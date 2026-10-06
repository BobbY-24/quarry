"""Deterministic frozen-artifact audit; no semantic judge or publication promise."""
from __future__ import annotations

from datetime import datetime
import re

from .config import DATA_TYPES
from .store import digest, ident


def _hash(value):
    try:
        return digest(value)
    except (ValueError, TypeError, RecursionError, OverflowError):
        return None


def _sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except (ValueError, OverflowError):
        return False


def verify_history(events):
    if not isinstance(events, list):
        return False
    previous = None
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or type(event.get("sequence")) is not int
                or event["sequence"] != index or event.get("previous_sha256") != previous
                or not isinstance(event.get("payload"), dict) or not _sha(event.get("event_sha256"))
                or not _timestamp(event.get("created_at")) or not isinstance(event.get("event_type"), str)
                or not event["event_type"].strip()):
            return False
        body = {key: value for key, value in event.items() if key != "event_sha256"}
        if event["event_sha256"] != _hash(body):
            return False
        previous = event["event_sha256"]
    return True


def audit_dataset(dataset):
    """Validate only frozen JSON, with diagnostics for malformed structures.

    The sanitized copies below prevent malformed imported JSON from crashing
    the audit. Every repair is an integrity error; original input is not edited.
    No sources, archives, agents, models or external services are accessed.
    """
    structural = []
    def error(code, location, message):
        structural.append({"severity": "error", "code": code, "location": location, "message": message})
    original_hash = _hash(dataset)
    if not isinstance(dataset, dict):
        error("dataset_invalid", "$", "A frozen dataset must be a JSON object.")
        dataset = {}
    if original_hash is None:
        error("dataset_json_invalid", "$", "The artifact cannot be represented as finite canonical JSON.")
    value = dict(dataset)
    for name, field in (("sources", "source_id"), ("terms", "term_id"), ("records", "record_id"),
                        ("jobs", "job_id"), ("occurrences", "occurrence_id")):
        rows = dataset.get(name, [])
        if not isinstance(rows, list):
            error("table_invalid", name, "A frozen table must be a list of JSON objects.")
            rows = []
        cleaned, seen = [], set()
        for i, row in enumerate(rows):
            location = f"{name}[{i}]"
            if not isinstance(row, dict) or _hash(row) is None:
                error("row_invalid", location, "A frozen row must be a finite JSON object.")
                continue
            rid = row.get(field, row.get("record_id", row.get("term_id")))
            if not isinstance(rid, str) or not rid.strip() or len(rid) > 256:
                error("identifier_invalid", location, "A frozen row needs a bounded nonempty string identifier.")
                continue
            if rid in seen:
                error("duplicate_identifier", name, "Duplicate identifiers cannot be silently collapsed.")
                continue
            seen.add(rid)
            row = dict(row)
            for ref in ("record_id", "term_id", "source_id", "job_id"):
                if ref in row and not isinstance(row[ref], str):
                    error("identifier_invalid", location, "Referenced identifiers must be strings.")
                    row[ref] = rid if name in {"terms", "records"} and ref in {"term_id", "record_id"} else None
            if name == "sources":
                if not isinstance(row.get("text"), str):
                    error("source_text_invalid", location, "Frozen parsed text must be a string.")
                    row["text"] = ""
                if not isinstance(row.get("constraints", {}), dict):
                    error("source_constraints_invalid", location, "Source constraints must be a JSON object.")
                    row["constraints"] = {}
            if name in {"terms", "records"}:
                kind = row.get("record_type", "term")
                if not isinstance(kind, str) or kind not in DATA_TYPES:
                    error("record_contract_invalid", location, "A collected record needs a known record type.")
                    row["record_type"] = "term"
                observed = row.get("observed_text", row.get("expression"))
                if not isinstance(observed, str) or not observed:
                    error("record_contract_invalid", location, "Observed text must be a nonempty verbatim string.")
                variants = row.get("observed_variants", row.get("original_spellings", [observed]))
                if not isinstance(variants, list) or not variants or any(not isinstance(v, str) or not v for v in variants):
                    error("record_variants_invalid", location, "Observed variants must be nonempty strings.")
                    row["observed_variants"] = []
                if row.get("text_origin", "observed_source") != "observed_source":
                    error("record_origin_invalid", location, "Observed records cannot be labeled as generated text.")
                if "record_id" in row and "term_id" in row and row["record_id"] != row["term_id"]:
                    error("record_identifier_alias_mismatch", location, "record_id and its compatibility alias must agree.")
            if name == "jobs":
                for key in ("signature", "model", "expert"):
                    if not isinstance(row.get(key, {}), dict):
                        error("job_signature_invalid", location, "Job signatures, configured models and experts must be JSON objects.")
                        row[key] = {}
            if name == "occurrences":
                for key in ("contexts", "provenance"):
                    children = row.get(key, [])
                    if not isinstance(children, list):
                        error("evidence_structure_invalid", location, "Contexts and provenance must be lists of JSON objects.")
                        children = []
                    row[key] = []
                    for child in children:
                        if not isinstance(child, dict):
                            error("evidence_structure_invalid", location, "Context/provenance entries must be JSON objects.")
                            continue
                        child = dict(child)
                        if "job_id" in child and not isinstance(child["job_id"], str):
                            error("identifier_invalid", location, "Provenance job_id must be a string.")
                            child["job_id"] = None
                        row[key].append(child)
            cleaned.append(row)
        value[name] = cleaned
    if not isinstance(value.get("agent_workflow", {}), dict):
        error("setup_workflow_invalid", "agent_workflow", "Planning lineage must be a JSON object.")
        value["agent_workflow"] = {}
    workflow = dict(value.get("agent_workflow", {}))
    if not isinstance(workflow.get("source_map", {}), dict):
        error("source_map_invalid", "agent_workflow.source_map", "Plan bindings must be a JSON object.")
        workflow["source_map"] = {}
    value["agent_workflow"] = workflow
    result = _audit_dataset(value)
    result["dataset_sha256"] = original_hash
    result["issues"] = structural + result["issues"]
    result["integrity_passed"] = not any(i["severity"] == "error" for i in result["issues"])
    if not isinstance(result.get("version_id"), str):
        result["version_id"] = None
    return result


