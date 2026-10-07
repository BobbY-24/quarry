"""Finite offline mixed-source stress: concurrent studies, quota, faults, resume.

Run inside the reviewed offline sandbox. These are synthetic engineering
measurements; no model, scheduler, external service or HTTP server is started.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import resource
import statistics
import tempfile
import threading
import time

from termfinder import FakeProvider, Project, Response, __version__
from termfinder.config import load_profile, starter_recipe
from termfinder.engine import Engine
from termfinder.fault_provider import FaultAction, FaultTapeProvider, KeyedFakeProvider, request_fingerprint
from termfinder.providers import ProviderError
from termfinder.quotas import QuotaCoordinator, QuotaLimits
from termfinder.sources import parse_document
from reliability_load import DescriptorSampler, disk_bytes, evidence_digest, open_descriptors


def summary(values):
    if not values:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    values = sorted(values)
    return {"count": len(values), "min": values[0], "median": statistics.median(values),
            "p95": values[min(len(values)-1, int(.95 * len(values)))], "max": values[-1]}


class Trace:
    def __init__(self):
        self.lock = threading.Lock()
        self.events, self.active, self.peak = [], 0, 0

    def wrap(self, provider, study):
        trace = self
        class Measured:
            paid = False
            execution_boundary = "trusted_in_process"
            enforceable_deadline = False
            cache_identity = provider.cache_identity
            fault_tape_sha256 = provider.fault_tape_sha256
            response_tape_sha256 = provider.provider.tape_sha256
            fault_key_scheme = provider.key_scheme
            def complete(self, request):
                started, wall = time.monotonic(), time.time()
                with trace.lock:
                    trace.active += 1
                    trace.peak = max(trace.peak, trace.active)
                reason = None
                try:
                    # Finite variable fixture latency, unrelated to real inference.
                    time.sleep(.002 + int(sha256(request["job_id"].encode()).hexdigest()[:2], 16) % 7 * .001)
                    return provider.complete(request)
                except ProviderError as error:
                    reason = error.reason
                    raise
                finally:
                    with trace.lock:
                        trace.active -= 1
                        trace.events.append({"study": study, "job_id": request["job_id"],
                            "attempt_number": request["attempt_number"], "expert": request["expert"]["id"],
                            "started": started, "wall_started": wall, "finished": time.monotonic(),
                            "failure_reason": reason})
        return Measured()


def fixtures(count, root):
    package = root / "src" / "termfinder" / "fixtures"
    expectations = json.loads((package / "expectations.json").read_text())
    for item in expectations:
        item.pop("expert_ids", None)
        item.pop("recipe_ids", None)
    extra = [
        {"expression": "月步", "language": "zh", "sense": "a fictional pause", "context": "社群把短暂停顿称为月步。"},
        {"expression": "قفزةقمرية", "language": "ar", "sense": "a fictional pause", "context": "يسمي الفريق هذا التوقف قفزةقمرية."},
    ]
    expectations.extend(extra)
    html = '<h1>Fictional community</h1><p>Players call a last-second escape a moonstep; the timing window closes before the landing animation.</p><table><tr><th>Label</th><td>ordinary text</td></tr></table>'
    markdown = "## مفردات خيالية\n" + extra[1]["context"]
    chinese = extra[0]["context"] + "\n社群里没有其他术语。"
    long_context = next(item["context"] for item in expectations if item["expression"] == "anchor")
    long_text = "Ordinary filler sentence. " * 400 + long_context + "\n" + "Ordinary filler sentence. " * 400
    forms = [(html.encode(), "text/html", "html", "en", "community"),
             (markdown.encode(), "text/markdown", "markdown", "ar", "cultural"),
             (chinese.encode(), "text/plain", "text", "zh", "cultural"),
             (long_text.encode(), "text/plain", "long-text", "en", "community"),
             ((package / "jargon.pdf").read_bytes(), "application/pdf", "pdf", "en", "medical")]
    documents = []
    for index in range(count):
        raw, mime, kind, language, domain = forms[index % len(forms)]
        source = parse_document(raw, mime, f"mixed-fixture-{index}.{kind}", {
            "language": language, "community": "synthetic-mixed", "domain": domain,
            "constraints": {"content_origin": "synthetic_fixture"}})
        documents.append(source)
    return documents, expectations


def recipe(mode):
    value = starter_recipe("jargon")
    value["languages"] = ["en", "ar", "zh", "ja", "hi"]
    value["communities"] = ["synthetic-mixed"]
    value["mode"] = mode
    for lens in value["specialist_lenses"]:
        lens["communities"] = ["*"]
    value["execution"].update(concurrency=4, timeout_seconds=1, deadline_seconds=3600,
        max_calls=4000, max_output_tokens=1024, recovery_output_tokens=2048)
    value["execution"]["resilience"].update(model_concurrency=2, min_request_interval_seconds=0,
        delays_seconds=[.005, .01, .02], jitter_fraction=0, automatic_uncertain_retries=False)
    return value


def build_provider(project, expectations, trace, label, unknown=False):
    base = FakeProvider(expectations)
    planning = Project(project.path.parent / ("plan-" + label))
    planning.configure(project.recipe, project.profile)
    for source in project.store.iter_rows("sources"):
        planning.add_source(source)
    planner = Engine(planning, base)
    jobs = [planning.store.get("jobs", key) for key in planner.prepare()]
    requests = [planner.request(job) for job in jobs]
    # Prefer long windows for truncation; smaller recovery windows use the
    # deterministic fixture fallback. Request keys avoid tape/cache-ID cycles.
    long = next(request for request in requests if len(request["text"]) > 2000)
    short = [request for request in requests if len(request["text"]) < 500]
    truncation = Response('{"candidates":[', 30, 10, "length", "mixed-fixture-v1")
    scripted = {(request_fingerprint(long), 1): truncation}
    fault_tape = {
        (request_fingerprint(short[0]), 1): ProviderError("http_422", failure_scope="request"),
        (request_fingerprint(short[1]), 1): ProviderError("http_429", retryable=True,
            retry_after_seconds=.005, failure_scope="provider"),
        (request_fingerprint(short[2]), 1): FaultAction(delay_seconds=.02),
    }
    if unknown:
        scripted[(request_fingerprint(short[3]), 1)] = Response(base.complete(short[3]).text, None, None,
            "stop", "mixed-fixture-v1")
    provider = KeyedFakeProvider(scripted, key_scheme="request", fallback_provider=base)
    return trace.wrap(FaultTapeProvider(provider, fault_tape, key_scheme="request"), label)


def run(count, output):
    root = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    initial_usage = resource.getrusage(resource.RUSAGE_SELF)
    initial_fds = open_descriptors()
    timings, trace = {}, Trace()
    with tempfile.TemporaryDirectory(prefix="quarry-mixed-") as directory, DescriptorSampler() as fds:
        directory = Path(directory)
        phase = time.monotonic()
        documents, expectations = fixtures(count, root)
        timings["parse_mixed_sources_seconds"] = time.monotonic() - phase
        profile = load_profile("fake")
        for model in profile["models"].values():
            model.update(input_per_million=.001, output_per_million=.001,
                price_note="Synthetic stress-accounting rates; no provider or GPU fees.")
        projects = [Project(directory / name) for name in ("broad", "specialists")]
        limits = QuotaLimits(max_inflight=2, requests_per_window=1000, tokens_per_window=1000000,
            window_seconds=.05, retry_requests_per_window=100, retry_window_seconds=.05,
            max_queue=32, max_queue_per_study=16, lease_seconds=10, max_history=4000)
        registry = directory / "quota.sqlite3"
        for project, mode in zip(projects, ("broad", "specialists")):
            project.configure(recipe(mode), profile)
            for document in documents:
                project.add_source(deepcopy(document))
            project.configure_quota(registry, "synthetic-mixed-account", limits)
        providers = [build_provider(project, expectations, trace, label, unknown=label == "specialists")
                     for project, label in zip(projects, ("broad", "specialists"))]
        def progress(phase, failure=None):
            # Save bounded partial diagnostics before any enclosing executor
            # cleanup can wait. Retain this file if the outer sandbox kills us.
            value = {"schema_version": 1, "synthetic_only": True, "paid_requests": 0,
                "completed": False, "phase": phase, "source_count": count,
                "failure_category": type(failure).__name__ if failure is not None else None,
                "elapsed_seconds": time.monotonic()-started, "completed_fixture_calls": len(trace.events),
                "active_fixture_calls": trace.active, "timings": timings,
                "projects": [{"name": project.path.name, "status": project.status(),
                    "attempt_statuses": dict(Counter(row["status"] for row in project.store.iter_rows("costs")))}
                    for project in projects], "recent_calls": trace.events[-32:],
                "note": "Partial engineering diagnostics, not a successful stress result; all inputs/calls synthetic."}
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(output.name+".tmp")
            temporary.write_text(json.dumps(value, sort_keys=True, indent=2)+"\n")
            temporary.replace(output)
        progress("configured")
        inspection = {"samples": 0, "max_bytes": 0, "latencies_seconds": [], "errors": 0}
        stop_inspection = threading.Event()
        def inspect():
            while not stop_inspection.is_set():
                phase = time.monotonic()
                try:
                    page = Project(projects[0].path).page_inventory(limit=20)
                    inspection["max_bytes"] = max(inspection["max_bytes"], len(json.dumps(page).encode()))
                    inspection["samples"] += 1
                    inspection["latencies_seconds"].append(time.monotonic()-phase)
                except BaseException:
                    inspection["errors"] += 1
                stop_inspection.wait(.02)
        inspector = threading.Thread(target=inspect, daemon=True)
        inspector.start()
        phase = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(project.collect, provider) for project, provider in zip(projects, providers)]
                # The first concurrent phase deliberately cancels Broad. Its
                # committed responses must be drained before returning.
                until = time.monotonic() + 2
                while len(trace.events) < 10 and time.monotonic() < until:
                    time.sleep(.005)
                cancel_started = time.monotonic()
                projects[0].cancel()
                try:
                    futures[0].result(timeout=120)
                except BaseException as failure:
                    progress("cancel_phase_failed", failure)
                    raise
                timings["cancel_to_drained_return_seconds"] = time.monotonic()-cancel_started
                checkpoint = time.monotonic()
                projects[0].store.backup(directory / "cancelled-checkpoint.sqlite3")
                timings["local_checkpoint_seconds"] = time.monotonic()-checkpoint
                try:
                    futures[1].result(timeout=120)
                except BaseException as failure:
                    progress("concurrent_phase_failed", failure)
                    raise
        finally:
            stop_inspection.set()
            inspector.join(timeout=2)
        timings["concurrent_cancelled_phase_seconds"] = time.monotonic()-phase
        progress("concurrent_phase_finished")
        phase = time.monotonic()
        resumed = [Project(project.path) for project in projects]
        resume_rounds = []
        resume_until = time.monotonic()+120
        for round_number in range(32):
            before = len(trace.events)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(project.resume, provider) for project, provider in zip(resumed, providers)]
                try:
                    results = [future.result(timeout=120) for future in futures]
                except BaseException as failure:
                    progress("resume_phase_failed", failure)
                    raise
            resume_rounds.append({"round": round_number+1, "new_calls": len(trace.events)-before,
                "stop_reasons": [value["stop_reason"] for value in results]})
            progress("resume_round_finished")
            transient = any(str(value["stop_reason"]).startswith("quota_") for value in results)
            if not transient:
                break
            if time.monotonic() >= resume_until:
                progress("resume_time_allowance_exhausted")
                raise AssertionError("Mixed stress exhausted its finite quota-resume time allowance")
            time.sleep(.01)
        else:
            progress("resume_round_allowance_exhausted")
            raise AssertionError("Mixed stress exhausted its finite quota-resume round allowance")
        timings["resume_seconds"] = time.monotonic()-phase
        calls_before = len(trace.events)
        for project, provider in zip(resumed, providers):
            project.resume(provider)
        completed_repeat = len(trace.events)-calls_before
        assert completed_repeat == 0, json.dumps({"error": "completed_repeat_made_calls", "calls": completed_repeat,
            "before": [{"jobs": value["jobs"], "stop_reason": value["stop_reason"]} for value in results],
            "after": [{"jobs": project.status()["jobs"], "stop_reason": project.status()["stop_reason"]} for project in resumed]}, sort_keys=True)
        assert trace.peak <= limits.max_inflight, "Shared account admitted too many simultaneous calls"
        assert inspection["samples"] and not inspection["errors"], "Concurrent paginated inspection failed"
        evidence = [evidence_digest(project) for project in resumed]
        # Counterfactual uses an independent fresh project, same frozen corpus
        # and policy. It has no reusable extraction cache or fault schedule.
        healthy = Project(directory / "healthy-counterfactual")
        healthy.configure(recipe("specialists"), profile)
        for document in documents:
            healthy.add_source(deepcopy(document))
        healthy.collect(FakeProvider(expectations))
        canonical = evidence_digest(healthy)
        assert all(value == canonical for value in evidence), "Grounded inventory differs from healthy counterfactual"
        phase = time.monotonic()
        frozen = []
        for index, project in enumerate(resumed):
            version = project.snapshot("mixed-stress-v1")
            a, b = directory / f"export-{index}-a", directory / f"export-{index}-b"
            project.export(version, a, ["csv", "jsonl", "parquet", "annotation"])
            Project(project.path).export(version, b, ["csv", "jsonl", "parquet", "annotation"])
            hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in a.iterdir() if p.is_file()}
            assert hashes == {p.name: sha256(p.read_bytes()).hexdigest() for p in b.iterdir() if p.is_file()}
            frozen.append({"byte_identical": True, "sha256": hashes})
        timings["frozen_exports_seconds"] = time.monotonic()-phase
        coordinator = QuotaCoordinator(registry, "synthetic-mixed-account", limits)
        quota = coordinator.diagnostics()
        assert quota["states"].get("uncertain", 0) == 1, "Unknown usage lease was lost or silently released"
        attempts = [row for project in resumed for row in project.store.iter_rows("costs")]
        assert any(row["status"] == "uncertain" and row["reserved_usd"] > 0 for row in attempts)
        queue_durations = []
        starts = {(event["study"], event["job_id"]): event["wall_started"] for event in reversed(trace.events)}
        for label, project in zip(("broad", "specialists"), resumed):
            for job in project.store.iter_rows("jobs"):
                if job.get("capacity_wait_started") and (label, job["job_id"]) in starts:
                    queue_durations.append(max(0, starts[label, job["job_id"]]-datetime.fromisoformat(job["capacity_wait_started"]).timestamp()))
        grouped = {}
        for event in sorted(trace.events, key=lambda event: event["started"]):
            grouped.setdefault((event["study"], event["job_id"]), []).append(event)
        retry_gaps = [items[i]["started"]-items[i-1]["finished"] for items in grouped.values()
                      for i in range(1, len(items)) if items[i]["attempt_number"] > items[i-1]["attempt_number"]]
        usage = resource.getrusage(resource.RUSAGE_SELF)
        result = {"schema_version": 1, "completed": True, "synthetic_only": True, "paid_requests": 0, "source_count": count,
            "formats": dict(Counter(document["media_type"] for document in documents)),
            "languages": dict(Counter(document.get("language") for document in documents)),
            "source_characters": summary([len(document["text"]) for document in documents]),
            "pdf_pages": sum(document.get("parser_info", {}).get("pages", 0) for document in documents),
            "modes": ["broad", "specialists"], "independent_concurrent_studies": 2,
            "software_version": __version__, "fault_tapes": [{"study": label,
                "response_tape_sha256": provider.response_tape_sha256,
                "runtime_fault_tape_sha256": provider.fault_tape_sha256,
                "key_scheme": provider.fault_key_scheme, "cache_identity": provider.cache_identity}
                for label, provider in zip(("broad", "specialists"), providers)],
            "faults": {"request_rejection": "http_422", "known_rejection_retry": "http_429",
                "truncation": "length + malformed JSON recovered with smaller windows",
                "unknown_usage": "one source-supported response with missing token counts",
                "delays": "2–8 ms variable fixture latency plus one 20 ms tape delay",
                "fault_key_scheme": "request fingerprint and attempt number"},
            "requests": len(trace.events), "attempt_statuses": dict(Counter(row["status"] for row in attempts)),
            "completed_repeat_extra_calls": completed_repeat, "quota": quota,
            "bounded_concurrent_resume_rounds": resume_rounds,
            "maximum_simultaneous_fixture_calls": trace.peak, "canonical_evidence": canonical,
            "fault_inventory_matches_fresh_healthy_counterfactual": True, "frozen_exports": frozen,
            "paginated_inspection": {"samples": inspection["samples"], "errors": inspection["errors"],
                "maximum_payload_bytes": inspection["max_bytes"], "latency_seconds": summary(inspection["latencies_seconds"]),
                "scope": "direct browser-data pagination while collecting; no HTTP/browser throughput measurement"},
            "request_latency_seconds": summary([event["finished"]-event["started"] for event in trace.events]),
            "first_capacity_wait_to_dispatch_seconds": summary(queue_durations),
            "retry_inter_attempt_gap_seconds": summary(retry_gaps),
            "timings": timings, "elapsed_seconds": time.monotonic()-started,
            "resources": {"peak_process_rss_platform_units": usage.ru_maxrss,
                "rss_units": "bytes on macOS; KiB on Linux", "user_cpu_seconds": usage.ru_utime-initial_usage.ru_utime,
                "system_cpu_seconds": usage.ru_stime-initial_usage.ru_stime,
                "fd_before": initial_fds, "fd_after": open_descriptors(), "fd_sampled_peak": fds.peak,
                "fd_sampling_seconds": .02, "disk_bytes_after_all_exports": disk_bytes(directory)},
            "cost_note": "All token rates/fees are synthetic accounting fixtures; real API and GT costs are unknown and unmeasured.",
            "limitations": "No real inference, scheduler/preemption, multihost registry, external HTTP or GPU stress; in-process fake delays are trusted and finite."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=int, default=120)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not 10 <= args.sources <= 120 or not args.report.resolve().is_relative_to(root / "verification"):
        parser.error("Use 10–120 synthetic sources and a report inside verification/")
    result = run(args.sources, args.report)
    print(json.dumps({key: result[key] for key in ("synthetic_only", "paid_requests", "source_count", "requests",
        "attempt_statuses", "maximum_simultaneous_fixture_calls", "completed_repeat_extra_calls",
        "canonical_evidence", "fault_inventory_matches_fresh_healthy_counterfactual", "resources", "timings",
        "elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
