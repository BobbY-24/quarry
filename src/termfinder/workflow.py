"""Small researcher workflow over the existing deterministic collection engine.

These functions prepare and explain a plan; they never draft research policy or
silently dispatch a model. Approval is bound to a frozen corpus and configuration.
The collection lock spans the final approval check and engine admission.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat

from . import costs, prompts
from .agent_setup import _credential_free
from .engine import Engine
from .exports import FORMATS
from .providers import FakeProvider, HTTPProvider
from .publication import verify_history
from .store import digest, ident, now

VERSION = "guided-review-v1"


def _selected(project):
    setup = project.agent_setup()
    if not setup.get("applied"):
        raise ValueError("Bring back a validated agent plan before preparing collection")
    if (digest(project.recipe) != setup["recipe_sha256"]
            or digest(project.profile) != setup["profile_sha256"]):
        raise ValueError("Study settings changed. Prepare and review the current plan again")
    # An already captured corpus can resume after original files are moved.
    # Trust only the unchanged, validated plan recorded in the integrity chain;
    # fresh submissions and uncaptured inputs still use filesystem validation.
    validation = setup.get("validation") or {}
    history = project.store.read_setting("agent_workflow") or []
    if not verify_history(history):
        raise ValueError("Research setup history failed its integrity check")
    applied = any(e["event_type"] == "plan_applied"
                  and e["payload"].get("brief_sha256") == setup["brief_sha256"]
                  and e["payload"].get("bundle_sha256") == setup["bundle_sha256"]
                  and digest(e["payload"].get("submitted_bundle")) == setup["bundle_sha256"]
                  and e["payload"].get("recipe_sha256") == setup["recipe_sha256"]
                  and e["payload"].get("profile_sha256") == setup["profile_sha256"]
                  and e["payload"].get("validation", {}).get("valid") is True for e in history)
    if (not applied or validation.get("valid") is not True
            or validation.get("bundle_sha256") != setup["bundle_sha256"]
            or digest(setup["bundle"]) != setup["bundle_sha256"]
            or digest(setup["brief"]) != setup["brief_sha256"]
            or digest(setup["bundle"]["recipe"]) != setup["recipe_sha256"]):
        raise ValueError("The approved plan is no longer valid. Repair and review it again")
    source_map = project.store.read_setting("agent_source_map") or {}
    sources, summaries = [], []
    failures = {a.get("locator"): a.get("reason") for a in project.store.iter_rows("audit")
                if a.get("stage") == "parsing"}
    for declared in setup["bundle"]["sources"]:
        source_id = source_map.get(setup["bundle_sha256"] + ":" + declared["source_key"])
        source = project.store.get("sources", source_id) if source_id else None
        if source:
            metadata = source.get("constraints", {})
            if (metadata.get("agent_plan_sha256") != setup["bundle_sha256"]
                    or metadata.get("agent_brief_sha256") != setup["brief_sha256"]
                    or metadata.get("agent_source_key") != declared["source_key"]
                    or metadata.get("approved_locator") != declared["locator"]):
                raise ValueError("An imported source no longer matches its approved plan")
        exclusion = project.source_exclusion(source) if source else None
        state = "excluded" if exclusion else "ready" if source else "failed" if declared["locator"] in failures else "pending"
        summaries.append({"source_key": declared["source_key"], "source_id": source_id,
            "locator": declared["locator"], "kind": declared["kind"], "status": state,
            "reason": exclusion or failures.get(declared["locator"]),
            "characters": len(source["text"]) if source else None,
            "language": (source or declared["metadata"]).get("language"),
            "community": (source or declared["metadata"]).get("community"),
            "family_id": declared["family_id"], "why_selected": declared["why_selected"]})
        if source:
            if digest(source["text"]) != source["text_sha256"]:
                raise ValueError("A source failed its content hash check; collection is blocked")
            sources.append(source)
    return setup, sources, summaries


def _source_binding(sources):
    # Include retained source metadata as well as text/raw hashes. Changes to
    # dates, language, scope or use constraints require a new visible decision.
    return sorted(({"source_id": s["source_id"], "text_sha256": s["text_sha256"],
                    "source_sha256": digest(s)} for s in sources), key=lambda s: s["source_id"])


def _packet_sha256(project, version_id, filename):
    """Hash frozen UTF-8 bytes with bounded memory and no symlink traversal."""
    if (not isinstance(version_id, str) or not re.fullmatch(r"dataset_[0-9a-f]{32}", version_id)
            or not isinstance(filename, str) or Path(filename).name != filename
            or filename in {".", ".."}):
        raise ValueError("The frozen human-review packet is missing or unsafe")
    directory = None
    try:
        directory = os.open(project.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in ("human-review", version_id):
            next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("The frozen human-review packet must be a regular file")
            checksum, remaining = hashlib.sha256(), info.st_size
            while remaining:
                block = stream.read(min(65_536, remaining))
                if not block:
                    raise ValueError("The frozen human-review packet changed while being read")
                checksum.update(block)
                remaining -= len(block)
            if stream.read(1):
                raise ValueError("The frozen human-review packet changed while being read")
        return checksum.hexdigest()
    except OSError:
        raise ValueError("The frozen human-review packet is missing or unsafe") from None
    finally:
        if directory is not None:
            os.close(directory)


def _matching_freeze(project, setup, sources):
    history = project.store.read_setting("agent_workflow") or []
    if not verify_history(history):
        raise ValueError("Research setup history failed its integrity check")
    selected = {s["source_id"]: digest(s) for s in sources}
    for event in reversed(history):
        payload = event["payload"]
        if event["event_type"] != "blind_corpus_prepared" or payload.get("bundle_sha256") != setup["bundle_sha256"]:
            continue
        try:
            dataset = project.dataset(payload["version_id"])
        except (ValueError, KeyError):
            continue
        frozen = {s["source_id"]: digest(s) for s in dataset["sources"] if s["source_id"] in selected}
        if (frozen != selected or payload.get("source_count") != len(selected)
                or digest(dataset["recipe"]) != digest(project.recipe)
                or digest(dataset["profile"]) != digest(project.profile)
                or dataset["prompts"] != prompts.manifest()):
            continue
        out = project.path / "human-review" / payload["version_id"]
        files = payload.get("file_sha256", {})
        if not files or out.parent.is_symlink() or out.is_symlink():
            raise ValueError("The frozen human-review packet is missing or unsafe")
        for filename, expected in files.items():
            path = out / filename
            if Path(filename).name != filename or path.is_symlink() or not path.is_file():
                raise ValueError("The frozen human-review packet is missing or unsafe")
            if _packet_sha256(project, payload["version_id"], filename) != expected:
                raise ValueError("The frozen human-review packet changed; restore its original files")
        return {k: deepcopy(v) for k, v in payload.items() if k not in {"bundle_sha256", "file_sha256"}}
    return None


def _binding(project, setup, sources, estimate, freeze):
    return {"version": VERSION, "brief_sha256": setup["brief_sha256"],
            "bundle_sha256": setup["bundle_sha256"], "recipe_sha256": digest(project.recipe),
            "profile_sha256": digest(project.profile), "prompts_sha256": digest(prompts.manifest()),
            "sources": _source_binding(sources), "estimate_sha256": digest(estimate),
            "freeze_version_id": freeze["version_id"]}


def _estimate(project, sources, assumptions=None):
    eligible = [source for source in sources if project.source_exclusion(source) is None]
    return costs.estimate(project.recipe, project.profile, eligible, **(assumptions or {}))


def prepare_review(project, bundle=None, *, fetch_remote=False):
    """Apply inputs, import permitted sources, freeze blind packets and estimate.

    URL fetching requires this explicit flag. Failed sources remain visible and
    do not erase usable sources. Preparing never creates extraction jobs.
    """
    if type(fetch_remote) is not bool:
        raise ValueError("fetch_remote must be an explicit boolean")
    if bundle is not None:
        report = project.validate_agent_bundle(bundle)
        if not report["valid"]:
            return {"ready": False, "review_id": None, "validation": report,
                    "message": "Send the correction request to your agent, then check its revised plan."}
        setup = project.agent_setup()
        if not setup.get("applied") or setup.get("bundle_sha256") != report["bundle_sha256"]:
            project.apply_agent_bundle(bundle, purpose="guided_preparation")
    setup = project.agent_setup()
    source_map = project.store.read_setting("agent_source_map") or {}
    # Existing captured sources are immutable inputs on resume. Ingestion is
    # needed only for uncaptured local files or an explicitly requested URL.
    needs_ingest = any((source["kind"] == "local" or fetch_remote)
        and not project.store.get("sources", source_map.get(setup.get("bundle_sha256", "") + ":" + source["source_key"], ""))
        for source in setup.get("bundle", {}).get("sources", []))
    if needs_ingest:
        project.ingest_agent_sources(include_remote=fetch_remote)
    with project._lock():
        setup, sources, summaries = _selected(project)
        if not sources:
            return {"ready": False, "review_id": None, "sources": summaries,
                    "failures": [s for s in summaries if s["status"] == "failed"],
                    "message": "No source text is ready. Inspect the source problems before collection."}
        freeze = _matching_freeze(project, setup, sources)
        if freeze is None:
            if (project.path / "human-review").is_symlink():
                raise ValueError("The human-review directory must stay inside this project")
            freeze = project._freeze_agent_corpus_unlocked("review-corpus", "v6-agent-study-v1")
        estimate = _estimate(project, sources)
        binding = _binding(project, setup, sources, estimate, freeze)
        review_id = ident("review", binding)
        pending = [s for s in summaries if s["status"] == "pending"]
        eligible = [s for s in summaries if s["status"] == "ready"]
        previous = project.store.read_setting("guided_review") or {}
        approval = previous.get("approval") if previous.get("review_id") == review_id else None
        result = {"version": VERSION, "review_id": review_id, "ready": bool(eligible) and not pending,
            "created_at": previous.get("created_at") if previous.get("review_id") == review_id else now(),
            "question": setup["brief"]["research_question"], "data_type": setup["brief"]["data_type"],
            "mode": project.recipe["mode"], "model_profile": project.profile["id"],
            "compute": project.compute(),
            "source_count": len(sources), "eligible_source_count": len(eligible),
            "sources": summaries, "failures": [s for s in summaries if s["status"] == "failed"],
            "pending_sources": pending, "freeze": freeze, "estimate": estimate,
            "budget_usd": project.recipe["execution"]["budget_usd"], "binding": binding,
            "approval": approval,
            "message": "Review the source list and spending estimate, then start collection." if eligible and not pending else "Fetch or repair pending sources before starting collection.",
            "rigor_note": "Source occurrence is checked deterministically. Proposed meanings and completeness still require human evaluation. Blank whole-source packets are not gold.",
            "external_agent_costs": {"actual_usd": None, "reason": "not_metered_by_collector", "included_in_collector_budget": False}}
        with project.store.connection() as db:
            # Repeated preparation must reuse the same frozen corpus and review.
            if previous.get("review_id") != review_id:
                project._plan_event("collection_review_prepared", {"review_id": review_id,
                    "binding": binding, "ready": result["ready"]}, db)
            project.store.setting("guided_review", result, db)
        return deepcopy(result)


def _check_review_unlocked(project, review_id, *, require_ready=True):
    saved = project.store.read_setting("guided_review") or {}
    if not isinstance(review_id, str) or saved.get("review_id") != review_id:
        raise ValueError("This collection review is outdated. Prepare the current plan again")
    if require_ready and not saved.get("ready"):
        raise ValueError("Resolve pending sources before approving collection")
    setup, sources, summaries = _selected(project)
    freeze = _matching_freeze(project, setup, sources)
    if freeze is None:
        raise ValueError("The current source corpus was not frozen before extraction")
    names = ("cache_fraction", "chars_per_token", "output_tokens_per_window", "recovery_fraction",
             "parsing_usd_per_source", "translation_usd_per_source")
    estimate = _estimate(project, sources, {key: saved["estimate"]["assumptions"][key] for key in names})
    binding = _binding(project, setup, sources, estimate, freeze)
    if binding != saved["binding"] or ident("review", binding) != review_id:
        raise ValueError("Sources, settings or costs changed. Prepare and approve the current plan again")
    if require_ready and any(s["status"] == "pending" for s in summaries):
        raise ValueError("New pending sources require a fresh collection review")
    return saved, sources


def current_review(project, *, check=True):
    """Read persisted review for UI/agents; stale reviews cannot authorize work."""
    saved = deepcopy(project.store.read_setting("guided_review") or {})
    if not saved:
        return {}
    if type(check) is not bool:
        raise ValueError("check must be a boolean")
    if not check:
        saved.update(approved=bool(saved.get("approval")), stale=None, check_deferred=True,
                     approval_verified=False)
        return saved
    try:
        with project._lock():
            _check_review_unlocked(project, saved["review_id"], require_ready=False)
            if saved.get("approval"):
                _approval_unlocked(project, saved)
    except (ValueError, KeyError):
        saved.update(stale=True, approved=False, approval_verified=False)
    except RuntimeError:
        # A running collector owns the same lock and already rechecked admission.
        saved.update(check_deferred=True, approval_verified=False)
    else:
        approved = bool(saved.get("approval")) and bool(saved.get("ready"))
        saved.update(stale=False, approved=approved, approval_verified=approved)
    return saved


def approve_review(project, review_id, *, approval_reference=None, approval_origin="researcher"):
    """Persist an explicit decision for this exact configuration and corpus."""
    if approval_reference is not None and (not isinstance(approval_reference, str) or not approval_reference.strip() or len(approval_reference) > 1000):
        raise ValueError("The approval reference must be bounded text")
    if approval_origin not in {"researcher", "browser", "cli", "agent_relay", "notebook"}:
        raise ValueError("Unknown approval origin")
    _credential_free(approval_reference)
    with project._lock(), project.store.connection() as db:
        review, _ = _check_review_unlocked(project, review_id)
        if review.get("approval"):
            return deepcopy(_approval_unlocked(project, review))
        payload = {"review_id": review_id, "binding": review["binding"],
                   "decision": "researcher_explicit_collection_approval",
                   "approval_origin": approval_origin, "approval_reference": approval_reference,
                   "identity_note": "Recorded declaration; not an authentication or human-identity proof"}
        approval = {"review_id": review_id, "approved_at": now(),
                    "approval_id": project._plan_event("collection_review_approved", payload, db)}
        review["approval"] = approval
        project.store.setting("guided_review", review, db)
        return deepcopy(approval)


def _approval_unlocked(project, review):
    approval = review.get("approval")
    if not approval:
        raise ValueError("Review the sources and estimate, then explicitly approve collection")
    history = project.store.read_setting("agent_workflow") or []
    if not any(e["event_sha256"] == approval.get("approval_id") and e["event_type"] == "collection_review_approved"
               and e["payload"].get("review_id") == review["review_id"]
               and e["payload"].get("binding") == review["binding"] for e in history):
        raise ValueError("Collection approval failed its history integrity check")
    return approval


def check_review(project, review_id, *, allow_paid=False):
    """Synchronous preflight for agent/UI dispatch; run repeats it under its lock."""
    if type(allow_paid) is not bool:
        raise ValueError("allow_paid must be an explicit boolean")
    with project._lock():
        review, sources = _check_review_unlocked(project, review_id)
        approval = _approval_unlocked(project, review)
        paid = any(p["adapter"] != "fake" for p in project.profile["providers"].values())
        if paid and not allow_paid:
            raise ValueError("This profile requires explicit paid collection authorization")
        return {"review_id": review_id, "approval_id": approval["approval_id"],
                "source_count": len(sources), "model_profile": project.profile["id"],
                "paid_authorized": paid and allow_paid, "ready": True}


class _ReviewedProject:
    """Reuse Engine unchanged, restrict this admission to approved sources."""
    def __init__(self, project, sources):
        self.project, self.source_ids = project, {s["source_id"] for s in sources}
        self.path, self.store, self.recipe, self.profile = project.path, project.store, project.recipe, project.profile

    def source_exclusion(self, source):
        return "outside_reviewed_source_inventory" if source["source_id"] not in self.source_ids else self.project.source_exclusion(source)

    def status(self):
        return self.project.status()


def run_review(project, review_id, *, provider=None, allow_paid=False, max_jobs=None):
    """Recheck the approved fingerprint and resume while holding admission lock."""
    if type(allow_paid) is not bool:
        raise ValueError("allow_paid must be an explicit boolean")
    if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 1):
        raise ValueError("max_jobs must be a positive integer")
    with project._lock():
        # Resume clears the preceding run's cancellation before potentially
        # lengthy corpus checks. A new stop request during those checks must
        # survive admission and reach Engine.prepare/run unchanged.
        project.store.setting("cancel_requested", False)
        review, sources = _check_review_unlocked(project, review_id)
        approval = _approval_unlocked(project, review)
        if provider is None:
            if all(p["adapter"] == "fake" for p in project.profile["providers"].values()):
                provider = FakeProvider()
            elif allow_paid:
                provider = HTTPProvider(project.profile)
            else:
                raise ValueError("This profile requires explicit paid collection authorization")
        if getattr(provider, "paid", False) and not allow_paid:
            raise ValueError("Paid transport requires explicit authorization")
        with project.store.connection() as db:
            project._plan_event("reviewed_collection_started", {"review_id": review_id,
                "approval_id": approval["approval_id"], "paid_transport": bool(getattr(provider, "paid", False)),
                "max_jobs": max_jobs}, db)
        engine = Engine(_ReviewedProject(project, sources), provider)
        result = engine.run(max_jobs)
        with project.store.connection() as db:
            job_counts = dict(db.execute("SELECT json_extract(j.data,'$.status'),count(*) FROM jobs j JOIN run_jobs r ON r.job_id=j.id WHERE r.run_id=? GROUP BY 1", (engine.run_id,)))
        run = project.store.get("runs", engine.run_id)
        scope = {"run_id": engine.run_id, "status": run["status"], "coverage": run["coverage"],
                 "jobs": job_counts, "approved_source_count": len(sources),
                 "eligible_source_count": sum(project.source_exclusion(source) is None for source in sources),
                 "inventory_note": "The top-level inventory, job counts, failures and cost ledger retain all project history. This scope describes only this reviewed collection; model completion is not measured recall."}
        with project.store.connection() as db:
            project._plan_event("reviewed_collection_finished", {"review_id": review_id,
                "run_id": (result.get("last_run") or {}).get("run_id"), "status": result["status"],
                "stop_reason": result.get("stop_reason")}, db)
        return {**result, "review_id": review_id, "approval_id": approval["approval_id"],
                "review_scope": scope}


def release_dataset(project, name, formats=None, *, version_id=None):
    """Save once per named release, audit and export without inference calls.

    Reusing a release name reproduces its frozen version, even if the live
    inventory later changes. Choose a new name to publish a new local version.
    """
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise ValueError("Choose a dataset name of 1–128 characters")
    formats = list(dict.fromkeys(formats or ("csv", "jsonl", "parquet", "annotation")))
    if not formats or any(not isinstance(f, str) or f not in FORMATS for f in formats):
        raise ValueError("Use csv, jsonl, parquet or annotation exports")
    with project._lock():
        if project.status()["status"] == "running":
            raise ValueError("Stop the active collection before saving a dataset")
        saved = project.store.read_setting("guided_releases") or {}
        prior = saved.get(name)
        if prior and version_id is not None and prior != version_id:
            raise ValueError("This dataset name already identifies a different frozen version")
        version_id = version_id or prior
        if version_id is None:
            version_id = project._snapshot_unlocked(name)
        dataset = project.dataset(version_id)
        # Save the name binding before export so an interruption retries the
        # same version instead of creating duplicate snapshots.
        with project.store.connection() as db:
            if not prior:
                saved[name] = version_id
                project.store.setting("guided_releases", saved, db)
                project._plan_event("dataset_release_saved", {"name": name, "version_id": version_id,
                    "dataset_sha256": digest(dataset)}, db)
        audit = project.publication_audit(version_id)
        if (project.path / "exports").is_symlink():
            raise ValueError("The export directory must stay inside this project")
        exported = project.export(version_id, project.path / "exports" / version_id, formats)
        return {"name": name, "version_id": version_id, "out": exported["out"],
                "files": sorted(exported["manifest"]["files"]), "manifest": exported["manifest"],
                "audit": audit, "coverage": dataset.get("coverage"),
                "note": "Frozen exports reproduce retained records. Integrity checks do not certify semantic truth, recall, sampling quality or permission to redistribute sources."}
