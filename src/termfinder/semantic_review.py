"""Full-source, system-blinded review packets and immutable human event history.

These APIs collect declarations and audit artifacts; they do not recruit people,
call models, infer semantic equivalence, or claim that blinding is perfect.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import math
import os
from pathlib import Path
import time
import uuid

from .experiments import _corpus, _decode, _hash, _read_input
from .studies import _fields, _now, _text, _write_once

AXES = frozenset({"eligibility", "contextual_meaning", "definition_support", "translation"})
DECISIONS = frozenset({"accept", "reject", "uncertain", "disputed", "unscorable"})
MODES = frozenset({"candidate_review", "assisted_complete_source", "independent_gold"})
WORK_KINDS = frozenset({"judgment", "adjudication", "reversal", "item_add", "item_remove", "item_correct", "source_complete"})
DETAIL_FIELDS = frozenset({"context", "context_start", "context_end", "contexts", "definition_quote", "definition_quote_reason", "translation", "source_locations"})


def _review_details(value):
    """Whitelist source/suggestion attachments, excluding arm/model provenance."""
    _fields(value, set(), DETAIL_FIELDS)
    from .exports import canonical_json
    if len(canonical_json(value).encode("utf-8")) > 1000000:
        raise ValueError("Original evidence details exceed their finite size limit")
    for key in ("context", "definition_quote", "definition_quote_reason"):
        if key in value and value[key] is not None and (not isinstance(value[key], str) or len(value[key]) > 100000):
            raise ValueError("Original context/definition details must be bounded strings or null")
    for key in ("context_start", "context_end"):
        if key in value and value[key] is not None and (type(value[key]) is not int or value[key] < 0):
            raise ValueError("Invalid original context location")
    if "contexts" in value:
        if not isinstance(value["contexts"], list) or len(value["contexts"]) > 1000:
            raise ValueError("Original contexts must be a bounded list")
        for context in value["contexts"]:
            _fields(context, {"text", "start", "end"})
            if not isinstance(context["text"], str) or any(type(context[k]) is not int for k in ("start", "end")):
                raise ValueError("Malformed original context attachment")
    locations = value.get("source_locations", [])
    if not isinstance(locations, list) or len(locations) > 1000:
        raise ValueError("Original source locations must be a bounded list")
    for location in locations:
        _fields(location, set(), {"kind", "start", "end", "page", "heading", "location"})
        if "location" in location:
            _fields(location["location"], set(), {"line", "column", "page", "html_tag", "element_id", "speaker", "xpath"})
    result = copy.deepcopy(value)
    translation = result.get("translation")
    if isinstance(translation, dict):
        _fields(translation, {"text", "origin", "reason"})
        if translation["text"] is not None and (not isinstance(translation["text"], str) or len(translation["text"]) > 100000):
            raise ValueError("Original translation text must be bounded or null")
        if translation["reason"] is not None and not isinstance(translation["reason"], str):
            raise ValueError("Original translation reason must be text or null")
        translation["origin"] = "model_generated" if translation["text"] is not None else None
    elif translation is not None and not isinstance(translation, str):
        raise ValueError("Original translation must be text, null or the Quarry translation object")
    result["origin_labels"] = {"context": "original_source_context_attachment",
                               "definition_quote": "original_quote_semantic_support_unverified",
                               "translation": "model_suggestion_not_human_verified",
                               "source_locations": "original_parser_reported_location"}
    result["human_verified"] = False
    return result


def quarry_review_details(dataset, run_id):
    """Attach original Quarry occurrence evidence to a normalized saved run.

    Returns the run_id -> prediction_id mapping accepted by create_packet.
    The ordering and fallback IDs match experiments.quarry_run exactly.
    Human annotations/provenance and model/system names are not copied.
    """
    from .exports import dataset_record_view, evidence_view
    if not _text(run_id):
        raise ValueError("Review evidence bridge needs a run identity")
    records = {r["record_id"]: r for r in dataset_record_view(dataset)}
    details = {}
    for index, occurrence in enumerate(evidence_view(dataset)):
        prediction_id = occurrence.get("occurrence_id") or f"observation-{index}"
        if prediction_id in details:
            raise ValueError("Duplicate original occurrence identity")
        record = records.get(occurrence["record_id"], {})
        support = record.get("source_support_quote")
        quote = occurrence.get("definition_quote")
        if "definition_quote" not in occurrence and isinstance(support, dict) and support.get("occurrence_id") in (None, prediction_id):
            quote = support.get("text")
        elif "definition_quote" not in occurrence and isinstance(support, str):
            quote = support
        attachment = {k: copy.deepcopy(occurrence[k]) for k in DETAIL_FIELDS if k in occurrence}
        attachment["definition_quote"] = quote
        attachment.setdefault("definition_quote_reason", None if quote else "no_original_definition_quote")
        details[prediction_id] = {k: v for k, v in _review_details(attachment).items() if k in DETAIL_FIELDS}
    return {run_id: details}


def _axes(value):
    _fields(value, AXES)
    for axis, judgment in value.items():
        _fields(judgment, {"decision", "label", "reason"})
        if not isinstance(judgment["decision"], str) or judgment["decision"] not in DECISIONS:
            raise ValueError("Unknown semantic decision")
        if judgment["label"] is not None and not _text(judgment["label"]):
            raise ValueError("Semantic labels must be nonempty strings or null")
        if not _text(judgment["reason"]):
            raise ValueError("Every semantic axis needs a reason, including unavailable/not-applicable judgments")
        if axis == "contextual_meaning" and judgment["decision"] == "accept" and not _text(judgment["label"]):
            raise ValueError("An accepted contextual meaning needs a human label")
    return copy.deepcopy(value)


def _timestamp(at):
    at = time.time() if at is None else at
    if type(at) not in (int, float) or not math.isfinite(at) or not 0 <= at <= 1e12:
        raise ValueError("Review timestamps must be finite nonnegative seconds")
    return at


@contextmanager
def _locked(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / ".ledger.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class ExposureRegistry:
    """Shared actor/family exposure registry across all study conditions.

    Use one coordinator-owned registry for every condition. Actor identities and
    prior-exposure declarations require a human protocol; multiple registries or
    aliases would defeat that protocol and cannot be detected from these files.
    """
    def __init__(self, root):
        self.root = Path(root).resolve()

    def claim(self, *, actor, family_ids, packet_sha256, session_id, prior_exposure=False):
        if not _text(actor) or not isinstance(family_ids, list) or not family_ids or any(not _text(f) for f in family_ids) or type(prior_exposure) is not bool:
            raise ValueError("Exposure claims require an actor and frozen source families")
        if prior_exposure:
            raise ValueError("Previously exposed reviewers cannot enter a fresh timing condition")
        families = set(family_ids)
        with _locked(self.root):
            for path in self.root.glob("exposure-*.json"):
                prior = _decode(_read_input(path))
                if prior["actor"] == actor and families & set(prior["family_ids"]):
                    raise ValueError("Reviewer has already seen a related source family; use a new family/task")
            return _write_once(self.root / f"exposure-{session_id}.json", {
                "actor": actor, "family_ids": sorted(families), "packet_sha256": packet_sha256,
                "session_id": session_id, "prior_exposure": False, "created_at": _now()})


class ReviewWorkspace:
    """Append-only review ledger with separate coordinator and reviewer packets.

    packet() is the reviewer view. coordinator.json contains the hidden origin
    mapping and must be kept away from blinded reviewers by the study coordinator.
    File separation is not an authentication or access-control system.
    """
    def __init__(self, root):
        self.root = Path(root).resolve()

    def create_packet(self, corpus, runs=None, *, mode="candidate_review", rubric, workspace_root=None, evidence_details=None):
        sources = _corpus(corpus)
        if not isinstance(mode, str) or mode not in MODES or not isinstance(rubric, dict) or set(rubric) != AXES or any(not _text(v) for v in rubric.values()):
            raise ValueError("Review mode and four-axis rubric must be declared")
        if mode == "independent_gold":
            if runs is not None or evidence_details is not None:
                raise ValueError("Independent complete-source gold cannot start from a candidate list")
            if workspace_root is None or self.root.is_relative_to(Path(workspace_root).resolve()):
                raise ValueError("Independent gold workspace must be outside planning/extraction workspace")
        elif not isinstance(runs, list) or not 1 <= len(runs) <= 20:
            raise ValueError("Candidate/assisted review requires bounded saved runs")
        if any(not isinstance(r, dict) or not _text(r.get("run_id")) for r in runs or []):
            raise ValueError("Saved review runs need explicit identities")
        if len({r["run_id"] for r in runs or []}) != len(runs or []):
            raise ValueError("Saved review run identities must be unique")
        if evidence_details is None:
            evidence_details = {}
        if not isinstance(evidence_details, dict) or set(evidence_details) - {r["run_id"] for r in runs or []}:
            raise ValueError("Original evidence detail mapping must name supplied runs")
        used_details = set()
        candidates, hidden, merged = [], [], {}
        for run in runs or []:
            if not isinstance(run, dict) or not _text(run.get("run_id")) or not isinstance(run.get("predictions"), list) or len(run["predictions"]) > 100000:
                raise ValueError("Malformed saved run review input")
            prediction_ids = set()
            for proposal in run["predictions"]:
                _fields(proposal, {"prediction_id", "source_id", "observed_text", "language", "start", "end", "interpretation"})
                sid = proposal["source_id"]
                if not isinstance(sid, str) or sid not in sources or not _text(proposal["prediction_id"]) or proposal["prediction_id"] in prediction_ids:
                    raise ValueError("Unknown source or missing original prediction identity")
                prediction_ids.add(proposal["prediction_id"])
                # Preserve malformed proposals without repairing their wording or
                # occurrence. The public view exposes exact grounding diagnostics.
                evidence = {k: copy.deepcopy(proposal[k]) for k in ("source_id", "observed_text", "language", "start", "end")}
                marker = _hash(evidence)
                if marker not in merged:
                    cid = "candidate-" + uuid.uuid4().hex
                    start, end = proposal["start"], proposal["end"]
                    exact = type(start) is int and type(end) is int and 0 <= start < end <= len(sources[sid]["text"]) and sources[sid]["text"][start:end] == proposal["observed_text"]
                    row = {"candidate_id": cid, "evidence": evidence, "grounding": "exact" if exact else "invalid_original_proposal",
                           "model_suggestions": []}
                    merged[marker] = row; candidates.append(row)
                row = merged[marker]
                suggestion_id = "suggestion-" + uuid.uuid4().hex
                suggestion = {"suggestion_id": suggestion_id, "origin": "model", "interpretation": copy.deepcopy(proposal["interpretation"])}
                run_details = evidence_details.get(run["run_id"], {})
                if not isinstance(run_details, dict):
                    raise ValueError("Each evidence detail mapping needs prediction IDs")
                if proposal["prediction_id"] in run_details:
                    suggestion["original_evidence"] = _review_details(run_details[proposal["prediction_id"]])
                    used_details.add((run["run_id"], proposal["prediction_id"]))
                else:
                    suggestion["original_evidence"] = None
                    suggestion["original_evidence_reason"] = "not_supplied_in_normalized_run"
                row["model_suggestions"].append(suggestion)
                hidden.append({"candidate_id": row["candidate_id"], "suggestion_id": suggestion_id,
                               "run_id": run["run_id"], "prediction_id": proposal["prediction_id"]})
                if len(hidden) > 100000:
                    raise ValueError("Review packet exceeds the finite aggregate proposal limit")
        if any(not isinstance(values, dict) or any((rid, pid) not in used_details for pid in values) for rid, values in evidence_details.items()):
            raise ValueError("Original evidence details reference unknown prediction IDs")
        # Random order and opaque IDs avoid exposing systems through arm order,
        # deterministic pseudonym hashes or candidate multiplicity by arm label.
        import random
        random.SystemRandom().shuffle(candidates)
        packet = {"schema_version": "7.0", "packet_id": "packet-" + uuid.uuid4().hex, "mode": mode,
                  "corpus_id": corpus["corpus_id"], "corpus_sha256": _hash(corpus), "data_type": corpus["data_type"],
                  "rubric": copy.deepcopy(rubric),
                  "sources": [{k: copy.deepcopy(s[k]) for k in ("source_id", "text", "text_sha256", "domain", "language", "family_id")} |
                              {"locator": copy.deepcopy(s.get("locator"))} for s in sources.values()],
                  "candidates": candidates,
                  "blinding": "System IDs/provenance hidden; source content and suggestion style may still reveal origins.",
                  "recall_limit": "Candidate review cannot measure omissions; independent complete-source gold supplies recall."}
        packet["sha256"] = _hash(packet)
        from .exports import canonical_json
        if len(canonical_json(packet).encode("utf-8")) > 32000000:
            raise ValueError("Review packet exceeds its finite 32 MB size limit")
        with _locked(self.root):
            if (self.root / "packet.json").exists():
                raise ValueError("Review packet already exists and cannot be replaced")
            _write_once(self.root / "coordinator.json", {"packet_sha256": packet["sha256"], "origins": hidden,
                                                         "run_sha256": {r["run_id"]: _hash(r) for r in runs or []}})
            return _write_once(self.root / "packet.json", packet)

    def packet(self):
        packet = _decode(_read_input(self.root / "packet.json"))
        if _hash({k: v for k, v in packet.items() if k != "sha256"}) != packet.get("sha256"):
            raise ValueError("Review packet was modified")
        return packet

    def history(self):
        packet = self.packet()
        rows, previous = [], None
        for index, path in enumerate(sorted((self.root / "events").glob("*.json")), 1):
            row = _decode(_read_input(path))
            if path.name != f"{index:06d}.json" or row.get("sequence") != index or row.get("previous_sha256") != previous or row.get("packet_sha256") != packet["sha256"] or _hash({k: v for k, v in row.items() if k != "sha256"}) != row.get("sha256"):
                raise ValueError("Review event history hash/sequence mismatch")
            rows.append(row); previous = row["sha256"]
        return rows

    def _append(self, kind, *, actor, payload):
        if not _text(actor):
            raise ValueError("Human event needs an actor")
        with _locked(self.root):
            rows = self.history()
            if len(rows) >= 100000:
                raise ValueError("Finite review event limit reached")
            row = {"event_id": "event-" + uuid.uuid4().hex, "sequence": len(rows) + 1, "kind": kind,
                   "actor": actor, "origin": "human", "created_at": _now(), "payload": copy.deepcopy(payload),
                   "packet_sha256": self.packet()["sha256"], "previous_sha256": rows[-1]["sha256"] if rows else None}
            if kind in WORK_KINDS:
                active = [s for s in self.sessions().values() if s["actor"] == actor and s["state"] == "active"]
                row["timing"] = {"session_id": active[0]["session_id"] if active else None,
                                 "unavailable_reason": None if active else "no_active_session_for_actor"}
            row["sha256"] = _hash(row)
            return _write_once(self.root / "events" / f"{row['sequence']:06d}.json", row)

    def _active_events(self):
        rows = self.history()
        reversed_ids = {r["payload"]["event_id"] for r in rows if r["kind"] == "reversal"}
        return [r for r in rows if r["event_id"] not in reversed_ids and r["kind"] != "reversal"]

    def items(self):
        """Current evidence view; originals and every correction remain in history."""
        items = {r["candidate_id"]: {"item_id": r["candidate_id"], **copy.deepcopy(r["evidence"])} for r in self.packet()["candidates"]}
        for row in self._active_events():
            payload = row["payload"]
            if row["kind"] in {"item_add", "item_correct"}:
                items[payload["item"]["item_id"]] = copy.deepcopy(payload["item"])
            elif row["kind"] == "item_remove":
                items.pop(payload["item_id"], None)
        return items

    def _item(self, item_id):
        if not isinstance(item_id, str) or item_id not in self.items():
            raise ValueError("Unknown or removed review item")
        return self.items()[item_id]

    def judge(self, item_id, axes, *, actor, note="", supersedes=None):
        item = self._item(item_id)
        axes = _axes(axes)
        if not isinstance(note, str) or len(note) > 20000:
            raise ValueError("Invalid human review note")
        prior = [r for r in self._active_events() if r["kind"] == "judgment" and r["actor"] == actor and r["payload"]["item_id"] == item_id and r["payload"]["evidence_sha256"] == _hash(item)]
        if prior and supersedes != prior[-1]["event_id"] or not prior and supersedes is not None:
            raise ValueError("A revised judgment must explicitly supersede that human's latest judgment")
        return self._append("judgment", actor=actor, payload={"item_id": item_id, "evidence_sha256": _hash(item),
                            "axes": axes, "note": note, "supersedes": supersedes})

    def adjudicate(self, item_id, axes, *, judgment_ids, actor, reason):
        item = self._item(item_id)
        axes = _axes(axes)
        if not _text(reason) or not isinstance(judgment_ids, list) or len(judgment_ids) < 2 or len(judgment_ids) != len(set(judgment_ids)):
            raise ValueError("Adjudication needs multiple independent judgments and a reason")
        active = {r["event_id"]: r for r in self._active_events()}
        judgments = []
        for jid in judgment_ids:
            row = active.get(jid)
            if not row or row["kind"] != "judgment" or row["payload"]["item_id"] != item_id or row["payload"]["evidence_sha256"] != _hash(item):
                raise ValueError("Adjudication references missing/reversed or stale-evidence judgments")
            later = [r for r in active.values() if r["kind"] == "judgment" and r["payload"].get("supersedes") == jid]
            if later:
                raise ValueError("Adjudication must use each reviewer's latest judgment")
            judgments.append(row)
        if len({r["actor"] for r in judgments}) < 2 or actor in {r["actor"] for r in judgments}:
            raise ValueError("Adjudication requires two distinct reviewers and a separate adjudicator")
        return self._append("adjudication", actor=actor, payload={"item_id": item_id, "evidence_sha256": _hash(item),
                            "axes": axes, "judgment_ids": judgment_ids, "reason": reason})

    def reverse(self, event_id, *, actor, reason):
        if not _text(reason):
            raise ValueError("A reversal needs a reason")
        row = next((r for r in self._active_events() if r["event_id"] == event_id), None)
        if row is None or row["kind"] not in {"judgment", "adjudication", "item_add", "item_remove", "item_correct", "source_complete"}:
            raise ValueError("Unknown, already reversed or nonreversible event")
        return self._append("reversal", actor=actor, payload={"event_id": event_id, "reason": reason})

    def record_item(self, action, item=None, *, item_id=None, actor, reason):
        """Add omissions, correct spans, or remove a view item without deleting evidence."""
        if not isinstance(action, str) or action not in {"add", "correct", "remove"} or not _text(reason):
            raise ValueError("Item edits need an explicit action and reason")
        if action == "remove":
            self._item(item_id)
            return self._append("item_remove", actor=actor, payload={"item_id": item_id, "reason": reason})
        _fields(item, {"source_id", "observed_text", "language", "start", "end"})
        sources = {s["source_id"]: s for s in self.packet()["sources"]}
        sid, start, end = item["source_id"], item["start"], item["end"]
        if not isinstance(sid, str) or sid not in sources or not _text(item["observed_text"]) or not _text(item["language"]) or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(sources[sid]["text"]) or sources[sid]["text"][start:end] != item["observed_text"]:
            raise ValueError("Human additions/corrections must be exact frozen-source spans")
        if action == "correct":
            self._item(item_id)
        else:
            if item_id is not None:
                raise ValueError("New items receive opaque identities")
            item_id = "human-item-" + uuid.uuid4().hex
        return self._append("item_" + action, actor=actor, payload={"item": {"item_id": item_id, **copy.deepcopy(item)}, "reason": reason})

    def mark_complete(self, source_id, *, actor, qualified, independent, note):
        if source_id not in {s["source_id"] for s in self.packet()["sources"]} or qualified is not True or independent is not True or not _text(note):
            raise ValueError("Complete-source signoff needs qualified independent human attestation and a note")
        return self._append("source_complete", actor=actor, payload={"source_id": source_id, "qualified": True, "independent": True, "note": note,
                            "inventory_sha256": _hash([i for i in self.items().values() if i["source_id"] == source_id])})

    def start_session(self, *, actor, exposure_registry, prior_exposure=False, at=None):
        packet, at = self.packet(), _timestamp(at)
        if not _text(actor):
            raise ValueError("Review session needs a stable human actor")
        if any(e["actor"] == actor and e["kind"] in WORK_KINDS for e in self.history()):
            raise ValueError("Reviewer already worked on this packet before timing; fresh tasks must start their timer before exposure")
        if any(s["actor"] == actor and s["state"] != "finished" for s in self.sessions().values()):
            raise ValueError("Finish an existing active review session before starting another")
        sid = "session-" + uuid.uuid4().hex
        ExposureRegistry(exposure_registry).claim(actor=actor, family_ids=sorted({s["family_id"] for s in packet["sources"]}),
                                                 packet_sha256=packet["sha256"], session_id=sid, prior_exposure=prior_exposure)
        return self._append("session_start", actor=actor, payload={"session_id": sid, "at": at, "condition": packet["mode"],
                            "exposure_registry": "shared_registry_claimed", "prior_exposure": False})

    def sessions(self):
        sessions = {}
        for row in self.history():
            p = row["payload"]
            if row["kind"] == "session_start":
                sessions[p["session_id"]] = {"session_id": p["session_id"], "actor": row["actor"], "condition": p["condition"],
                                            "state": "active", "active_seconds": 0, "last_at": p["at"], "correction": None}
            elif row["kind"] in {"session_pause", "session_resume", "session_finish"}:
                s = sessions[p["session_id"]]
                if s["state"] == "active":
                    s["active_seconds"] += p["at"] - s["last_at"]
                s["state"] = {"session_pause": "paused", "session_resume": "active", "session_finish": "finished"}[row["kind"]]
                s["last_at"] = p["at"]
            elif row["kind"] == "time_correction":
                sessions[p["session_id"]]["correction"] = {"active_seconds": p["active_seconds"], "reason": p["reason"], "event_id": row["event_id"]}
        return sessions

    def _transition(self, session_id, *, actor, action, at=None, reason):
        at = _timestamp(at)
        s = self.sessions().get(session_id)
        allowed = {"pause": {"active"}, "resume": {"paused"}, "finish": {"active", "paused"}}
        if s is None or s["actor"] != actor or s["state"] not in allowed[action] or at < s["last_at"] or not _text(reason):
            raise ValueError("Invalid review timer transition, actor or backward timestamp")
        return self._append("session_" + action, actor=actor, payload={"session_id": session_id, "at": at, "reason": reason})

    def pause_session(self, session_id, *, actor, reason, at=None):
        return self._transition(session_id, actor=actor, action="pause", at=at, reason=reason)

    def resume_session(self, session_id, *, actor, reason, at=None):
        return self._transition(session_id, actor=actor, action="resume", at=at, reason=reason)

    def finish_session(self, session_id, *, actor, reason, at=None):
        return self._transition(session_id, actor=actor, action="finish", at=at, reason=reason)

    def correct_time(self, session_id, *, active_seconds, actor, reason):
        s = self.sessions().get(session_id)
        if s is None or s["state"] != "finished" or not _text(reason):
            raise ValueError("Time corrections require a finished session and reason")
        active_seconds = _timestamp(active_seconds)
        return self._append("time_correction", actor=actor, payload={"session_id": session_id, "active_seconds": active_seconds, "reason": reason})

    def summary(self):
        events = self._active_events()
        history = self.history()
        sessions = self.sessions()
        unmeasured = [e["event_id"] for e in history if e["kind"] in WORK_KINDS and e.get("timing", {}).get("session_id") is None]
        known = sum(s["correction"]["active_seconds"] if s["correction"] else s["active_seconds"] for s in sessions.values())
        if any(s["state"] != "finished" for s in sessions.values()):
            reason, total = "unfinished_review_sessions", None
        elif not sessions:
            reason, total = "active_time_not_measured", None
        elif unmeasured:
            reason, total = "unmeasured_review_actions", None
        else:
            reason = None
            total = known
        return {"packet_sha256": self.packet()["sha256"], "active_seconds": total, "active_seconds_reason": reason,
                "known_active_subtotal_seconds": known if sessions else None, "unmeasured_review_action_ids": unmeasured,
                "sessions": list(sessions.values()), "events": len(self.history()),
                "additions": sum(r["kind"] == "item_add" for r in events),
                "removals": sum(r["kind"] == "item_remove" for r in events),
                "corrections": sum(r["kind"] == "item_correct" for r in events),
                "reversals": sum(r["kind"] == "reversal" for r in self.history()),
                "semantic": self.semantic_summary(),
                "quality_note": "Human decisions and adjudication assess semantics; label equality is not semantic equivalence."}

    def semantic_summary(self):
        """Current human judgments and resolutions; no automatic disagreement resolution."""
        events, items = self._active_events(), self.items()
        judgment_counts = {axis: {decision: 0 for decision in sorted(DECISIONS)} for axis in sorted(AXES)}
        resolved_counts = copy.deepcopy(judgment_counts)
        rows = []
        for item_id, item in items.items():
            latest = {}
            for event in events:
                if event["kind"] == "judgment" and event["payload"]["item_id"] == item_id and event["payload"]["evidence_sha256"] == _hash(item):
                    latest[event["actor"]] = event
            latest_ids = {event["event_id"] for event in latest.values()}
            resolutions = [event for event in events if event["kind"] == "adjudication" and event["payload"]["item_id"] == item_id and
                           event["payload"]["evidence_sha256"] == _hash(item) and set(event["payload"]["judgment_ids"]) <= latest_ids]
            resolution = resolutions[-1] if resolutions else None
            for judgment in latest.values():
                for axis, value in judgment["payload"]["axes"].items():
                    judgment_counts[axis][value["decision"]] += 1
            if resolution:
                for axis, value in resolution["payload"]["axes"].items():
                    resolved_counts[axis][value["decision"]] += 1
            disagreement = [axis for axis in sorted(AXES) if len({j["payload"]["axes"][axis]["decision"] for j in latest.values()}) > 1]
            rows.append({"item_id": item_id, "source_id": item["source_id"], "evidence_sha256": _hash(item),
                         "current_judgments": [{"event_id": j["event_id"], "actor": j["actor"], "axes": copy.deepcopy(j["payload"]["axes"])} for j in latest.values()],
                         "adjudication_id": resolution["event_id"] if resolution else None,
                         "adjudicated_axes": copy.deepcopy(resolution["payload"]["axes"]) if resolution else None,
                         "adjudicated_axes_reason": None if resolution else "unjudged" if not latest else "awaiting_current_independent_adjudication",
                         "decision_disagreement_axes": disagreement})
        judged = sum(bool(r["current_judgments"]) for r in rows)
        resolved = sum(r["adjudication_id"] is not None for r in rows)
        return {"item_count": len(rows), "judged_items": judged, "unjudged_items": len(rows) - judged,
                "adjudicated_items": resolved, "pending_adjudication_items": judged - resolved,
                "current_human_judgment_counts_by_axis": judgment_counts, "adjudicated_item_counts_by_axis": resolved_counts,
                "items": rows, "quality_rate": None, "quality_rate_reason": "no_predeclared_semantic_rate_or_independent_semantic_gold_analysis",
                "note": "Counts describe human decisions; matching labels or matching decisions do not establish semantic equivalence. Disagreements remain unresolved until human adjudication."}

    def export_gold(self, version, *, actor, provenance):
        """Immutable gold version from independent complete-source annotation only.

        Every source needs two qualified independent signoffs on its current
        inventory. Positive items need current adjudication, referencing two
        distinct human reviewers and a third adjudicator. Unknown/disputed
        eligibility or meaning blocks export rather than becoming a negative.
        """
        packet = self.packet()
        if packet["mode"] != "independent_gold" or not _text(version) or not all(c.isalnum() or c in "-_" for c in version) or not _text(actor) or not _text(provenance):
            raise ValueError("Gold export requires independent complete-source mode, a safe version and human provenance")
        events, items = self._active_events(), self.items()
        packets = []
        for source in packet["sources"]:
            sid = source["source_id"]
            inventory = [i for i in items.values() if i["source_id"] == sid]
            signoffs = [e for e in events if e["kind"] == "source_complete" and e["payload"]["source_id"] == sid and e["payload"]["inventory_sha256"] == _hash(inventory)]
            if len({e["actor"] for e in signoffs}) < 2:
                raise ValueError("Every source, including negative sources, needs two current independent complete-source signoffs")
            terms = []
            for item in inventory:
                resolutions = [e for e in events if e["kind"] == "adjudication" and e["payload"]["item_id"] == item["item_id"] and e["payload"]["evidence_sha256"] == _hash(item)]
                if not resolutions:
                    raise ValueError("Every gold item requires independent human adjudication")
                resolution = resolutions[-1]
                refs = resolution["payload"]["judgment_ids"]
                active_ids = {e["event_id"] for e in events}
                if any(j not in active_ids for j in refs) or any(e["kind"] == "judgment" and e["payload"].get("supersedes") in refs for e in events):
                    raise ValueError("Gold adjudication references reversed/superseded judgments")
                axes = resolution["payload"]["axes"]
                if axes["eligibility"]["decision"] not in {"accept", "reject"}:
                    raise ValueError("Uncertain/disputed/unscorable eligibility cannot become gold negatives")
                if axes["eligibility"]["decision"] == "reject":
                    continue
                if axes["contextual_meaning"]["decision"] != "accept":
                    raise ValueError("Positive gold needs an adjudicated contextual meaning")
                terms.append({"observed_text": item["observed_text"], "language": item["language"], "start": item["start"], "end": item["end"],
                              "interpretation": axes["contextual_meaning"]["label"], "semantic_axes": copy.deepcopy(axes),
                              "adjudication_id": resolution["event_id"]})
            packets.append({"source_id": sid, "text_sha256": source["text_sha256"], "complete": True,
                            "data_type": packet["data_type"], "terms" if packet["data_type"] == "term" else "records": terms})
        from .evaluation import validate_gold
        validate_gold(packets, packet["sources"], data_type=packet["data_type"])
        rows = self.history()
        manifest = {"schema_version": "7.0", "version_id": version, "gold_sha256": _hash(packets), "packet_sha256": packet["sha256"],
                    "history_sha256": rows[-1]["sha256"] if rows else None, "actor": actor, "provenance": provenance,
                    "created_at": _now(), "complete_source_independent": True,
                    "custody_limit": "Qualification, independence and prior exposure are human attestations, not inferred facts."}
        with _locked(self.root):
            destination = self.root / "gold" / version
            if destination.exists():
                raise ValueError("Earlier gold versions are immutable; choose a new version")
            # Version directory creation prevents two writers from publishing the
            # same version; neither file is subsequently modified by this API.
            destination.mkdir(parents=True)
            _write_once(destination / "gold.json", packets)
            _write_once(destination / "manifest.json", manifest)
        return {"gold_path": str(destination / "gold.json"), "manifest": manifest}