def _audit_dataset(dataset):
    from .exports import dataset_record_view
    issues, limitations = [], []
    sources = {s["source_id"]: s for s in dataset.get("sources", [])}
    records = {r["record_id"]: r for r in dataset_record_view(dataset)}
    from .exports import record_view
    generic = {r["record_id"]: r for r in record_view(dataset.get("records", []))}
    jobs = {j["job_id"]: j for j in dataset.get("jobs", [])}
    workflow = dataset.get("agent_workflow", {})
    events = workflow.get("events", [])

    def issue(code, location, message, severity="error"):
        issues.append({"severity": severity, "code": code, "location": location, "message": message})

    for record in record_view(dataset.get("terms", [])):
        if record["record_id"] in generic and _hash(generic[record["record_id"]]) != _hash(record):
            issue("record_views_disagree", "records", "Lexical and generic views of the same record disagree.")
    for jid, job in jobs.items():
        signature = job.get("signature", {})
        # Retry/status fields can change; the extraction request signature and
        # its deterministic identifier must still describe the original job.
        if (jid != ident("job", signature) or not _sha(job.get("policy_hash"))
                or signature.get("policy") != job.get("policy_hash")
                or signature.get("model") != job.get("model")
                or signature.get("expert") != job.get("expert")
                or signature.get("start") != job.get("start") or signature.get("end") != job.get("end")
                or signature.get("max_output_tokens") != job.get("max_output_tokens")
                or signature.get("transport") != job.get("transport_identity")):
            issue("job_signature_mismatch", jid, "Configured request fields or policy hash disagree with the deterministic job signature.")
    if not verify_history(events):
        issue("setup_history_hash_mismatch", "agent_workflow.events", "The planning history hash chain does not verify.")
        events = [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []
    approved = {}
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            issue("setup_payload_invalid", "agent_workflow.events", "A planning event payload is malformed.")
            continue
        if event.get("event_type") == "brief_prepared":
            if not isinstance(payload.get("brief"), dict) or not isinstance(payload.get("prompt"), str) or _hash(payload.get("brief")) != payload.get("brief_sha256") or _hash(payload.get("prompt", "")) != payload.get("prompt_sha256"):
                issue("handoff_hash_mismatch", "agent_workflow.events", "A brief or prompt hash does not match its saved contents.")
        if event.get("event_type") == "plan_applied":
            bundle = payload.get("submitted_bundle")
            if not _sha(payload.get("bundle_sha256")) or _hash(bundle) != payload.get("bundle_sha256"):
                issue("plan_hash_mismatch", "agent_workflow.events", "An approved bundle hash does not verify.")
            elif isinstance(bundle, dict):
                selected = bundle.get("sources")
                if not isinstance(selected, list):
                    issue("planned_sources_invalid", "agent_workflow.events", "An approved plan needs a finite list of sources.")
                    continue
                keys = {}
                for source in selected:
                    if not isinstance(source, dict) or not isinstance(source.get("source_key"), str):
                        issue("planned_source_invalid", "agent_workflow.events", "Each planned source needs a string source key.")
                    elif source["source_key"] in keys:
                        issue("planned_source_duplicate", "agent_workflow.events", "Approved source keys must be unique.")
                    else:
                        keys[source["source_key"]] = source
                approved[payload["bundle_sha256"]] = {"bundle": bundle, "sources": keys}
                if not isinstance(bundle.get("recipe"), dict) or _hash(bundle.get("recipe")) != payload.get("recipe_sha256"):
                    issue("applied_recipe_hash_mismatch", "agent_workflow.events", "Applied recipe hash does not match its approved bundle.")
                if payload.get("approval") == "validated_plan_preparation" and payload.get("application_origin") == "guided_preparation":
                    planned_ids = {sid for sid, source in sources.items()
                                   if source.get("constraints", {}).get("agent_plan_sha256") == payload["bundle_sha256"]}
                    prepared_jobs = [job for job in jobs.values() if job.get("source_id") in planned_ids]
                    # Automatic input preparation is not a human approval.
                    # Any extraction jobs for this prepared plan need a prior
                    # hash-bound recorded decision, with its identity caveat.
                    decisions = [event for event in events
                                 if event.get("event_type") == "collection_review_approved"
                                 and isinstance(event.get("payload"), dict)
                                 and isinstance(event["payload"].get("binding"), dict)
                                 and event.get("payload", {}).get("binding", {}).get("bundle_sha256") == payload["bundle_sha256"]
                                 and event.get("payload", {}).get("decision") == "researcher_explicit_collection_approval"
                                 and _timestamp(event.get("created_at"))]
                    if prepared_jobs and not any(
                        all(_timestamp(job.get("created_at")) and decision.get("created_at", "") <= job["created_at"]
                            for job in prepared_jobs) for decision in decisions
                    ):
                        issue("collection_approval_missing", "agent_workflow.events", "Automatically prepared inputs have extraction jobs without a prior recorded collection approval.")
                elif payload.get("approval") != "researcher_explicit_apply":
                    issue("plan_approval_missing", "agent_workflow.events", "An applied plan needs a recognized application event.")
    for sid, source in sources.items():
        if _hash(source.get("text", "")) != source.get("text_sha256"):
            issue("source_text_hash_mismatch", sid, "Frozen parsed text does not match its hash.")
        if not _sha(source.get("raw_sha256")) or not _timestamp(source.get("retrieved_at")) or not isinstance(source.get("parser_version"), str) or not source["parser_version"].strip():
            issue("source_provenance_incomplete", sid, "Source byte hash, retrieval date or parser version is missing.")
        if source.get("publication_date") is None and (not isinstance(source.get("publication_date_reason"), str) or not source["publication_date_reason"].strip()):
            issue("missing_date_reason", sid, "Unavailable publication date needs a reason.")
        constraints = source.get("constraints") or {}
        if any(not isinstance(constraints.get(key), str) or not constraints[key].strip() for key in ("license", "permitted_use", "redistribution")):
            issue("source_use_unresolved", sid, "License, permitted use or redistribution is unresolved; review before sharing data.", "review")
        if not isinstance(constraints.get("original_bytes_archive"), str) or not constraints["original_bytes_archive"].strip():
            issue("original_bytes_archive_unrecorded", sid, "Retain and record an original-byte archive for parser replay; a byte hash cannot reconstruct the document.", "review")
        else:
            issue("original_bytes_archive_unverified", sid, "The archive reference is a declaration; this audit does not read or verify original files.", "review")
        plan_hash = constraints.get("agent_plan_sha256")
        if plan_hash is not None:
            plan = approved.get(plan_hash) if isinstance(plan_hash, str) else None
            keys = plan["sources"] if plan else {}
            source_key = constraints.get("agent_source_key")
            if not plan or not isinstance(source_key, str) or source_key not in keys:
                issue("source_plan_lineage_missing", sid, "The source cannot be joined to its approved agent plan.")
            else:
                selected = keys[source_key]
                mapped = workflow.get("source_map", {}).get(plan_hash + ":" + source_key)
                if (mapped != sid or constraints.get("family_id") != selected.get("family_id")
                        or constraints.get("source_selection_origin") != selected.get("origin")
                        or constraints.get("source_selection_reason") != selected.get("why_selected")
                        or constraints.get("search_refs") != selected.get("search_refs")
                        or constraints.get("approved_locator") != selected.get("locator")
                        or constraints.get("agent_brief_sha256") != plan["bundle"].get("brief_sha256")):
                    issue("source_plan_binding_mismatch", sid, "Source identity, approved locator, family or selection metadata disagrees with its plan binding.")
                metadata = selected.get("metadata")
                declarations = metadata.get("constraints") if isinstance(metadata, dict) else None
                mismatch = (not isinstance(metadata, dict) or not isinstance(declarations, dict))
                if isinstance(metadata, dict):
                    mismatch |= any(source.get(key) != metadata.get(key) for key in ("language", "community", "domain"))
                    mismatch |= metadata.get("publication_date") is not None and source.get("publication_date") != metadata["publication_date"]
                if isinstance(declarations, dict):
                    mismatch |= any(constraints.get(key) != val for key, val in declarations.items())
                if mismatch:
                    issue("source_plan_metadata_mismatch", sid, "Frozen source metadata does not retain its approved declarations.")
        elif events:
            issue("source_outside_agent_plan", sid, "This source was ingested through another workflow; describe its sampling lineage separately.", "review")
    spans, evidenced = 0, set()
    for binding, sid in workflow.get("source_map", {}).items():
        if not isinstance(binding, str) or not isinstance(sid, str):
            issue("source_map_binding_invalid", "agent_workflow.source_map", "Source-map keys and source identifiers must be strings.")
            continue
        plan_hash, separator, source_key = binding.partition(":")
        plan = approved.get(plan_hash)
        source = sources.get(sid)
        if not separator or not plan or source_key not in plan["sources"] or not source:
            issue("source_map_binding_invalid", "agent_workflow.source_map", "A successful source binding cannot be joined to its approved plan and frozen source.")
        elif source.get("constraints", {}).get("agent_plan_sha256") != plan_hash or source.get("constraints", {}).get("agent_source_key") != source_key:
            issue("source_map_binding_invalid", "agent_workflow.source_map", "A successful binding disagrees with its source's saved lineage.")
    for plan_hash, plan in approved.items():
        for source_key in plan["sources"]:
            mapped = workflow.get("source_map", {}).get(plan_hash + ":" + source_key)
            if not isinstance(mapped, str) or mapped not in sources:
                issue("approved_source_not_ingested", "agent_workflow.source_map", "An approved source is staged, failed or absent; disclose missing source coverage.", "review")
    for occurrence in dataset.get("occurrences", []):
        oid = occurrence["occurrence_id"]
        if "record_id" in occurrence and "term_id" in occurrence and occurrence["record_id"] != occurrence["term_id"]:
            issue("record_identifier_alias_mismatch", oid, "Evidence record_id and its compatibility term_id alias disagree.")
        source = sources.get(occurrence.get("source_id"))
        record = records.get(occurrence.get("record_id", occurrence.get("term_id")))
        if not source or not record:
            issue("evidence_join_missing", oid, "Evidence has no matching frozen source or collected record.")
            continue
        evidenced.add(record["record_id"])
        text = source["text"]
        start, end = occurrence.get("start"), occurrence.get("end")
        observed = occurrence.get("expression", occurrence.get("observed_text", record.get("observed_text")))
        valid_offsets = type(start) is int and type(end) is int and 0 <= start < end <= len(text)
        if not valid_offsets or text[start:end] != observed:
            issue("evidence_span_mismatch", oid, "Evidence does not equal the exact frozen source span.")
        else:
            spans += 1
        expected = record.get("observed_variants", [record.get("observed_text")]) if record.get("record_type", "term") == "term" else [record.get("observed_text")]
        kind = record.get("record_type", "term")
        if (observed not in expected or occurrence.get("record_type", "term") != kind
                or occurrence.get("observed_text", observed) != observed
                or occurrence.get("text_origin", "observed_source") != "observed_source"):
            issue("record_evidence_mismatch", oid, "Collected record text/type does not match its observed evidence.")
        contexts = occurrence.get("contexts", [])
        if not contexts:
            issue("context_missing", oid, "Evidence needs an exact source context with Unicode locations.")
        contexts = contexts + [{"text": occurrence.get("context"), "start": occurrence.get("context_start"), "end": occurrence.get("context_end")}]
        for context in contexts:
            begin, finish = context.get("start"), context.get("end")
            if not valid_offsets or type(begin) is not int or type(finish) is not int or not 0 <= begin <= start < end <= finish <= len(text) or text[begin:finish] != context.get("text"):
                issue("context_span_mismatch", oid, "A recorded context does not match frozen text and contain the observed span.")
        if not occurrence.get("provenance"):
            issue("extraction_provenance_missing", oid, "Evidence needs extraction provenance.")
        for provenance in occurrence.get("provenance", []):
            job = jobs.get(provenance.get("job_id"))
            if not job or job.get("source_id") != source["source_id"] or not _sha(job.get("prompt_sha256")) or job.get("prompt_sha256") != provenance.get("prompt_sha256"):
                issue("job_provenance_mismatch", oid, "Extraction provenance cannot be joined to its source job and prompt hash.")
            elif (not valid_offsets or type(job.get("start")) is not int or type(job.get("end")) is not int
                    or not 0 <= job["start"] <= start < end <= job["end"] <= len(text)
                    or job.get("signature", {}).get("source_text_sha256") != source.get("text_sha256")
                    or job.get("signature", {}).get("source_id") != source["source_id"]
                    or job.get("signature", {}).get("prompt_sha256") != job.get("prompt_sha256")
                    or job.get("record_type", "term") != kind or provenance.get("record_type", "term") != kind):
                issue("job_evidence_contract_mismatch", oid, "Evidence type, source hash or bounds do not match the extraction job.")
            if job:
                model, expert, signature = job.get("model", {}), job.get("expert", {}), job.get("signature", {})
                if (provenance.get("provider") != model.get("provider")
                        or provenance.get("model") != model.get("model")
                        or provenance.get("configured_model_version") != model.get("version")
                        or provenance.get("recipe_sha256") != job.get("policy_hash")
                        or provenance.get("recipe_sha256") != signature.get("policy")
                        or provenance.get("prompt_version") != signature.get("prompt_version")
                        or provenance.get("expert_id") != expert.get("id")
                        or provenance.get("stage") != expert.get("stage")
                        or provenance.get("lens") != expert.get("lens")
                        or provenance.get("transport_identity") != job.get("transport_identity")):
                    issue("configured_provenance_mismatch", oid, "Configured provider, model, version, recipe, prompt or expert provenance disagrees with its saved request.")
                reported = provenance.get("reported_model_version")
                if ((reported is not None and not isinstance(reported, str))
                        or reported is None and (not isinstance(provenance.get("reported_model_version_reason"), str)
                                                 or not provenance["reported_model_version_reason"].strip())):
                    issue("reported_model_version_invalid", oid, "Provider-reported model revision must be text or null with a reason; it need not match the configured alias.")
    for rid in sorted(records.keys() - evidenced):
        issue("record_without_evidence", rid, "Every collected record needs at least one frozen source occurrence.")
    pending = [j for j in jobs.values() if j.get("status") not in ("done", "split")]
    if pending or dataset.get("failures"):
        issue("processing_incomplete", "jobs", "Pending, partial, failed or uncertain processing remains; report coverage and failures.", "review")
    if not events:
        limitations.append("No agent setup was recorded; this may be a manually configured study.")
    limitations += ["Deterministic grounding verifies occurrence, not meaning, truth, novelty, semantic type, sentence completeness, sentiment or real-person attribution.",
        "Agent-reported searches, permissions and provenance are declarations, not independently verified facts.",
        "The audit reads only frozen JSON; it does not fetch sources, read archives, execute agents or call models. Retain original files separately for parser replay.",
        "This audit does not establish recall or gold independence. Evaluate complete held-out sources with a documented rubric.",
        "Exported records are reproducible; source search and model inference can be nondeterministic.",
        "Bundle/event hashes cover canonical JSON objects, not original response bytes. Hash chains are not authenticated signatures or guarantees of publication acceptance."]
    return {"schema_version": 1, "audit_version": "publication-audit-v1.1", "version_id": dataset.get("version_id"),
            "dataset_sha256": _hash(dataset), "integrity_passed": not any(i["severity"] == "error" for i in issues),
            "requires_researcher_review": any(i["severity"] == "review" for i in issues),
            "checks": {"sources": len(sources), "records": len(records), "verified_evidence_spans": spans,
                       "planning_events": len(events), "approved_plans": len(approved)},
            "issues": issues, "limitations": limitations}
