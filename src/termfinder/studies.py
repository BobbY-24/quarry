"""Validated, append-only V7 study contracts. Specifications are inert data.

No function here dispatches providers, imports adapter code, or authorizes paid
work. Prediction locking precedes reading independently held external gold.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path

from .experiments import PROVENANCE, STATUSES, _corpus, _costs, _decode, _hash, _read_input, compare_experiments
from .exports import canonical_json

VERSION = "7.0"
LIMITS = frozenset({"calls", "input_tokens", "output_tokens", "seconds", "spending_usd", "allocation_hours"})
SPLITS = frozenset({"development", "calibration", "heldout"})


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) != set(required) | (set(value) & set(optional)):
        raise ValueError("Invalid V7 contract fields")


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 20000 and "\x00" not in value


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _strings(value, *, nonempty=False):
    return isinstance(value, list) and (not nonempty or bool(value)) and len(value) <= 1000 and all(_text(v) for v in value)


def _finite(value, *, integer=False):
    return type(value) in ((int,) if integer else (int, float)) and 0 <= value <= 1e12 and math.isfinite(value)


def _provenance(value):
    _fields(value, PROVENANCE | {"unavailable_reasons"})
    reasons = value["unavailable_reasons"]
    if not isinstance(reasons, dict) or set(reasons) - PROVENANCE:
        raise ValueError("Invalid provenance unavailable reasons")
    for key in PROVENANCE:
        if value[key] is None:
            if not _text(reasons.get(key)):
                raise ValueError("Unknown provenance needs a reason")
        elif not (_sha(value[key]) if key.endswith("sha256") else _text(value[key])) or key in reasons:
            raise ValueError("Invalid provenance value or contradictory unavailable reason")


def validate_study(spec, corpus=None):
    """Return a defensive copy of a complete draft/frozen study specification.

    States and history are repository metadata, not fields authors may forge.
    All resources have finite caps, including zero for an offline-only study.
    """
    _fields(spec, {"schema_version", "study_id", "research_question", "hypothesis", "contribution",
                   "primary_contrast", "primary_outcome", "secondary_analyses", "policy", "corpus", "gold",
                   "arms", "repetitions", "seeds", "run_order", "cache", "limits", "stopping_rules",
                   "planned_exclusions", "unavailable_reasons"})
    if spec["schema_version"] != VERSION or any(not _text(spec[k]) for k in ("study_id", "research_question", "hypothesis", "contribution")):
        raise ValueError("Invalid V7 study identity or research statement")
    contrast = spec["primary_contrast"]
    _fields(contrast, {"left", "right", "direction", "rival_explanations"})
    if not isinstance(contrast["direction"], str) or contrast["direction"] not in {"right_minus_left", "left_minus_right"} or not _strings(contrast["rival_explanations"], nonempty=True):
        raise ValueError("Predeclare a contrast direction and rival explanations")
    outcome = spec["primary_outcome"]
    _fields(outcome, {"metric", "unit", "analysis", "quality_margin", "unavailable_reason"})
    if any(not _text(outcome[k]) for k in ("metric", "analysis")) or not isinstance(outcome["unit"], str) or outcome["unit"] not in {"occurrence", "source_term", "semantic", "active_seconds", "recovery", "usability"}:
        raise ValueError("Invalid predeclared primary outcome")
    if outcome["quality_margin"] is None:
        if not _text(outcome["unavailable_reason"]):
            raise ValueError("A null quality margin needs a reason (including not applicable)")
    elif not _finite(outcome["quality_margin"]) or outcome["unavailable_reason"] is not None:
        raise ValueError("Invalid quality margin")
    if not _strings(spec["secondary_analyses"]):
        raise ValueError("Secondary analyses must be explicit bounded text")
    _fields(spec["policy"], {"inclusion", "exclusion", "annotation_rubric"})
    if any(not _text(spec["policy"][k]) for k in ("inclusion", "exclusion")):
        raise ValueError("Declare inclusion and exclusion policies")
    rubric = spec["policy"]["annotation_rubric"]
    if not isinstance(rubric, dict) or set(rubric) != {"eligibility", "contextual_meaning", "definition_support", "translation"} or any(not _text(v) for v in rubric.values()):
        raise ValueError("Annotation rubric needs all four semantic axes")
    manifest = spec["corpus"]
    _fields(manifest, {"corpus_id", "corpus_sha256", "sources", "scope", "acquisition_provenance"})
    if not _text(manifest["corpus_id"]) or not _sha(manifest["corpus_sha256"]) or not isinstance(manifest["scope"], str) or manifest["scope"] not in {"frozen_parsed_text", "end_to_end"} or not _text(manifest["acquisition_provenance"]):
        raise ValueError("Declare corpus hash and acquisition/parsing scope")
    if not isinstance(manifest["sources"], list) or not 1 <= len(manifest["sources"]) <= 5000:
        raise ValueError("Study needs a bounded complete corpus manifest")
    identities, families = {}, {}
    for source in manifest["sources"]:
        _fields(source, {"source_id", "text_sha256", "family_id", "split"})
        if not _text(source["source_id"]) or not _text(source["family_id"]) or not _sha(source["text_sha256"]) or not isinstance(source["split"], str) or source["split"] not in SPLITS or source["source_id"] in identities:
            raise ValueError("Invalid source identity, hash or split")
        if source["family_id"] in families and families[source["family_id"]] != source["split"]:
            raise ValueError("Related source families cannot cross splits")
        identities[source["source_id"]] = source
        families[source["family_id"]] = source["split"]
    # Identical frozen documents are at least duplicates, even when a bad
    # manifest labels them as unrelated. Translations still need human grouping.
    text_splits = {}
    for source in identities.values():
        if source["text_sha256"] in text_splits and text_splits[source["text_sha256"]] != source["split"]:
            raise ValueError("Identical source texts cannot cross splits")
        text_splits[source["text_sha256"]] = source["split"]
    if corpus is not None:
        sources = _corpus(corpus)
        if manifest["corpus_id"] != corpus["corpus_id"] or manifest["corpus_sha256"] != _hash(corpus) or set(identities) != set(sources):
            raise ValueError("Study manifest differs from the full frozen corpus")
        for sid, source in sources.items():
            if any(identities[sid][key] != source[key] for key in ("text_sha256", "family_id")):
                raise ValueError("Frozen source hash/family mismatch")
    gold = spec["gold"]
    _fields(gold, {"version_id", "sha256", "provenance", "unavailable_reasons"})
    if not _text(gold["version_id"]) or not _text(gold["provenance"]) or not isinstance(gold["unavailable_reasons"], dict) or set(gold["unavailable_reasons"]) - {"sha256"}:
        raise ValueError("Invalid gold version/provenance")
    if gold["sha256"] is None:
        if not _text(gold["unavailable_reasons"].get("sha256")):
            raise ValueError("Gold unavailable before predictions lock needs a reason")
    elif not _sha(gold["sha256"]) or gold["unavailable_reasons"]:
        raise ValueError("Invalid gold hash")
    arms = spec["arms"]
    if not isinstance(arms, list) or not 2 <= len(arms) <= 20:
        raise ValueError("A study needs 2–20 arms")
    arm_ids = set()
    for arm in arms:
        _fields(arm, {"arm_id", "system", "track", "configuration", "provenance"})
        if not _text(arm["arm_id"]) or arm["arm_id"] in arm_ids or not _text(arm["system"]) or not isinstance(arm["track"], str) or arm["track"] not in {"matched", "native", "ablation", "warm_extension"} or not isinstance(arm["configuration"], dict):
            raise ValueError("Invalid experimental arm")
        arm_ids.add(arm["arm_id"])
        _provenance(arm["provenance"])
    if not _text(contrast["left"]) or not _text(contrast["right"]) or contrast["left"] not in arm_ids or contrast["right"] not in arm_ids or contrast["left"] == contrast["right"]:
        raise ValueError("Primary contrast must name distinct registered arms")
    repetitions = spec["repetitions"]
    if type(repetitions) is not int or not 1 <= repetitions <= 100 or not _strings(spec["seeds"]) or len(spec["seeds"]) != repetitions or len(set(spec["seeds"])) != repetitions:
        raise ValueError("Each repetition needs a distinct predeclared seed")
    if repetitions * len(arms) > 20:
        raise ValueError("Shared offline scoring supports at most 20 arm/repetition runs; predeclare separate study blocks")
    order = spec["run_order"]
    if not isinstance(order, list) or len(order) != len(arms) * repetitions:
        raise ValueError("Run order must cover every arm/repetition exactly once")
    seen, run_ids = set(), set()
    for row in order:
        _fields(row, {"run_id", "arm_id", "repetition", "seed"})
        rep = row["repetition"]
        if not _text(row["run_id"]) or row["run_id"] in run_ids or not _text(row["arm_id"]) or row["arm_id"] not in arm_ids or type(rep) is not int or not 0 <= rep < repetitions or row["seed"] != spec["seeds"][rep] or (row["arm_id"], rep) in seen:
            raise ValueError("Invalid duplicate/missing run-order cell or seed")
        seen.add((row["arm_id"], rep)); run_ids.add(row["run_id"])
    cache = spec["cache"]
    _fields(cache, {"regime", "isolation", "extension_of", "unavailable_reason"})
    if not isinstance(cache["regime"], str) or cache["regime"] not in {"cold", "warm_extension"} or not _text(cache["isolation"]):
        raise ValueError("Declare cold or separately labeled warm cache and isolation")
    if cache["regime"] == "warm_extension":
        if not _sha(cache["extension_of"]) or cache["unavailable_reason"] is not None or any(a["track"] != "warm_extension" for a in arms):
            raise ValueError("Warm extensions must identify their prior cold prediction lock")
    elif cache["extension_of"] is not None or not _text(cache["unavailable_reason"]):
        raise ValueError("Cold cache extension reference must be null with a reason")
    _fields(spec["limits"], LIMITS)
    if any(not _finite(v, integer=k in {"calls", "input_tokens", "output_tokens"}) for k, v in spec["limits"].items()):
        raise ValueError("All call/token/time/spending/allocation limits must be finite nonnegative caps")
    if not _strings(spec["stopping_rules"], nonempty=True):
        raise ValueError("Declare finite stopping rules")
    if not isinstance(spec["planned_exclusions"], list) or len(spec["planned_exclusions"]) > 1000:
        raise ValueError("Planned exclusions must be a bounded list")
    for exclusion in spec["planned_exclusions"]:
        _fields(exclusion, {"rule", "reason"})
        if any(not _text(v) for v in exclusion.values()):
            raise ValueError("Exclusions need a predeclared rule and reason")
    if not isinstance(spec["unavailable_reasons"], dict) or any(not _text(k) or not _text(v) for k, v in spec["unavailable_reasons"].items()):
        raise ValueError("Unavailable values need explicit reasons")
    if len(canonical_json(spec).encode()) > 8000000:
        raise ValueError("Study specification exceeds its finite size limit")
    return copy.deepcopy(spec)


def _write_once(path, value):
    """Exclusive creation prevents replacing an earlier version accidentally."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical_json(value) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


