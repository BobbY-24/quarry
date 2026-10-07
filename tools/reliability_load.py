"""Bounded synthetic source/resume/cache/export rehearsal; run inside isolation.

This measures local software scaling, not real providers, GPUs or extraction
quality. It performs no paid calls, scheduler operations or network requests.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import resource
import sys
import tempfile
import threading
import time

from termfinder import Project, FakeProvider
from termfinder.config import starter_recipe
from termfinder.sources import parse_document
from termfinder.engine import SourceCache


def open_descriptors():
    """Count only this process's descriptors; never inspect their contents."""
    folder = Path("/proc/self/fd") if sys.platform.startswith("linux") else Path("/dev/fd")
    try:
        return sum(1 for _ in folder.iterdir())
    except OSError:
        return None


class DescriptorSampler:
    def __init__(self):
        self.stop = threading.Event()
        self.samples, self.peak = 0, None
        self.thread = threading.Thread(target=self.sample, name="quarry-offline-fd-sampler", daemon=True)

    def sample(self):
        while not self.stop.is_set():
            value = open_descriptors()
            if value is not None:
                self.samples += 1
                self.peak = value if self.peak is None else max(self.peak, value)
            self.stop.wait(.02)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *unused):
        self.stop.set()
        self.thread.join(timeout=1)


def disk_bytes(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def evidence_digest(project):
    """Verify every observed span and hash a stable source/evidence projection."""
    sources = SourceCache(project.store)
    hasher = sha256()
    count = 0
    for occurrence in project.store.iter_rows("occurrences"):
        source = sources[occurrence["source_id"]]
        observed = source["text"][occurrence["start"]:occurrence["end"]]
        if observed != occurrence["expression"]:
            raise AssertionError("Evidence offsets do not reproduce the observed expression")
        if sha256(source["text"].encode()).hexdigest() != source["text_sha256"]:
            raise AssertionError("Stored source hash differs from its text")
        projection = {k: occurrence[k] for k in ("occurrence_id", "source_id", "term_id", "expression", "start", "end")}
        projection["text_sha256"] = source["text_sha256"]
        hasher.update(json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
        hasher.update(b"\n")
        count += 1
    return {"occurrences": count, "source_span_checks": count, "canonical_sha256": hasher.hexdigest(),
            "projection": "occurrence/source/term IDs, observed expression, exact Unicode start/end, source text hash"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=int, default=1000)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.sources <= 5000:
        parser.error("Use 1–5000 synthetic sources under the outer finite CPU/wall bounds")
    root = Path(__file__).resolve().parents[1]
    if not args.report.resolve().is_relative_to(root / "verification"):
        parser.error("Report must stay inside verification/")
    started = time.monotonic()
    initial_usage = resource.getrusage(resource.RUSAGE_SELF)
    initial_fds = open_descriptors()
    timings = {}
    context = "This fictional community calls a pause moonstep."
    provider = FakeProvider([{"expression": "moonstep", "language": "en", "sense": "a pause",
                              "context": context, "attributes": {}, "definition_quote": None, "translation": None}])
    with DescriptorSampler() as descriptor_samples, tempfile.TemporaryDirectory(prefix="quarry-reliability-load-") as temporary:
        project = Project(Path(temporary) / "study")
        recipe = starter_recipe("neologisms")
        recipe["execution"]["resilience"]["min_request_interval_seconds"] = 0
        recipe["execution"]["max_calls"] = 50_000
        project.configure(recipe, "fake")
        phase = time.monotonic()
        for index in range(args.sources):
            text = f"Synthetic source {index}. {context}\n" + "Ordinary filler sentence. " * 50
            project.add_source(parse_document(text.encode(), "text/plain", f"source-{index}.txt",
                {"language": "en", "community": "Gaming", "domain": "synthetic-load",
                 "constraints": {"content_origin": "synthetic_fixture"}}))
        timings["ingestion_seconds"] = time.monotonic() - phase
        disk_samples = {"ingestion": disk_bytes(Path(temporary))}
        phase = time.monotonic()
        interrupted = project.collect(provider, max_jobs=min(20, args.sources))
        assert interrupted["jobs"].get("pending", 0) > 0
        project = Project(project.path)
        complete = project.resume(provider)
        assert complete["coverage"]["partial"] == 0
        calls = len(provider.calls)
        project.resume(provider)
        assert len(provider.calls) == calls
        timings["interruption_resume_cache_seconds"] = time.monotonic() - phase
        disk_samples["resume"] = disk_bytes(Path(temporary))
        phase = time.monotonic()
        exact_evidence = evidence_digest(project)
        assert exact_evidence["occurrences"] == args.sources
        assert evidence_digest(Project(project.path)) == exact_evidence
        timings["canonical_evidence_verification_seconds"] = time.monotonic() - phase
        phase = time.monotonic()
        page = project.page_inventory()
        page_size = len(json.dumps(page, ensure_ascii=False).encode())
        assert len(page["records"]) <= 50
        timings["bounded_inventory_page_seconds"] = time.monotonic() - phase
        phase = time.monotonic()
        version = project.snapshot("synthetic-reliability-load-v1")
        first, second = Path(temporary) / "first", Path(temporary) / "second"
        formats = ["csv", "jsonl", "parquet", "annotation"]
        project.export(version, first, formats); project.export(version, second, list(reversed(formats)))
        hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in first.iterdir() if path.is_file()}
        assert hashes == {path.name: sha256(path.read_bytes()).hexdigest() for path in second.iterdir() if path.is_file()}
        timings["snapshot_and_frozen_exports_seconds"] = time.monotonic() - phase
        disk_samples["exports"] = disk_bytes(Path(temporary))
        final_usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_rss_bytes = final_usage.ru_maxrss if sys.platform == "darwin" else final_usage.ru_maxrss * 1024
        result = {"schema_version": 1, "synthetic_only": True, "paid_requests": 0, "source_count": args.sources,
                  "initial_stop_reason": interrupted["stop_reason"], "final_coverage": complete["coverage"],
                  "requests": calls, "completed_resume_extra_calls": len(provider.calls) - calls,
                  "frozen_exports_byte_identical": True, "frozen_export_sha256": hashes,
                  "inventory_page_bytes": page_size, "database_bytes": project.store.path.stat().st_size,
                  "canonical_evidence": exact_evidence, "costs": complete["costs"],
                  "resources": {"peak_process_rss_bytes": peak_rss_bytes,
                     "process_user_cpu_seconds": final_usage.ru_utime - initial_usage.ru_utime,
                     "process_system_cpu_seconds": final_usage.ru_stime - initial_usage.ru_stime,
                     "open_descriptors_before": initial_fds, "open_descriptors_after": open_descriptors(),
                     "peak_open_descriptors_sampled": descriptor_samples.peak,
                     "descriptor_samples": descriptor_samples.samples, "descriptor_sampling_seconds": .02,
                     "disk_phase_bytes": disk_samples, "maximum_measured_disk_bytes": max(disk_samples.values()),
                     "measurement_scope": "collector process including Python/Arrow threads; synthetic provider has no inference subprocesses; FD peak sampled and disk peak measured at phase boundaries"},
                  "timings": timings, "elapsed_seconds": time.monotonic() - started,
                  "peak_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "rss_units": "bytes on macOS; KiB on Linux",
                  "limitations": "Synthetic latency, source text and responses; no provider/GT throughput or measured extraction quality."}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("synthetic_only", "paid_requests", "source_count", "requests",
        "completed_resume_extra_calls", "frozen_exports_byte_identical", "canonical_evidence", "resources",
        "timings", "elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
