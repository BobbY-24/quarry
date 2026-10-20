"""Complete-source, held-out evaluation with explicit false-negative evidence."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from pathlib import Path
from .config import DATA_TYPES
from .exports import canonical_json, dataset_record_view


def read_gold(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("Gold JSON must contain a list of complete-source annotations")
    return value


def _normalized(value: str) -> str:
    # Preserve case: case-sensitive medical entities and multilingual expressions
    # must not be collapsed by an English-only heuristic.
    return unicodedata.normalize("NFC", value)


def validate_gold(gold: list[dict], sources: list[dict], *, data_type: str | None = None) -> list[dict]:
    """Validate full-source annotations against the exact frozen source text."""
    if not isinstance(gold, list) or not gold:
        raise ValueError("Evaluation needs at least one complete held-out source annotation")
    if data_type is not None and (not isinstance(data_type, str) or data_type not in DATA_TYPES):
        raise ValueError("Unknown gold data_type")
    index = {source.get("source_id", source.get("id")): source for source in sources}
    seen = set()
    flattened = []
    for packet in gold:
        if not isinstance(packet, dict) or packet.get("complete") is not True:
            raise ValueError("Every evaluated source must explicitly have complete=true; candidate-only review cannot measure recall")
        source_id = packet.get("source_id")
        if source_id not in index or source_id in seen:
            raise ValueError(f"Unknown or duplicate gold source: {source_id}")
        seen.add(source_id)
        source = index[source_id]
        text = source["text"]
        expected_hash = source.get("text_sha256") or hashlib.sha256(text.encode("utf-8")).hexdigest()
        if packet.get("text_sha256") != expected_hash:
            raise ValueError(f"Gold source hash mismatch: {source_id}; annotate the exported frozen text")
        packet_type = packet.get("data_type", packet.get("record_type", "term"))
        if not isinstance(packet_type, str) or packet_type not in DATA_TYPES or data_type is not None and packet_type != data_type:
            raise ValueError("Gold data_type must match the frozen collection policy")
        terms = packet.get("terms" if packet_type == "term" else "records")
        if not isinstance(terms, list):
            raise ValueError("Gold terms/records must be a list (empty is valid for an exhaustively reviewed negative source)")
        unique = set()
        for term in terms:
            if not isinstance(term, dict):
                raise ValueError("Each gold record must be an object")
            expression = term.get("observed_text", term.get("expression"))
            if not isinstance(expression, str) or not expression or not isinstance(term.get("language"), str) or not term["language"]:
                raise ValueError("Each gold record requires verbatim expression/observed_text and language strings")
            if "expression" in term and "observed_text" in term and term["expression"] != term["observed_text"]:
                raise ValueError("Gold expression and observed_text disagree")
            if "sense" in term and "interpretation" in term and term["sense"] != term["interpretation"]:
                raise ValueError("Gold sense and interpretation disagree")
            record_type = term.get("record_type", term.get("data_type", packet_type))
            if not isinstance(record_type, str) or record_type not in DATA_TYPES or record_type != packet_type:
                raise ValueError("Gold record_type must match its complete-source packet")
            spans = term.get("occurrences", [{"start": term.get("start"), "end": term.get("end")}])
            if not isinstance(spans, list) or not spans:
                raise ValueError("Each gold record needs one or more exact occurrence spans")
            for span in spans:
                if not isinstance(span, dict):
                    raise ValueError("Each gold span must be an object")
                start, end = span.get("start"), span.get("end")
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                    raise ValueError(f"Invalid Unicode offsets for {expression!r}")
                if text[start:end] != expression:
                    raise ValueError(f"Gold expression does not match frozen text at [{start},{end})")
                row = {"source_id": source_id, "record_type": record_type, "expression": expression,
                       "observed_text": expression, "language": term["language"],
                       "sense": term.get("interpretation", term.get("sense")), "start": start, "end": end,
                       "domain": source.get("domain") or "unknown", "source_language": source.get("language") or "unknown"}
                marker = canonical_json(row)
                if marker in unique:
                    raise ValueError("Duplicate gold occurrence annotation")
                unique.add(marker)
                flattened.append(row)
    return flattened


def source_splits(sources: list[dict], *, seed: str = "termfinder-v1", ratios=(0.7, 0.15, 0.15), group_field: str | None = None) -> dict:
    """Assign whole sources/groups, never random occurrence rows, to splits."""
    if len(ratios) != 3 or any(type(x) not in (int, float) or x < 0 for x in ratios) or abs(sum(ratios) - 1) > 1e-9:
        raise ValueError("Split ratios must be three nonnegative values summing to 1")
    assignments = {"train": [], "validation": [], "test": []}
    seen = set()
    for source in sources:
        source_id = source.get("source_id", source.get("id"))
        if not isinstance(source_id, str) or source_id in seen:
            raise ValueError("Sources need unique string source_id values")
        seen.add(source_id)
        group = source_id if not group_field else source.get(group_field)
        if group is None:
            raise ValueError(f"Source {source_id} lacks split group field {group_field}")
        value = int(hashlib.sha256((seed + "\0" + canonical_json(group)).encode()).hexdigest(), 16) / 2**256
        label = "train" if value < ratios[0] else "validation" if value < ratios[0] + ratios[1] else "test"
        assignments[label].append(source_id)
    return {"seed": seed, "group_field": group_field or "source_id", "ratios": list(ratios), "splits": {label: sorted(ids) for label, ids in assignments.items()}, "warning": "Small source collections can produce empty splits. Freeze the split manifest before recipe/prompt tuning; evaluate only held-out sources."}


def _metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn, "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else (0.0 if precision is not None and recall is not None else None), "precision_reason": None if precision is not None else "no_predictions", "recall_reason": None if recall is not None else "no_gold_records"}


def evaluate(dataset: dict, gold: list[dict], *, unit: str = "occurrence", require_sense: bool = False, heldout_source_ids=None, data_type: str | None = None) -> dict:
    """Measure grounded extraction against complete-source human labels.

    occurrence matches exact source spans, record type, and language. source_term matches
    NFC expression + language within a source. Sense evaluation is opt-in and
    exact; free-text model proposals and human labels need a shared rubric.
    Ideas, opinions and sentences require occurrence matching; interpretation,
    attribution, truth, and sentence completeness remain separate judgments.
    """
    if unit not in {"occurrence", "source_term"}:
        raise ValueError("Evaluation unit must be occurrence or source_term")
    if data_type is None:
        data_type = dataset.get("recipe", {}).get("data_type", "term")
    if not isinstance(data_type, str) or data_type not in DATA_TYPES:
        raise ValueError("Unknown evaluation data_type")
    if data_type != "term" and unit != "occurrence":
        raise ValueError("Nonterm data types require exact-span occurrence evaluation")
    gold_rows = validate_gold(gold, dataset.get("sources", []), data_type=data_type)
    annotated_sources = {packet["source_id"] for packet in gold}
    if heldout_source_ids is not None and annotated_sources != set(heldout_source_ids):
        raise ValueError("Complete gold packets must cover exactly the declared held-out sources")
    if require_sense and any(row["sense"] is None for row in gold_rows):
        raise ValueError("Sense/interpretation matching requires a human label for every gold record")
    sources = {source.get("source_id", source.get("id")): source for source in dataset.get("sources", [])}
    terms = {record["record_id"]: record for record in dataset_record_view(dataset)}
    predicted = []
    for occurrence in dataset.get("occurrences", []):
        source_id = occurrence.get("source_id")
        if source_id not in annotated_sources:
            continue
        source = sources[source_id]
        term = terms.get(occurrence.get("record_id", occurrence.get("term_id")), {})
        record_type = occurrence.get("record_type", term.get("record_type", "term"))
        if record_type != data_type:
            continue
        expression = occurrence.get("observed_text", occurrence.get("expression", term.get("observed_text")))
        row = {"source_id": source_id, "record_type": record_type, "expression": expression,
               "observed_text": expression, "language": occurrence.get("language", term.get("language")),
               "sense": term.get("interpretation"), "start": occurrence.get("start"), "end": occurrence.get("end"),
               "domain": source.get("domain") or "unknown", "source_language": source.get("language") or "unknown"}
        if not isinstance(row["expression"], str) or not isinstance(row["language"], str):
            raise ValueError("Prediction requires expression and language")
        start, end = row["start"], row["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]) or source["text"][start:end] != row["expression"]:
            raise ValueError("Prediction occurrence is not grounded in frozen source text")
        predicted.append(row)

    def key(row):
        base = (row["record_type"], row["source_id"], row["language"], row["start"], row["end"]) if unit == "occurrence" else (row["record_type"], row["source_id"], row["language"], _normalized(row["expression"]))
        return base + (row["sense"],) if require_sense else base

    gold_map = {key(row): row for row in gold_rows}
    predicted_map = {key(row): row for row in predicted}
    true = gold_map.keys() & predicted_map.keys()
    false_positive = predicted_map.keys() - gold_map.keys()
    false_negative = gold_map.keys() - predicted_map.keys()
    groups = {"domain": defaultdict(lambda: [0, 0, 0]), "language": defaultdict(lambda: [0, 0, 0])}
    for index, keys, lookup in ((0, true, gold_map), (1, false_positive, predicted_map), (2, false_negative, gold_map)):
        for marker in keys:
            row = lookup[marker]
            groups["domain"][row["domain"]][index] += 1
            groups["language"][row["language"]][index] += 1
    def evidence(row):
        source = sources[row["source_id"]]
        return {**row, "context": source["text"][max(0, row["start"] - 120):row["end"] + 120], "locator": source.get("locator")}
    return {"schema_version": "1.1", "data_type": data_type, "dataset_version": dataset.get("version_id"), "gold_sha256": hashlib.sha256(canonical_json(gold).encode()).hexdigest(), "unit": unit, "require_sense": require_sense, "source_ids": sorted(annotated_sources), "heldout_assertion": heldout_source_ids is not None, "overall": _metrics(len(true), len(false_positive), len(false_negative)), "by_domain": {label: _metrics(*counts) for label, counts in sorted(groups["domain"].items())}, "by_language": {label: _metrics(*counts) for label, counts in sorted(groups["language"].items())}, "false_negatives": sorted((evidence(gold_map[marker]) for marker in false_negative), key=canonical_json), "false_positives": sorted((evidence(predicted_map[marker]) for marker in false_positive), key=canonical_json), "limitations": "Metrics depend on exhaustive human labels, a frozen research policy, and genuinely held-out sources. Default matching evaluates exact observed spans, not correctness of generated interpretations, factual truth, real-person opinion attribution, sentence completeness, or novelty. Counts and model agreement are not recall estimates."}