class StudyRepository:
    """Append-only JSON revisions; hashes detect modifications, not malicious re-signing.

    Keep this local repository under access control or commit frozen artifacts
    for stronger independent custody. It is intentionally not a job runner.
    """
    def __init__(self, root):
        self.root = Path(root).resolve()

    def history(self):
        rows, previous = [], None
        for index, path in enumerate(sorted((self.root / "revisions").glob("*.json")), 1):
            row = _decode(_read_input(path))
            _fields(row, {"revision", "state", "actor", "created_at", "reason", "previous_sha256", "spec", "sha256"})
            payload = {k: v for k, v in row.items() if k != "sha256"}
            if path.name != f"{index:06d}.json" or row["revision"] != index or row["previous_sha256"] != previous or _hash(payload) != row["sha256"]:
                raise ValueError("Study history hash/sequence mismatch")
            validate_study(row["spec"])
            if not isinstance(row["state"], str) or row["state"] not in {"draft", "frozen", "amended"} or not _text(row["actor"]) or not _text(row["reason"]):
                raise ValueError("Invalid study history state")
            rows.append(row); previous = row["sha256"]
        return rows

    def current(self):
        history = self.history()
        if not history:
            raise ValueError("Study has no revisions")
        return history[-1]

    def _append(self, spec, state, actor, reason):
        spec = validate_study(spec)
        if not _text(actor) or not _text(reason):
            raise ValueError("Study changes need an actor and reason")
        history = self.history()
        row = {"revision": len(history) + 1, "state": state, "actor": actor, "created_at": _now(), "reason": reason,
               "previous_sha256": history[-1]["sha256"] if history else None, "spec": spec}
        row["sha256"] = _hash(row)
        return _write_once(self.root / "revisions" / f"{row['revision']:06d}.json", row)

    def create(self, spec, *, actor):
        if self.history():
            raise ValueError("Study already exists; use a documented amendment")
        return self._append(spec, "draft", actor, "initial_draft")

    def freeze(self, *, actor, corpus):
        current = self.current()
        if current["state"] == "frozen":
            raise ValueError("Study is already frozen")
        validate_study(current["spec"], corpus)
        return self._append(current["spec"], "frozen", actor, "freeze_before_execution_and_scoring")

    def amend(self, spec, *, reason, actor):
        current = self.current()
        if spec.get("study_id") != current["spec"]["study_id"]:
            raise ValueError("An amendment must retain its study identity")
        return self._append(spec, "amended", actor, reason)

    def _validate_runs(self, corpus, runs):
        current = self.current()
        if current["state"] != "frozen":
            raise ValueError("Freeze the current study revision first")
        spec = validate_study(current["spec"], corpus)
        sources = _corpus(corpus)
        if not isinstance(runs, list) or len(runs) != len(spec["run_order"]):
            raise ValueError("Predictions must include every planned arm/repetition")
        arms = {a["arm_id"]: a for a in spec["arms"]}
        run_ids = set()
        for run, planned in zip(runs, spec["run_order"]):
            _fields(run, {"schema_version", "run_id", "system", "data_type", "proposal_population", "provenance", "source_results", "predictions", "costs"})
            if not isinstance(run, dict) or run.get("run_id") != planned["run_id"] or run.get("run_id") in run_ids:
                raise ValueError("Saved runs must follow the predeclared run order")
            if run["schema_version"] != "1" or not isinstance(run["proposal_population"], str) or run["proposal_population"] not in {"raw_proposals", "grounded_inventory"}:
                raise ValueError("Invalid normalized saved run schema/population")
            run_ids.add(run["run_id"])
            arm = arms[planned["arm_id"]]
            if run.get("system") != arm["system"] or run.get("provenance") != arm["provenance"] or run.get("data_type") != corpus["data_type"]:
                raise ValueError("Run system/provenance differs from its frozen arm")
            rows = run.get("source_results")
            if not isinstance(rows, list) or len(rows) != len(sources):
                raise ValueError("Every frozen source needs an explicit outcome")
            seen = set()
            for row in rows:
                _fields(row, {"source_id", "text_sha256", "status", "reason"})
                if not isinstance(row, dict) or not isinstance(row.get("source_id"), str) or row["source_id"] not in sources or row["source_id"] in seen or row.get("text_sha256") != sources[row["source_id"]]["text_sha256"] or not isinstance(row.get("status"), str) or row["status"] not in STATUSES:
                    raise ValueError("Invalid run full-source outcome inventory")
                if row["status"] != "complete" and not _text(row.get("reason")):
                    raise ValueError("Incomplete source outcomes need reasons")
                seen.add(row["source_id"])
            if not isinstance(run.get("predictions"), list) or len(run["predictions"]) > 100000:
                raise ValueError("Predictions must be a bounded list")
            prediction_ids = set()
            for prediction in run["predictions"]:
                _fields(prediction, {"prediction_id", "source_id", "observed_text", "language", "start", "end", "interpretation"})
                if not _text(prediction["prediction_id"]) or prediction["prediction_id"] in prediction_ids or not isinstance(prediction["source_id"], str) or prediction["source_id"] not in sources:
                    raise ValueError("Predictions need unique identities and frozen sources")
                prediction_ids.add(prediction["prediction_id"])
            _costs(run["costs"])
        return current

    def lock_predictions(self, corpus, runs, *, actor):
        current = self._validate_runs(corpus, runs)
        if not _text(actor):
            raise ValueError("Prediction lock needs an actor")
        lock = {"schema_version": VERSION, "study_revision_sha256": current["sha256"], "corpus_sha256": _hash(corpus),
                "run_sha256": {r["run_id"]: _hash(r) for r in runs}, "run_order": [r["run_id"] for r in runs],
                "actor": actor, "created_at": _now(), "gold_access": "not_read_by_locking_api"}
        lock["sha256"] = _hash(lock)
        return _write_once(self.root / "locks" / f"{current['sha256']}.json", lock)

    def score(self, corpus, runs, gold_path, *, workspace_root, bootstrap_samples=0, seed="quarry-v7", gold_manifest_path=None):
        """Read external gold only after verifying an existing frozen prediction lock.

        workspace_root must name the complete planning/extraction workspace;
        path separation is enforced, but human prior access remains an attestation.
        Only heldout families enter confirmatory detection; development data
        remain in the corpus/lock and can be analyzed separately as exploratory.
        """
        current = self._validate_runs(corpus, runs)
        lock = _decode(_read_input(self.root / "locks" / f"{current['sha256']}.json"))
        payload = {k: v for k, v in lock.items() if k != "sha256"}
        if _hash(payload) != lock.get("sha256") or lock.get("study_revision_sha256") != current["sha256"] or lock.get("corpus_sha256") != _hash(corpus) or lock.get("run_sha256") != {r["run_id"]: _hash(r) for r in runs} or lock.get("run_order") != [r["run_id"] for r in runs]:
            raise ValueError("Predictions/corpus changed after the immutable lock")
        workspace, gold_path = Path(workspace_root).resolve(), Path(gold_path).resolve()
        if not self.root.is_relative_to(workspace):
            raise ValueError("Study repository must be inside the declared planning workspace")
        if gold_path.is_relative_to(workspace):
            raise ValueError("Independent gold must be held outside the planning/extraction workspace")
        raw = _read_input(gold_path)
        gold = [_decode(line) for line in raw.splitlines() if line.strip()] if gold_path.suffix.lower() == ".jsonl" else _decode(raw)
        expected = current["spec"]["gold"]["sha256"]
        if expected is not None and expected != _hash(gold):
            raise ValueError("External gold differs from the predeclared gold version hash")
        manifest = None
        manifest_raw = None
        manifest_path = Path(gold_manifest_path).resolve() if gold_manifest_path is not None else gold_path.with_name("manifest.json")
        if gold_manifest_path is not None or manifest_path.exists():
            manifest_path = manifest_path.resolve()
            if manifest_path.is_relative_to(workspace):
                raise ValueError("External gold manifest must remain outside the planning/extraction workspace")
            manifest_raw = _read_input(manifest_path)
            manifest = _decode(manifest_raw)
            if not isinstance(manifest, dict) or manifest.get("version_id") != current["spec"]["gold"]["version_id"] or manifest.get("gold_sha256") != _hash(gold) or not _text(manifest.get("provenance")):
                raise ValueError("External gold manifest version/hash/provenance mismatch")
        heldout = {s["source_id"] for s in current["spec"]["corpus"]["sources"] if s["split"] == "heldout"}
        if not heldout:
            raise ValueError("Confirmatory scoring needs held-out source families")
        if not isinstance(gold, list) or {p.get("source_id") for p in gold if isinstance(p, dict)} != heldout or len(gold) != len(heldout):
            raise ValueError("External gold must cover every heldout source exactly once")
        scored_corpus = {**corpus, "sources": [s for s in corpus["sources"] if s["source_id"] in heldout]}
        scored_runs = [{**run, "source_results": [r for r in run["source_results"] if r["source_id"] in heldout],
                        "predictions": [p for p in run["predictions"] if p.get("source_id") in heldout]} for run in runs]
        # No interpretation string equality is presented as semantic equivalence.
        outcome_unit = current["spec"]["primary_outcome"]["unit"]
        unit = outcome_unit if outcome_unit in {"occurrence", "source_term"} else "occurrence"
        if len(scored_runs) > 20:
            raise ValueError("Shared comparison supports at most 20 saved runs; score predeclared repetition blocks separately")
        report = compare_experiments(scored_corpus, gold, scored_runs, unit=unit, require_sense=False,
                                     bootstrap_samples=bootstrap_samples, seed=seed)
        contrast = current["spec"]["primary_contrast"]
        outcome = current["spec"]["primary_outcome"]
        normalized_reports = {r["run_id"]: r for r in report["runs"]}
        primary = []
        for repetition in range(current["spec"]["repetitions"]):
            planned = {r["arm_id"]: r["run_id"] for r in current["spec"]["run_order"] if r["repetition"] == repetition}
            left_id, right_id = planned[contrast["left"]], planned[contrast["right"]]
            supported = outcome["unit"] in {"occurrence", "source_term"} and outcome["metric"] in {"precision", "recall", "f1"}
            values = [normalized_reports[r]["detection"]["overall"].get(outcome["metric"]) if supported else None for r in (left_id, right_id)]
            delta = values[1] - values[0] if all(v is not None for v in values) else None
            direction = 1 if contrast["direction"] == "right_minus_left" else -1
            pair = next(p for p in report["pairs"] if {p["left"], p["right"]} == {left_id, right_id})
            interval = pair["uncertainty"]["intervals_95"].get(outcome["metric"]) if supported else None
            orientation = direction * (1 if pair["left"] == left_id else -1)
            interval = interval if interval is None or orientation == 1 else [-interval[1], -interval[0]]
            primary.append({"repetition": repetition, "seed": current["spec"]["seeds"][repetition],
                            "left_run_id": left_id, "right_run_id": right_id, "metric": outcome["metric"], "unit": outcome["unit"],
                            "left_value": values[0], "right_value": values[1], "direction": contrast["direction"],
                            "delta": delta * direction if delta is not None else None,
                            "delta_reason": None if delta is not None else "undefined_detection_metric" if supported else "separate_predeclared_primary_analysis_required",
                            "interval_95": interval, "interval_reason": None if interval is not None else pair["uncertainty"]["null_reason"] if supported else "separate_predeclared_primary_analysis_required"})
        report["primary_contrast_results"] = primary
        report["study"] = {"revision_sha256": current["sha256"], "prediction_lock_sha256": lock["sha256"],
                           "declared_gold_version": current["spec"]["gold"]["version_id"],
                           "gold_version": manifest["version_id"] if manifest is not None else None,
                           "gold_version_reason": None if manifest is not None else "declared_version_unattested_without_export_manifest",
                           "gold_version_status": "manifest_content_matched_custody_unattested" if manifest is not None else "declared_unattested",
                           "gold_manifest_file_sha256": hashlib.sha256(manifest_raw).hexdigest() if manifest_raw is not None else None,
                           "gold_provenance": manifest["provenance"] if manifest is not None else None,
                           "gold_provenance_reason": None if manifest is not None else "export_manifest_unavailable",
                           "gold_file_sha256": hashlib.sha256(raw).hexdigest(),
                           "primary_contrast": current["spec"]["primary_contrast"], "primary_outcome": current["spec"]["primary_outcome"],
                           "scope": current["spec"]["corpus"]["scope"], "full_locked_corpus_sha256": _hash(corpus),
                           "analysis": "heldout_detection; semantic/time outcomes require their separately predeclared analysis",
                           "custody_limit": "Path separation and lock checks do not prove humans lacked prior gold access."}
        return report
