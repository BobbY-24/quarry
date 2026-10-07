"""Controlled offline recovery experiments against the real Quarry engine.

Faults and responses are keyed by logical request, never by thread completion
order. Every arm owns a new SQLite database, cache and fake transport journal.
The fake journal represents observable dispatches, not provider invoices.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import threading

from .config import canonical, load_profile, starter_recipe
from .costs import reserve_cost
from .engine import Engine
from .project import Project
from .providers import ProviderError, Response
from .resilience import DEFAULT_RESILIENCE
from .sources import parse_document
from .store import digest, now

VERSION = "quarry-recovery-experiment/1"
CACHE_IDENTITY = "quarry-request-keyed-fault/1"
EXPRESSIONS = ("moonstep", "glowpause", "reefturn", "cloudskip")
PROVIDER_ACTIONS = frozenset({"success", "timeout", "transient", "uncertain",
                              "truncation", "malformed", "refusal"})
SCENARIOS = (
    "before_dispatch", "during_uncertain_request", "before_cache_persistence",
    "cache_transaction_rollback", "after_cache_persistence",
    "grounding_transaction_rollback", "after_grounding_before_completion",
    "truncation", "timeout", "transient", "malformed", "refusal",
    "call_exhaustion", "budget_exhaustion", "deadline_exhaustion",
    "cancellation", "cache_invalidation",
)


def logical_request_key(request):
    """Bind frozen input/expert/window/decoding independently of scheduling.

    Model revision is deliberately excluded from the *logical* response key so
    cache invalidation can hold responses constant. Engine job/cache keys still
    bind the complete model configuration and invalidate on revision changes.
    """
    return digest({"source_id": request["source"]["source_id"],
        "source_text_sha256": request["source"]["text_sha256"],
        "expert": request["expert"], "start": request["start"],
        "end": request["start"] + len(request["text"]),
        "prompt_sha256": digest(request["prompt"]),
        "max_output_tokens": request["max_output_tokens"]})


def logical_response(request):
    """A fixed source-grounded response, identical across all experiment arms."""
    candidates = [{"expression": expression, "language": "en",
        "sense": "synthetic recovery fixture", "context": request["text"],
        "start": None, "attributes": {}, "definition_quote": None,
        "translation": None} for expression in EXPRESSIONS if expression in request["text"]]
    return Response(canonical({"candidates": candidates, "coverage_complete": True}),
        32, 24, "stop", "synthetic-request-keyed-v1",
        "fake_" + logical_request_key(request)[:24])


class RequestKeyedProvider:
    """Offline transport with a durable per-request attempt journal.

    A schedule maps a request hash to its ordered local-attempt actions. Calls
    for other requests cannot consume a fault. Reconstructing this provider
    from the same journal preserves the local attempt schedule after reopen.
    """
    paid = False
    cache_identity = CACHE_IDENTITY

    def __init__(self, schedule=None, *, journal=None):
        self.schedule = deepcopy(schedule or {})
        if len(self.schedule) > 128 or any(not isinstance(key, str) or len(key) != 64 or
               any(character not in "0123456789abcdef" for character in key) or
               not isinstance(actions, (list, tuple)) or not actions or
               len(actions) > 16 or
               any(action not in PROVIDER_ACTIONS for action in actions)
               for key, actions in self.schedule.items()):
            raise ValueError("fault schedule requires request hashes and finite named actions")
        self.journal = Path(journal) if journal is not None else None
        self.events = []
        self.counts = Counter()
        self._lock = threading.Lock()
        if self.journal is not None and self.journal.exists():
            if self.journal.stat().st_size > 1_000_000:
                raise ValueError("fake transport journal exceeds experiment bound")
            for line in self.journal.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("schedule_sha256") != digest(self.schedule):
                    raise ValueError("fake transport journal belongs to another fault schedule")
                key = event["logical_request_key"]
                if event["local_attempt"] != self.counts[key] + 1:
                    raise ValueError("fake transport journal is inconsistent")
                self.counts[key] += 1
                self.events.append(event)

    def complete(self, request):
        key = logical_request_key(request)
        response = logical_response(request)
        with self._lock:
            attempt = self.counts[key] + 1
            actions = self.schedule.get(key, ())
            action = actions[attempt - 1] if attempt <= len(actions) else "success"
            event = {"logical_request_key": key, "job_id": request["job_id"],
                     "local_attempt": attempt, "action": action,
                     "schedule_sha256": digest(self.schedule),
                     "logical_response_sha256": digest(asdict(response)),
                     "billing_observed": False}
            if self.journal is not None:
                self.journal.parent.mkdir(parents=True, exist_ok=True)
                with self.journal.open("a", encoding="utf-8") as stream:
                    stream.write(canonical(event) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            self.counts[key] += 1
            self.events.append(event)
        if action == "timeout":
            raise ProviderError("request_wall_timeout_outcome_unknown", uncertain=True, retryable=True)
        if action == "uncertain":
            raise ProviderError("transport_outcome_unknown", uncertain=True, retryable=True)
        if action == "transient":
            raise ProviderError("http_503", retryable=True)
        if action == "malformed":
            return Response("{not JSON", 32, 24, "stop", response.model_version, response.request_id)
        if action == "refusal":
            return Response("Synthetic refusal to enumerate this window.", 32, 24,
                            "content_filter", response.model_version, response.request_id)
        if action == "truncation":
            candidates = json.loads(response.text)["candidates"]
            raw = '{"candidates":[' + (canonical(candidates[0]) + ',' if candidates else '')
            return Response(raw, 32, 24, "length", response.model_version, response.request_id)
        return response


class ExperimentClock:
    """Deterministic scheduler time; provider calls never sleep or use a network."""
    def __init__(self):
        self.value = 1_800_000_000.0
        self.on_sleep = None
        self.sleep_calls = 0
        self.scheduled_wait_seconds = 0.0

    def time(self): return self.value
    def monotonic(self): return self.value
    def sleep(self, delay):
        self.sleep_calls += 1
        self.scheduled_wait_seconds += delay
        self.value += max(0.001, delay)
        if self.on_sleep is not None: self.on_sleep()


class InjectedInterruption(RuntimeError):
    """A controlled local interruption, caught only by the experiment runner."""


@contextmanager
def _interrupt_write(store, table, predicate=lambda row: True, *, after=True):
    original = store.put
    fired = False

    def put(name, key, value, db=None):
        nonlocal fired
        selected = not fired and name == table and predicate(value)
        if selected and not after:
            fired = True
            raise InjectedInterruption(table)
        result = original(name, key, value, db)
        if selected:
            fired = True
            raise InjectedInterruption(table)
        return result

    store.put = put
    try:
        yield
    finally:
        store.put = original


def fixture_sources():
    result = []
    for number, expression in enumerate(EXPRESSIONS):
        text = (f"Synthetic source {number}. " + "The players waited by the gate. " * 3 +
                f"They call this pause {expression}. " + "The session continues quietly. " * 4)
        result.append(parse_document(text.encode(), "text/plain", f"recovery-{number}.txt",
            {"language": "en", "community": "Gaming", "retrieved_at": "2026-10-06T00:00:00Z",
             "constraints": {"content_origin": "synthetic_fixture", "permitted_use": "offline_testing"}}))
    return result


def _configuration(concurrency):
    recipe = starter_recipe("neologisms")
    recipe["model_profile"] = "fake"
    recipe["execution"].update(concurrency=concurrency, max_calls=128,
        max_retries=2, deadline_seconds=60, timeout_seconds=1, window_chars=3000,
        overlap_chars=32, split_depth=1, max_output_tokens=128, recovery_output_tokens=256,
        resilience=deepcopy(DEFAULT_RESILIENCE), budget_usd=20)
    recipe["execution"]["stage_budgets"].update(extraction=20, specialist=0)
    recipe["execution"]["resilience"].update(delays_seconds=[2, 4], jitter_fraction=0,
        min_request_interval_seconds=0, model_concurrency=1, max_retry_calls=16)
    recipe["exports"].update(formats=["jsonl", "csv"], annotation=False)
    profile = load_profile("fake")
    for model in profile["models"].values():
        model.update(input_per_million=1, output_per_million=1,
                     price_note="Synthetic reservation rate; no provider invoice or payment.")
    return recipe, profile


def _evidence(project):
    occurrences = project.store.all("occurrences")
    observed = {canonical([row["source_id"], row["start"], row["end"], row["expression"],
                           row["language"], row["term_id"]]) for row in occurrences}
    expert_evidence = {canonical([row["source_id"], row["start"], row["end"], row["expression"],
                                  row["term_id"], provenance["expert_id"]])
                       for row in occurrences for provenance in row["provenance"]}
    return {"occurrences": sorted(observed), "expert_evidence": sorted(expert_evidence)}


def _checkpoint(project, provider):
    costs = project.store.all("costs")
    return {"evidence": _evidence(project), "provider_dispatches": len(provider.events),
            "ledger_attempts": len(costs), "job_status_counts": dict(Counter(
                row["status"] for row in project.store.all("jobs"))),
            "cache_entries": project.store.count("cache"),
            "uncertain_attempts": sum(row["status"] == "uncertain" for row in costs),
            "unsettled_attempts": sum("settled_usd" not in row for row in costs)}


def _root_work(project, provider):
    engine = Engine(project, provider)
    run = project.store.get("runs", project.store.read_setting("last_run_id"))
    result = []
    for key in run["root_job_ids"]:
        job = project.store.get("jobs", key)
        result.append({"logical_request_key": logical_request_key(engine.request(job)),
                       "source_id": job["source_id"], "expert_id": job["expert"]["id"],
                       "complete": engine.coverage(key), "status": job["status"],
                       "reason": job["reason"]})
    return sorted(result, key=lambda row: row["logical_request_key"])


def _stage_interruption(engine, job, scenario):
    """Commit real engine stages, interrupt at one boundary, then reopen.

    Other requests are deliberately not dispatched in this boundary experiment;
    this holds the interruption point constant when scheduler concurrency varies.
    """
    if scenario == "before_dispatch":
        raise InjectedInterruption("before admission and provider dispatch")
    attempt, reason = engine.admit(job)
    if reason: raise ValueError("fixture admission unexpectedly rejected")
    response = engine.provider.complete(engine.request(job))
    if scenario in {"during_uncertain_request", "before_cache_persistence"}:
        # The fake endpoint observed a dispatch; the collector has no durable
        # response/settlement, so prepare must retain the reserve as uncertain.
        raise InjectedInterruption(scenario)
    if scenario == "cache_transaction_rollback":
        with _interrupt_write(engine.store, "cache"):
            engine.settle(job, attempt, response)
    elif scenario == "after_cache_persistence":
        original = engine.accept
        def interrupt(*args, **kwargs):
            raise InjectedInterruption("after committed cache before grounding")
        engine.accept = interrupt
        try: engine.settle(job, attempt, response)
        finally: engine.accept = original
    elif scenario == "grounding_transaction_rollback":
        with _interrupt_write(engine.store, "occurrences"):
            engine.settle(job, attempt, response)
    elif scenario == "after_grounding_before_completion":
        with _interrupt_write(engine.store, "jobs", lambda row: row["status"] == "done", after=False):
            engine.settle(job, attempt, response)


def _file_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.iterdir()) if path.is_file()}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def _run_arm(root, name, sources, concurrency):
    arm = root / name
    arm.mkdir()
    project = Project(arm / "project")
    recipe, profile = _configuration(concurrency)
    # Eight roots are planned, but the injected failed call makes completion
    # require a ninth dispatch. This isolates admission exhaustion from planning.
    if name == "call_exhaustion": recipe["execution"]["max_calls"] = 8
    if name == "deadline_exhaustion": recipe["execution"]["deadline_seconds"] = 1
    if name == "budget_exhaustion":
        cap = reserve_cost(profile["models"]["glm"], recipe["execution"]["max_output_tokens"])
        recipe["execution"]["budget_usd"] = cap
        recipe["execution"]["stage_budgets"]["extraction"] = cap
    project.configure(recipe, profile)
    for source in sources: project.add_source(source)
    clock = ExperimentClock()
    journal = arm / "provider-dispatches.jsonl"
    provider = RequestKeyedProvider(journal=journal)
    engine = Engine(project, provider, clock=clock, random=lambda: 0)
    roots = engine.prepare()
    target_id = min(key for key in roots if project.store.get("jobs", key)["expert"]["model"] == "glm")
    target = project.store.get("jobs", target_id)
    target_key = logical_request_key(engine.request(target))
    action = {"timeout": "timeout", "transient": "transient", "malformed": "malformed",
              "refusal": "refusal", "truncation": "truncation", "deadline_exhaustion": "timeout",
              "budget_exhaustion": "timeout", "call_exhaustion": "timeout",
              "cancellation": "timeout"}.get(name)
    schedule = {target_key: [action]} if action else {}
    provider = RequestKeyedProvider(schedule, journal=journal)
    engine.provider = provider
    _write_json(arm / "schedule.json", {"version": VERSION, "scenario": name,
        "target_logical_request_key": target_key, "target_job_id": target_id,
        "provider_actions": schedule, "response_contract": "same logical_response for every arm"})
    if name == "cancellation": clock.on_sleep = project.cancel
    boundary_scenarios = set(SCENARIOS[:7])
    interruption = None
    first_status = None
    if name in boundary_scenarios:
        project.store.put("runs", engine.run_id, {"run_id": engine.run_id, "status": "running",
            "created_at": now(), "root_job_ids": roots, "recipe": recipe, "profile": profile,
            "transport_identity": CACHE_IDENTITY, "budget_scope": engine.budget_scope})
        try:
            _stage_interruption(engine, target, name)
        except InjectedInterruption as error:
            interruption = str(error)
        else:
            raise ValueError("scheduled interruption did not fire")
    else:
        first_status = engine.run()
    first = _checkpoint(project, provider)
    # Reconstruct BOTH sides from durable state: database and fake transport
    # journal. No global response list or in-memory attempt counter survives.
    project = Project(project.path)
    provider = RequestKeyedProvider(schedule, journal=journal)
    clock.on_sleep = None
    if name == "cancellation": project.store.setting("cancel_requested", False)
    intentional_identity_change = 0
    if name == "cache_invalidation":
        changed = deepcopy(project.profile)
        changed["models"]["glm"]["version"] = "synthetic-revision-2"
        project.configure(project.recipe, changed)
        intentional_identity_change = len(sources)
    status = Engine(project, provider, clock=clock, random=lambda: 0).run()
    final = _checkpoint(project, provider)
    root_work = _root_work(project, provider)
    version = project.snapshot("recovery-" + name)
    first_export = arm / "frozen-export"
    project.export(version, first_export, ["jsonl", "csv"])
    # Frozen export identity is measured after a live annotation change and
    # another resume, not assumed from two exports of an untouched project.
    terms = project.store.all("terms")
    if terms: project.annotate(terms[0]["term_id"], "approved", "Synthetic reversible review.")
    before_warm_resume = len(provider.events)
    if status["status"] == "complete":
        Engine(project, provider, clock=clock, random=lambda: 0).run()
        warm_resume_dispatches = len(provider.events) - before_warm_resume
    else:
        # A new run grants a new per-run deadline. Do not silently add that
        # resource to an exhausted condition merely to check frozen export IO.
        warm_resume_dispatches = None
    second_export = arm / "frozen-reexport"
    project.export(version, second_export, ["jsonl", "csv"])
    hashes_before, hashes_after = _file_hashes(first_export), _file_hashes(second_export)
    costs = project.store.all("costs")
    jobs = project.store.all("jobs")
    report = {"arm": name, "simulated_only": True, "concurrency": concurrency,
        "scenario": name, "target_logical_request_key": target_key,
        "boundary_interruption": interruption, "first_status": first_status,
        "final_status": status, "first_checkpoint": first, "final_checkpoint": final,
        "evidence": final["evidence"], "provider_dispatches": len(provider.events),
        "root_work": root_work,
        "provider_dispatches_by_logical_request": dict(sorted(provider.counts.items())),
        "repeated_logical_dispatches": sum(max(0, count - 1) for count in provider.counts.values()),
        "intentional_identity_change_dispatches": intentional_identity_change,
        "retry_ledger_attempts": sum(row.get("is_retry", False) for row in costs),
        "uncertain_reservations": {"attempts": sum(row["status"] == "uncertain" for row in costs),
            "held_simulated_usd": sum(row["reserved_usd"] for row in costs
                                       if row["status"] == "uncertain" and "settled_usd" not in row),
            "not_provider_invoice": True},
        "recovery_effort": {"database_reopens": 1, "explicit_cancel_clears": int(name == "cancellation"),
            "new_dispatches_after_reopen": final["provider_dispatches"] - first["provider_dispatches"],
            "automatic_retry_attempts": sum(row.get("is_retry", False) for row in costs),
            "split_children": sum(row["depth"] > 0 for row in jobs),
            "scheduler_wait_seconds": round(clock.scheduled_wait_seconds, 6),
            "human_active_time_seconds": None, "human_active_time_reason": "offline_fixture_has_no_human_session"},
        "warm_resume_dispatches": warm_resume_dispatches,
        "warm_resume_dispatches_reason": None if warm_resume_dispatches is not None else "partial_condition_not_given_another_resource_envelope",
        "frozen_export": {"version_id": version, "identity_preserved": hashes_before == hashes_after,
            "before_sha256_by_file": hashes_before, "after_sha256_by_file": hashes_after,
            "live_annotation_changed": bool(terms)},
        "dispatch_events": sorted(provider.events, key=lambda event: (event["logical_request_key"], event["local_attempt"])),
        "limits": project.recipe["execution"]}
    _write_json(arm / "report.json", report)
    return report


def run_fault_suite(out, concurrency=2, *, scenarios=None):
    """Write a cold-cache reference and isolated recovery arms; never run paid IO.

    Existing destinations are rejected, avoiding accidental reuse of caches or
    overwrite of previous evidence. Reports compare all frozen source evidence
    and per-expert evidence, even when planning/call limits leave jobs absent.
    """
    if type(concurrency) is not int or not 1 <= concurrency <= 8:
        raise ValueError("offline fault-suite concurrency must be between one and eight")
    selected = tuple(SCENARIOS if scenarios is None else scenarios)
    if not selected or len(set(selected)) != len(selected) or any(name not in SCENARIOS for name in selected):
        raise ValueError("select distinct known fault scenarios")
    root = Path(out).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=False)
    sources = fixture_sources()
    _write_json(root / "corpus.json", {"version": VERSION, "sources": sources,
        "denominator": "all four frozen sources, including unplanned and failed work"})
    reference = _run_arm(root, "reference", sources, concurrency)
    results = []
    for name in selected:
        arm = _run_arm(root, name, sources, concurrency)
        for field in ("occurrences", "expert_evidence"):
            expected, actual = set(reference["evidence"][field]), set(arm["evidence"][field])
            arm[field + "_comparison"] = {"reference": len(expected), "retained": len(expected & actual),
                "missing": sorted(expected - actual), "unexpected": sorted(actual - expected)}
        arm["dispatch_delta_vs_reference"] = arm["provider_dispatches"] - reference["provider_dispatches"]
        arm["evidence_identity_vs_reference"] = arm["evidence"] == reference["evidence"]
        expected_work = {row["logical_request_key"] for row in reference["root_work"]}
        planned_work = {row["logical_request_key"] for row in arm["root_work"]}
        completed_work = {row["logical_request_key"] for row in arm["root_work"] if row["complete"]}
        arm["missing_work"] = {"reference_root_requests": len(expected_work),
            "completed": len(expected_work & completed_work),
            "unplanned": sorted(expected_work - planned_work),
            "incomplete_or_unplanned": sorted(expected_work - completed_work),
            "unit": "frozen source by expert root request; split children count through recursive coverage"}
        _write_json(root / name / "report.json", arm)
        results.append(arm)
    report = {"version": VERSION, "status": "offline_engineering_experiment",
        "simulated_only": True, "provider_billing_exactly_once_claimed": False,
        "concurrency": concurrency, "cache_regime": "isolated_cold_database_per_arm_then_labeled_warm_resume",
        "source_count": len(sources), "reference": reference, "arms": results,
        "limitations": ["Synthetic responses measure persistence/recovery behavior, not extraction quality.",
            "The fake endpoint journal observes dispatches and does not model provider invoices.",
            "Boundary faults stage one real engine request before reopening; scheduler collisions are a separate stress experiment.",
            "Scheduler wait uses a virtual clock; it is not wall-clock throughput or human recovery time.",
            "Snapshot byte identity is assessed within each frozen version; independent snapshots have distinct run IDs and timestamps."]}
    _write_json(root / "report.json", report)
    return report
