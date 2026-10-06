"""Deterministic exports of immutable dataset snapshots. No provider calls occur here."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

TABLES = ("terms", "records", "occurrences", "evidence", "sources", "runs", "jobs", "audit", "annotations", "relations", "discovery", "costs")
FORMATS = frozenset({"csv", "jsonl", "parquet", "annotation"})
EXPORT_SCHEMA_VERSION = "1.1"
DEFAULT_COLUMNS = {
    "terms": ("term_id", "expression", "language", "community", "sense", "review_status"),
    "records": ("record_id", "record_type", "observed_text", "language", "interpretation", "interpretation_origin", "review_status"),
    "occurrences": ("occurrence_id", "term_id", "source_id", "start", "end", "context"),
    "evidence": ("occurrence_id", "record_id", "record_type", "source_id", "observed_text", "start", "end", "context"),
    "sources": ("source_id", "locator", "text", "text_sha256", "raw_sha256"),
    "runs": ("id", "status"), "jobs": ("id", "source_id", "status"),
    "audit": ("id", "source_id", "reason"), "annotations": ("id", "term_id", "status"),
    "relations": ("id", "term_a", "term_b", "kind"),
    "discovery": ("id", "decision"), "costs": ("stage", "amount_usd"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _records(value: Any) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Dataset tables must be lists of JSON objects")
    return sorted(value, key=canonical_json)


def record_view(rows: list[dict]) -> list[dict]:
    """Expose typed observed records without presenting nonterms as vocabulary.

    Storage retains term_id as a compatibility alias; public record_id has the
    same stable value. Generated interpretations never replace observed text.
    Legacy term records without record_type are interpreted as lexical terms.
    """
    lexical_fields = {"expression", "original_spellings", "normalized_expression", "sense", "sense_reason",
                      "meaning_status", "source_supported_definition", "coinage_date", "coinage_date_reason"}
    result = []
    for row in _records(rows):
        record = {key: value for key, value in row.items() if key not in lexical_fields}
        record.update(record_id=row.get("record_id", row.get("term_id", row.get("id"))),
                      record_type=row.get("record_type", "term"),
                      observed_text=row.get("observed_text", row.get("expression")),
                      observed_variants=row.get("observed_variants", row.get("original_spellings", [row.get("observed_text", row.get("expression"))])),
                      normalized_observed_text=row.get("normalized_observed_text", row.get("normalized_expression")),
                      interpretation=row.get("interpretation", row.get("sense")),
                      interpretation_reason=row.get("interpretation_reason", row.get("sense_reason")),
                      interpretation_origin=row.get("interpretation_origin", "model_generated" if row.get("sense") else None),
                      interpretation_status=row.get("interpretation_status", row.get("meaning_status", "unresolved")),
                      source_support_quote=row.get("source_support_quote", row.get("source_supported_definition")),
                      text_origin="observed_source")
        result.append(record)
    return _records(result)


def dataset_record_view(dataset: dict) -> list[dict]:
    """Combine saved generic records and legacy lexical rows by stable ID."""
    result = {row["record_id"]: row for row in record_view(dataset.get("terms", []))}
    result.update({row["record_id"]: row for row in record_view(dataset.get("records", []))})
    return _records(list(result.values()))


def evidence_view(dataset: dict, records=None) -> list[dict]:
    index = {row["record_id"]: row for row in (records if records is not None else dataset_record_view(dataset))}
    result = []
    for occurrence in _records(dataset.get("occurrences")):
        record_id = occurrence.get("record_id", occurrence.get("term_id"))
        record = index.get(record_id, {})
        result.append({**occurrence, "record_id": record_id,
                       "record_type": occurrence.get("record_type", record.get("record_type", "term")),
                       "observed_text": occurrence.get("observed_text", occurrence.get("expression", record.get("observed_text")))})
    return _records(result)


def _flat(row: dict) -> dict:
    return {key: canonical_json(value) if isinstance(value, (dict, list)) else value for key, value in row.items()}


def _csv_cell(value):
    if isinstance(value, str) and (value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


def _columns(name: str, records: list[dict]) -> list[str]:
    keys = set().union(*(row.keys() for row in records)) if records else set(DEFAULT_COLUMNS[name])
    preferred = [key for key in DEFAULT_COLUMNS[name] if key in keys]
    return preferred + sorted(keys.difference(preferred))


def _parquet_column(values, arrow):
    nonnull = [value for value in values if value is not None]
    kinds = {type(value) for value in nonnull}
    if not kinds or kinds == {str}:
        return arrow.string(), "native"
    if kinds == {bool}:
        return arrow.bool_(), "native"
    if kinds == {int} and all(-(2**63) <= value < 2**63 for value in nonnull):
        return arrow.int64(), "native"
    if kinds <= {int, float} and all(type(value) is not int or abs(value) <= 2**53 for value in nonnull):
        return arrow.float64(), "native"
    # Arbitrary research attributes, heterogeneous scalars and oversized integers
    # cannot share a safe Arrow scalar type. Canonical JSON preserves all values.
    return arrow.string(), "canonical_json"


def _jsonl(records: list[dict]) -> bytes:
    return "".join(canonical_json(row) + "\n" for row in records).encode("utf-8")


def annotation_sources(dataset: dict) -> list[dict]:
    """Blank complete-source gold packets; candidate review alone cannot find FNs."""
    data_type = dataset.get("recipe", {}).get("data_type", "term")
    packets = [{
        "source_id": source.get("source_id", source.get("id")),
        "text": source.get("text", ""),
        "text_sha256": source.get("text_sha256"),
        "locator": source.get("locator"),
        "language": source.get("language"), "domain": source.get("domain"),
        "community": source.get("community"), "constraints": source.get("constraints"),
        "data_type": data_type,
        "research_policy": {key: dataset.get("recipe", {}).get(key) for key in ("id", "version", "data_type", "research_question", "inclusion_criteria", "exclusion_criteria", "languages", "communities", "dates")},
        "blocks": source.get("blocks", []), "complete": False,
        "annotator": None, "annotation_date": None,
        "terms" if data_type == "term" else "records": [],
        "instructions": f"Annotate ALL in-scope {data_type} records in this entire source. Each expression/observed_text must be an exact contiguous source span; mark record_type={data_type}. Set complete=true only after reviewing the full text. Offsets are Unicode code points, half-open [start,end). Record distinct senses/interpretations separately. Generated paraphrases belong only in interpretation, never observed_text.",
    } for source in _records(dataset.get("sources"))]
    return packets


def export_dataset(dataset: dict, out: Path, formats=None) -> dict:
    out=Path(out)
    if out.is_symlink(): raise ValueError("Export destination must not be a symbolic link")
    out.mkdir(parents=True,exist_ok=True)
    # Stage on disk: an interruption cannot publish a half-written data file.
    with tempfile.TemporaryDirectory(prefix=".termfinder-export-",dir=out) as staging:
        return _export_dataset(dataset,out,formats,Path(staging))


class StagedFiles:
    def __init__(self,path): self.path,self.metadata=path,{}
    def __setitem__(self,name,data):
        (self.path/name).write_bytes(data)
        self.finish(name)
    def finish(self,name): self.metadata[name]=_file_metadata(self.path/name)
    def json(self,name,value):
        with (self.path/name).open("w",encoding="utf-8",newline="\n") as stream:
            for chunk in json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).iterencode(value): stream.write(chunk)
            stream.write("\n")
        self.finish(name)
    def jsonl(self,name,rows):
        with (self.path/name).open("w",encoding="utf-8",newline="\n") as stream:
            for row in rows: stream.write(canonical_json(row)+"\n")
        self.finish(name)


def _file_metadata(path):
    checksum=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""): checksum.update(block)
    return {"sha256":checksum.hexdigest(),"bytes":path.stat().st_size}


def _export_dataset(dataset: dict, out: Path, formats, staging) -> dict:
    """Write deterministic CSV/JSONL/Parquet and annotation packets with hashes.

    Parquet homogeneous scalar columns retain native types. Nested/heterogeneous
    values use canonical JSON strings, with per-column encoding in schema.json.
    Existing nonidentical files are refused, preserving older dataset exports.
    """
    formats = list(dict.fromkeys(formats or ("csv", "jsonl", "parquet", "annotation")))
    if set(formats).difference(FORMATS):
        raise ValueError("Unknown export format; use csv, jsonl, parquet, annotation")
    if not dataset.get("version_id") or "schema_version" not in dataset:
        raise ValueError("Export requires a saved dataset snapshot with version_id and schema_version")
    # Derive generic views without mutating or regenerating the frozen dataset.
    records = dataset_record_view(dataset)
    tables = {**dataset, "records": records, "evidence": evidence_view(dataset, records),
              "terms": [row for row in _records(dataset.get("terms")) if row.get("record_type", "term") == "term"]}
    arrow = None
    if "parquet" in formats:
        try:
            import pyarrow as arrow
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise RuntimeError("Parquet export requires the pinned pyarrow dependency; install termfinder with its dependencies or select csv,jsonl,annotation") from exc
    out = Path(out)
    if out.is_symlink():
        raise ValueError("Export destination must not be a symbolic link")
    out.mkdir(parents=True, exist_ok=True)
    files = StagedFiles(staging)
    schemas = {}
    for name in TABLES:
        rows = _records(tables.get(name))
        columns = _columns(name, rows)
        schemas[name] = {"columns": columns, "records": len(rows), "nested_values": "canonical JSON strings in CSV and Parquet; native JSON in JSONL", "null_values": "JSON null / Parquet null / empty CSV cell; use JSONL or Parquet to distinguish null from empty string"}
        if "jsonl" in formats:
            files.jsonl(name + ".jsonl", rows)
        if "csv" in formats:
            escape_column = "__csv_escaped_columns"
            while escape_column in columns:
                escape_column = "_" + escape_column
            with (staging/(name+".csv")).open("w",encoding="utf-8",newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns + [escape_column], lineterminator="\n")
                writer.writeheader()
                for original in rows:
                    row=_flat(original)
                    row={column:row.get(column) for column in columns}
                    safe = {key: _csv_cell(value) for key, value in row.items()}
                    safe[escape_column] = canonical_json([key for key in columns if safe[key] != row[key]])
                    writer.writerow(safe)
            files.finish(name + ".csv")
            schemas[name]["csv_escape_column"] = escape_column
        if "parquet" in formats:
            specs = {column: _parquet_column([row.get(column) for row in rows], arrow) for column in columns}
            arrow_schema=arrow.schema([(column, specs[column][0]) for column in columns])
            with parquet.ParquetWriter(staging/(name+".parquet"),arrow_schema,compression="zstd",version="2.6",use_dictionary=False,write_statistics=False) as writer:
                for start in range(0,max(1,len(rows)),256):
                    portable=[{column: None if row.get(column) is None else canonical_json(row[column]) if specs[column][1] == "canonical_json" else row[column] for column in columns} for row in rows[start:start+256]]
                    writer.write_table(arrow.Table.from_pylist(portable,schema=arrow_schema))
            files.finish(name + ".parquet")
            schemas[name]["parquet_columns"] = {column: {"type": str(specs[column][0]), "encoding": specs[column][1]} for column in columns}
            schemas[name]["parquet_encoding"] = "Homogeneous scalar columns are native Arrow types; only columns marked canonical_json need json.loads on non-null cells. Nulls remain null. Nested and heterogeneous values retain exact JSON types and Unicode."
    if "annotation" in formats:
        files.jsonl("annotation_sources.jsonl",annotation_sources(dataset))
        files.jsonl("annotation_candidates.jsonl",records)
        files.jsonl("approved_records.jsonl",(row for row in records if row.get("review_status", row.get("status")) == "approved"))
        files.jsonl("approved_terms.jsonl",(row for row in tables["terms"] if row.get("review_status", row.get("status")) == "approved"))
    schema = {"export_schema_version": EXPORT_SCHEMA_VERSION, "dataset_schema_version": dataset["schema_version"], "offsets": "Unicode code points in extracted source text; half-open [start,end)", "tables": schemas, "record_contract": "records includes all configured data types; terms contains lexical terms only. record_id equals the legacy storage term_id alias. observed_text is an exact source span; interpretation is a generated suggestion, not observed evidence. evidence retains original contexts and source IDs. Type checks prove occurrence, not meaning, factual truth, opinion attribution, sentence completeness, or novelty.", "csv_formula_protection": "Potential spreadsheet formula strings (leading =,+,-,@ after whitespace, or initial tab/CR/LF) are prefixed with an apostrophe. Each CSV row has a JSON list of modified column names in its csv_escape_column named by this table schema. To restore values, remove exactly one leading apostrophe from those columns before using evidence offsets. Use JSONL or decoded Parquet for original typed records; CSV null/empty cells remain ambiguous.", "annotation_sources": "Complete-source gold template for held-out evaluation. Blank terms/records and complete=false are deliberate; do not use candidate-only review to measure recall."}
    files["schema.json"] = (canonical_json(schema) + "\n").encode("utf-8")
    files.json("dataset.json",dataset)
    if "compute_execution" in dataset:
        files["compute_execution.json"] = (canonical_json(dataset["compute_execution"]) + "\n").encode("utf-8")
    if dataset.get("agent_workflow", {}).get("events"):
        from .publication import audit_dataset
        files["agent_workflow.json"] = (canonical_json(dataset["agent_workflow"]) + "\n").encode("utf-8")
        files["publication_audit.json"] = (canonical_json(audit_dataset(dataset)) + "\n").encode("utf-8")
    source_inventory = [{key: source.get(key) for key in ("source_id", "locator", "retrieved_at", "publication_date", "publication_date_reason", "raw_sha256", "text_sha256", "parser_version", "language", "domain", "community", "constraints")} for source in _records(dataset.get("sources"))]
    model_provenance = []
    for occurrence in _records(dataset.get("occurrences")):
        for entry in occurrence.get("provenance", []):
            model_provenance.append({key: entry.get(key) for key in ("provider", "model", "configured_model_version", "reported_model_version", "reported_model_version_reason", "prompt_version", "prompt_sha256", "expert_id", "run_id", "transport_identity", "record_type", "observed_text_contract", "interpretation_origin")})
            model_provenance[-1].update({key: entry[key] for key in
                ("runtime", "declared_cluster_runtime", "declared_cluster_runtime_reason", "request_decoding", "token_admission", "token_admission_reason") if key in entry})
    model_provenance = sorted({canonical_json(row) for row in model_provenance})
    manifest = {"export_schema_version": EXPORT_SCHEMA_VERSION, "version_id": dataset["version_id"], "dataset_sha256": files.metadata["dataset.json"]["sha256"], "formats": sorted(formats), "tables": {name: len(_records(tables.get(name))) for name in TABLES}, "files": dict(sorted(files.metadata.items())), "frozen_metadata": {key: dataset.get(key) for key in ("schema_version", "name", "created_at", "recipe", "profile", "prompts", "coverage", "failures", "constraints")}, "source_inventory": source_inventory, "model_provenance": [json.loads(row) for row in model_provenance], "costs": dataset.get("costs", []), "collection_runs": dataset.get("runs", []), "schema_file": "schema.json", "reproduction": "All records derive from this saved snapshot. Export performs no model calls. JSONL and CSV are byte reproducible; Parquet bytes are reproducible with the pinned pyarrow version."}
    if "compute_execution" in dataset:
        manifest["compute_execution"] = dataset["compute_execution"]
    files["manifest.json"] = (canonical_json(manifest) + "\n").encode("utf-8")
    # Preflight the entire result before writing any new file.
    for name, metadata in files.metadata.items():
        target = out / name
        if target.is_symlink():
            raise ValueError(f"Export target must not be a symbolic link: {target}")
        if target.exists() and _file_metadata(target) != metadata:
            raise FileExistsError(f"Refusing to overwrite a different export: {target}")
    # Publish the manifest last as the dataset completion marker. Atomic links
    # refuse concurrent overwrites; interrupted staging directories are ignored.
    for name in sorted(files.metadata,key=lambda name:(name=="manifest.json",name)):
        target = out / name
        if not target.exists():
            os.link(staging/name,target)
    return {"out": str(out.resolve()), "version_id": dataset["version_id"], "manifest": manifest}
