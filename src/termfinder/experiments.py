"""Offline, complete-source comparisons. Inputs are data, never executable jobs.

Adapters retain raw proposals; the shared exact-span gate audits unsupported
ones separately from detection metrics on the accepted evidence inventory.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import unicodedata

from .config import DATA_TYPES, STAGES, _pairs
from .evaluation import _metrics, evaluate, validate_gold
from .exports import canonical_json, evidence_view, dataset_record_view

VERSION = "1"
STATUSES = frozenset({"complete", "partial", "failed", "pending", "uncertain", "excluded"})
PROVENANCE = {"software_revision", "model_version", "prompt_sha256", "configuration_sha256", "adapter_version"}


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 20000 and "\x00" not in value


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("Invalid experiment contract fields")


def _money(value):
    try:
        return value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _corpus(corpus):
    _fields(corpus, {"schema_version", "corpus_id", "data_type", "sources"})
    if corpus["schema_version"] != VERSION or not _text(corpus["corpus_id"]) or not isinstance(corpus["data_type"], str) or corpus["data_type"] not in DATA_TYPES:
        raise ValueError("Invalid experiment corpus version/type")
    if not isinstance(corpus["sources"], list) or not 1 <= len(corpus["sources"]) <= 5000:
        raise ValueError("Experiment needs 1–5000 frozen sources")
    sources = {}
    for source in corpus["sources"]:
        _fields(source, {"source_id", "text", "text_sha256", "domain", "language", "family_id"}, {"locator"})
        if any(not _text(source[key]) for key in ("source_id", "domain", "language", "family_id")):
            raise ValueError("Sources need explicit IDs, domain, language and family grouping")
        if not isinstance(source["text"], str) or len(source["text"]) > 16000000:
            raise ValueError("Frozen source text must be bounded")
        if source["source_id"] in sources or source["text_sha256"] != hashlib.sha256(source["text"].encode()).hexdigest():
            raise ValueError("Duplicate source ID or incorrect frozen text hash")
        sources[source["source_id"]] = source
    return sources


def _costs(rows):
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Run costs must be a bounded list")
    seen = set()
    for row in rows:
        _fields(row, {"stage", "known_usd", "uncertain_reserved_usd", "basis", "missing_reason"})
        if not _text(row["stage"]) or row["stage"] in seen:
            raise ValueError("Cost stages must be unique")
        seen.add(row["stage"])
        if not _money(row["known_usd"]) or not _money(row["uncertain_reserved_usd"]):
            raise ValueError("Costs must be finite, nonnegative numbers or null")
        if not isinstance(row["basis"], str) or row["basis"] not in {"simulated", "token_estimate", "provider_invoice", "not_metered"}:
            raise ValueError("Unknown cost measurement basis")
        if (row["known_usd"] is None or row["uncertain_reserved_usd"] is None) and not _text(row["missing_reason"]):
            raise ValueError("Unavailable cost information requires a reason")
        if row["basis"] == "not_metered" and row["known_usd"] is not None:
            raise ValueError("An unmetered cost cannot be reported as a known zero")
    if not set(STAGES) <= seen:
        raise ValueError("Declare all collector cost stages, including explicit unused stages")
    unknown = sorted(row["stage"] for row in rows if row["known_usd"] is None or row["uncertain_reserved_usd"] is None or row["uncertain_reserved_usd"] > 0)
    known = sum(row["known_usd"] or 0 for row in rows)
    reserved = sum(row["uncertain_reserved_usd"] or 0 for row in rows)
    if not _money(known) or not _money(reserved):
        raise ValueError("Aggregated cost is not finite")
    return {"stages": rows, "known_subtotal_usd": known,
            "uncertain_reserved_subtotal_usd": reserved,
            "incomplete_stages": unknown, "complete": not unknown,
            "note": "Known subtotals do not include unavailable costs or prove invoice totals. Simulation is not paid expenditure; declarations are not independently attested."}


def _run(run, corpus, sources, gold, unit, require_sense):
    _fields(run, {"schema_version", "run_id", "system", "data_type", "proposal_population", "provenance", "source_results", "predictions", "costs"})
    if run["schema_version"] != VERSION or run["data_type"] != corpus["data_type"] or not _text(run["run_id"]) or not _text(run["system"]):
        raise ValueError("Invalid run version/identity/type")
    if not isinstance(run["proposal_population"], str) or run["proposal_population"] not in {"raw_proposals", "grounded_inventory"}:
        raise ValueError("Declare whether predictions contain raw proposals or a grounded inventory")
    provenance = run["provenance"]
    _fields(provenance, PROVENANCE | {"unavailable_reasons"})
    if not isinstance(provenance["unavailable_reasons"], dict) or set(provenance["unavailable_reasons"]) - PROVENANCE:
        raise ValueError("Invalid provenance unavailable reasons")
    for key in PROVENANCE:
        if provenance[key] is None:
            if not _text(provenance["unavailable_reasons"].get(key)):
                raise ValueError("Unknown provenance requires an explicit reason")
        elif not _text(provenance[key]):
            raise ValueError("Invalid run provenance")
        elif key.endswith("sha256") and (len(provenance[key]) != 64 or any(c not in "0123456789abcdef" for c in provenance[key])):
            raise ValueError("Invalid provenance SHA-256")
    if not isinstance(run["source_results"], list):
        raise ValueError("One processing result is required for every source")
    results = {}
    for result in run["source_results"]:
        _fields(result, {"source_id", "text_sha256", "status", "reason"})
        sid = result["source_id"]
        if not isinstance(sid, str) or sid not in sources or sid in results or result["text_sha256"] != sources[sid]["text_sha256"]:
            raise ValueError("Run source inventory differs from the frozen corpus")
        if not isinstance(result["status"], str) or result["status"] not in STATUSES or (result["status"] != "complete" and not _text(result["reason"])):
            raise ValueError("Unknown source status or missing failure/partial reason")
        results[sid] = result
    if set(results) != set(sources):
        raise ValueError("Omitted sources must remain explicit pending/failed results")
    if not isinstance(run["predictions"], list) or len(run["predictions"]) > 100000:
        raise ValueError("Predictions must be a bounded list")
    accepted, invalid, attribute_issues, seen, exact_grounded = [], [], [], set(), 0
    for proposal in run["predictions"]:
        _fields(proposal, {"prediction_id", "source_id", "observed_text", "language", "start", "end", "interpretation"})
        pid, sid = proposal["prediction_id"], proposal["source_id"]
        if not _text(pid) or pid in seen or not isinstance(sid, str) or sid not in sources:
            raise ValueError("Predictions need unique IDs and declared source identities")
        seen.add(pid)
        reasons = []
        start, end, text = proposal["start"], proposal["end"], sources[sid]["text"]
        if not _text(proposal["observed_text"]) or not _text(proposal["language"]):
            reasons.append("missing_observed_text_or_language")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            reasons.append("invalid_unicode_codepoint_offsets")
        elif text[start:end] != proposal["observed_text"]:
            reasons.append("not_verbatim_at_reported_span")
        else:
            exact_grounded += 1
        if reasons:
            invalid.append({"proposal": proposal, "reasons": reasons})
        else:
            if proposal["interpretation"] is not None and not _text(proposal["interpretation"]):
                attribute_issues.append({"proposal": proposal, "reasons": ["invalid_interpretation_field"],
                                         "disposition": "kept_exact_evidence_interpretation_unavailable"})
                accepted.append({**proposal, "interpretation": None})
            else:
                accepted.append(proposal)
    # The existing scorer deliberately requires grounded predictions. Raw failures
    # are retained above rather than repaired or silently removed from diagnostics.
    records = [{"record_id": p["prediction_id"], "record_type": corpus["data_type"],
                "observed_text": p["observed_text"], "language": p["language"],
                "interpretation": p["interpretation"]} for p in accepted]
    dataset = {"version_id": run["run_id"], "recipe": {"data_type": corpus["data_type"]},
               "sources": list(sources.values()), "records": records,
               "occurrences": [{**p, "record_id": p["prediction_id"], "record_type": corpus["data_type"]} for p in accepted]}
    detection = evaluate(dataset, gold, unit=unit, require_sense=require_sense, heldout_source_ids=list(sources))
    per_source = []
    observations_by_source, records_by_source = defaultdict(list), defaultdict(list)
    for record, occurrence in zip(records, dataset["occurrences"]):
        observations_by_source[occurrence["source_id"]].append(occurrence)
        records_by_source[occurrence["source_id"]].append(record)
    for packet in sorted(gold, key=lambda p: p["source_id"]):
        sid = packet["source_id"]
        single = {"recipe": dataset["recipe"], "sources": [sources[sid]],
                  "records": records_by_source[sid], "occurrences": observations_by_source[sid]}
        metrics = evaluate(single, [packet], unit=unit, require_sense=require_sense)["overall"]
        per_source.append({**results[sid], "domain": sources[sid]["domain"], "language": sources[sid]["language"],
                           "family_id": sources[sid]["family_id"], **metrics})
    identities = {(p["source_id"], p["start"], p["end"], p["language"], p["interpretation"] if require_sense else None) for p in accepted}
    statuses = dict(sorted(Counter(r["status"] for r in results.values()).items()))
    return {"run_id": run["run_id"], "system": run["system"], "provenance": provenance,
            "detection": detection, "by_source": per_source, "by_domain": detection["by_domain"], "by_language": detection["by_language"],
            "raw_proposals": {"submitted": len(seen), "exact_grounded": exact_grounded, "accepted_predictions": len(accepted), "invalid": len(invalid),
                              "attribute_issues": len(attribute_issues), "attribute_issue_queue": attribute_issues,
                              "duplicate_grounded_observations": len(accepted) - len(identities),
                              "population": run["proposal_population"],
                              "exact_grounding_rate": exact_grounded / len(seen) if seen and run["proposal_population"] == "raw_proposals" else None,
                              "exact_grounding_rate_reason": "raw_proposals_not_supplied" if run["proposal_population"] != "raw_proposals" else None if seen else "no_proposals", "invalid_queue": invalid},
            "coverage": {"source_count": len(sources), "status_counts": statuses,
                         "complete_fraction": statuses.get("complete", 0) / len(sources),
                         "note": "Statuses describe declared operational completion, not verified recall. Failed, partial, excluded and pending sources retain their gold positives in the denominator."},
            "costs": _costs(run["costs"])}


def _delta(left, right):
    return {metric: right[metric] - left[metric] if left[metric] is not None and right[metric] is not None else None
            for metric in ("precision", "recall", "f1")}


def _bootstrap(left, right, samples, seed):
    families = defaultdict(lambda: [[0, 0, 0], [0, 0, 0]])
    for arm, report in enumerate((left, right)):
        for source in report["by_source"]:
            for i, field in enumerate(("true_positives", "false_positives", "false_negatives")):
                families[source["family_id"]][arm][i] += source[field]
    keys = sorted(families)
    values = {metric: [] for metric in ("precision", "recall", "f1")}
    if samples and len(keys) >= 2:
        rng = random.Random(seed + "\0" + left["run_id"] + "\0" + right["run_id"])
        for _ in range(samples):
            totals = [[0, 0, 0], [0, 0, 0]]
            for _ in keys:
                family = families[rng.choice(keys)]
                for arm in range(2):
                    for index in range(3):
                        totals[arm][index] += family[arm][index]
            for metric, delta in _delta(_metrics(*totals[0]), _metrics(*totals[1])).items():
                if delta is not None:
                    values[metric].append(delta)
    def interval(observed):
        observed.sort()
        # Do not silently condition an interval on defined replicates: negative-only
        # resamples can make precision or recall undefined.
        if not samples or len(keys) < 2 or len(observed) != samples:
            return None
        def quantile(q):
            position = (len(observed) - 1) * q
            low, high = math.floor(position), math.ceil(position)
            return observed[low] + (observed[high] - observed[low]) * (position - low)
        return [quantile(.025), quantile(.975)]
    return {"method": "paired_family_cluster_percentile_bootstrap", "seed": seed, "family_count": len(keys),
            "requested_replicates": samples, "intervals_95": {metric: interval(items) for metric, items in values.items()},
            "effective_replicates": {metric: len(items) for metric, items in values.items()},
            "null_reason": "not_requested" if not samples else "fewer_than_two_families" if len(keys) < 2 else "undefined_metric_replicates" if any(len(v) != samples for v in values.values()) else None,
            "note": "Micro-metric deltas resample paired independent families. Intervals do not establish representativeness, annotation quality, power, or causal attribution."}


def compare_experiments(corpus, gold, runs, *, unit="occurrence", require_sense=False, bootstrap_samples=0, seed="quarry-study-v1"):
    """Compare normalized frozen runs without fetching sources or invoking models."""
    sources = _corpus(corpus)
    if not isinstance(unit, str) or unit not in {"occurrence", "source_term"}:
        raise ValueError("Comparison unit must be occurrence or source_term")
    if type(require_sense) is not bool or type(bootstrap_samples) is not int or not 0 <= bootstrap_samples <= 10000 or not _text(seed):
        raise ValueError("Invalid finite comparison settings")
    if not isinstance(runs, list) or not 2 <= len(runs) <= 20:
        raise ValueError("A comparison needs 2–20 separately identified runs")
    families = {source["family_id"] for source in sources.values()}
    if bootstrap_samples * len(families) * len(runs) * (len(runs) - 1) // 2 > 5000000:
        raise ValueError("Aggregate bootstrap work exceeds five million paired family draws; compare fewer arms or use fewer replicates")
    gold_rows = validate_gold(gold, list(sources.values()), data_type=corpus["data_type"])
    if any(row["sense"] is not None and not _text(row["sense"]) for row in gold_rows):
        raise ValueError("Gold interpretation/sense labels must be nonempty strings or null")
    if {p["source_id"] for p in gold} != set(sources):
        raise ValueError("Complete gold must cover the whole declared comparison corpus, including negative and failed sources")
    reports, ids = [], set()
    for run in runs:
        report = _run(run, corpus, sources, gold, unit, require_sense)
        if report["run_id"] in ids:
            raise ValueError("Duplicate experimental run ID")
        ids.add(report["run_id"])
        reports.append(report)
    pairs = []
    for i, left in enumerate(reports):
        for right in reports[i + 1:]:
            # Unique recovered gold units use the shared scorer's FN identities.
            def missed(report):
                def identity(row):
                    key = (row["source_id"], row["language"], row["start"], row["end"]) if unit == "occurrence" else (row["source_id"], row["language"], unicodedata.normalize("NFC", row["expression"]))
                    return key + (row["sense"],) if require_sense else key
                return {identity(row) for row in report["detection"]["false_negatives"]}
            left_miss, right_miss = missed(left), missed(right)
            pairs.append({"left": left["run_id"], "right": right["run_id"], "direction": "right_minus_left",
                          "delta": _delta(left["detection"]["overall"], right["detection"]["overall"]),
                          "unique_gold_recoveries": {left["run_id"]: len(right_miss - left_miss), right["run_id"]: len(left_miss - right_miss)},
                          "uncertainty": _bootstrap(left, right, bootstrap_samples, seed)})
    return {"schema_version": VERSION, "corpus_id": corpus["corpus_id"], "data_type": corpus["data_type"],
            "inputs": {"corpus_sha256": _hash(corpus), "gold_sha256": _hash(gold), "run_sha256": {run["run_id"]: _hash(run) for run in runs}},
            "evaluator": {"adapter_version": VERSION, "matching_unit": unit, "require_sense": require_sense,
                          "code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ("experiments.py", "evaluation.py", "exports.py")}},
            "runs": reports, "pairs": pairs,
            "limitations": ["Exact occurrence checks do not establish interpretation correctness, novelty or valid research-policy membership.",
                            "Detection metrics score the grounded inventory; raw unsupported proposals are audited separately and are not silently called correct.",
                            "Gold completeness, blinding, family independence and run provenance are declarations requiring study documentation.",
                            "Comparisons do not control model, prompt, cost, parser or cache differences automatically; specify matched and native tracks."]}


def _read_input(path):
    # Hash and parse the same bounded buffer; do not reopen a changing file.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32000000:
            raise ValueError("Study inputs must be bounded regular files")
        raw = handle.read(32000001)
        if len(raw) > 32000000:
            raise ValueError("Study input exceeds its size bound")
    return raw


def _decode(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def compare_study(path):
    """Load a bounded local study. Paths cannot escape its directory, even by symlink."""
    path = Path(path).resolve()
    study_bytes = _read_input(path)
    study = _decode(study_bytes)
    _fields(study, {"schema_version", "corpus", "gold", "runs"}, {"unit", "require_sense", "bootstrap_samples", "seed"})
    if study["schema_version"] != VERSION or not isinstance(study["runs"], list) or not 2 <= len(study["runs"]) <= 20:
        raise ValueError("Invalid study version or run list")
    if any(not _text(name) for name in [study["corpus"], study["gold"], *study["runs"]]) or len(set(study["runs"])) != len(study["runs"]):
        raise ValueError("Study file references must be bounded strings and run paths must be distinct")
    files = {}
    def load(name, *, jsonl=False):
        if not _text(name) or Path(name).is_absolute():
            raise ValueError("Study inputs must use relative local paths")
        target = (path.parent / name).resolve()
        if not target.is_relative_to(path.parent):
            raise ValueError("Study input is missing, escapes its directory or exceeds its size bound")
        raw = _read_input(target)
        files[name] = hashlib.sha256(raw).hexdigest()
        if not jsonl:
            return _decode(raw)
        return [_decode(line.encode("utf-8")) for line in raw.decode("utf-8").splitlines() if line.strip()]
    corpus = load(study["corpus"])
    gold = load(study["gold"], jsonl=Path(study["gold"]).suffix.lower() == ".jsonl")
    runs = [load(name) for name in study["runs"]]
    report = compare_experiments(corpus, gold, runs, **{key: study[key] for key in ("unit", "require_sense", "bootstrap_samples", "seed") if key in study})
    report["input_files_sha256"] = dict(sorted(files.items()))
    report["study_sha256"] = _hash(study)
    report["study_file_sha256"] = hashlib.sha256(study_bytes).hexdigest()
    return report


def quarry_run(dataset, *, run_id, software_revision=None):
    """Normalize a frozen Quarry snapshot. Completion remains operational only.

    Use a fresh arm-only project. Pauses/resumes may share its unchanged config;
    changed historical configurations must be compared as separate snapshots.
    This does not invent missing acquisition/parse-failure source text. Include
    those sources in the externally frozen corpus and an explicit result row.
    """
    record_index = {r["record_id"]: r for r in dataset_record_view(dataset)}
    history = dataset.get("runs", [])
    if any(r.get("recipe") != dataset.get("recipe") or r.get("profile") != dataset.get("profile") for r in history):
        raise ValueError("Comparison snapshots must come from a fresh arm with one unchanged configuration")
    latest = max(history, key=lambda r: r.get("created_at", ""), default={})
    planning_complete = latest.get("planning_complete") is True
    predictions = []
    for index, occurrence in enumerate(evidence_view(dataset)):
        predictions.append({"prediction_id": occurrence.get("occurrence_id") or f"observation-{index}",
                            "source_id": occurrence["source_id"], "observed_text": occurrence["observed_text"],
                            "language": occurrence.get("language", record_index[occurrence["record_id"]]["language"]),
                            "start": occurrence["start"], "end": occurrence["end"],
                            "interpretation": record_index[occurrence["record_id"]].get("interpretation")})
    results = []
    for source in dataset["sources"]:
        jobs = [j for j in dataset.get("jobs", []) if j["source_id"] == source["source_id"] and j["status"] != "split"]
        statuses = {j["status"] for j in jobs}
        status = "complete" if statuses == {"done"} and planning_complete else "uncertain" if "uncertain" in statuses else "partial" if "done" in statuses or any(p["source_id"] == source["source_id"] for p in predictions) else "failed" if statuses == {"failed"} else "excluded" if source.get("scope_exclusion") else "pending"
        results.append({"source_id": source["source_id"], "text_sha256": source["text_sha256"], "status": status,
                        "reason": None if status == "complete" else "quarry_job_states:" + ",".join(sorted(statuses or {source.get("scope_exclusion") or "no_jobs"})) + (";planning_coverage_unproven" if not planning_complete else "")})
    raw_costs = dataset.get("costs", [])
    billing = {c.get("billing_kind") for c in raw_costs}
    if "simulated" in billing and len(billing) > 1:
        raise ValueError("Separate simulated and live experiment projects")
    simulated = billing == {"simulated"} or bool(dataset.get("profile", {}).get("providers")) and all(p.get("adapter") == "fake" for p in dataset["profile"]["providers"].values())
    costs = []
    for stage in STAGES:
        entries = [c for c in raw_costs if c["stage"] == stage]
        costs.append({"stage": stage, "known_usd": sum(c.get("settled_usd") or 0 for c in entries),
                      "uncertain_reserved_usd": sum(c.get("reserved_usd") or 0 for c in entries if c.get("settled_usd") is None),
                      "basis": "simulated" if simulated else "token_estimate", "missing_reason": None})
    if not simulated:
        for stage in ("external_planning", "human_review", "infrastructure"):
            costs.append({"stage": stage, "known_usd": None, "uncertain_reserved_usd": None,
                          "basis": "not_metered", "missing_reason": "not_measured_by_snapshot_bridge"})
    models = {key: value.get("version") for key, value in dataset.get("profile", {}).get("models", {}).items()}
    provenance = {"software_revision": software_revision, "model_version": canonical_json(models) if models and all(_text(v) for v in models.values()) else None,
                  "prompt_sha256": _hash(dataset["prompts"]) if dataset.get("prompts") else None,
                  "configuration_sha256": _hash({"recipe": dataset["recipe"], "profile": dataset["profile"]}) if dataset.get("recipe") and dataset.get("profile") else None,
                  "adapter_version": VERSION}
    provenance["unavailable_reasons"] = {key: "not_supplied_in_snapshot_or_by_operator" for key, value in provenance.items() if value is None}
    return {"schema_version": VERSION, "run_id": run_id, "system": "quarry", "data_type": dataset.get("recipe", {}).get("data_type", "term"), "proposal_population": "grounded_inventory",
            "provenance": provenance,
            "source_results": results, "predictions": predictions, "costs": costs}
