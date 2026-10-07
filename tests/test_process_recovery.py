"""SIGKILL collector regressions with fresh-process resume; no live providers."""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from termfinder import Project, FakeProvider, Response
import termfinder
from termfinder.config import starter_recipe
from termfinder.sources import parse_document


TEXT = "Crew calls a pause a moonstep."


def response(text):
    return Response(json.dumps({"candidates": [{"expression": "moonstep", "language": "en",
        "sense": "a pause", "context": text, "start": text.index("moonstep"), "attributes": {},
        "definition_quote": None, "translation": None}], "coverage_complete": True}), 30, 20,
        "stop", "recovery-fixture-v1")


OWNER = r'''
import json,sys,time
from pathlib import Path
from termfinder import Project,FakeProvider,Response
from termfinder.engine import Engine
project_path,phase,log_path,ready_path=sys.argv[1:]
class Traced(FakeProvider):
    def complete(self,request):
        with open(log_path,'a') as handle:
            handle.write(request['job_id']+'\n');handle.flush()
        if phase=='dispatch':
            Path(ready_path).write_text(request['job_id'])
            time.sleep(60)
        text=request['text']
        return Response(json.dumps({'candidates':[{'expression':'moonstep','language':'en','sense':'a pause',
            'context':text,'start':text.index('moonstep'),'attributes':{},'definition_quote':None,'translation':None}],
            'coverage_complete':True}),None if phase=='unknown-cache' else 30,
            None if phase=='unknown-cache' else 20,'stop','recovery-fixture-v1')
engine=Engine(Project(project_path),Traced([]))
if phase in {'cache','unknown-cache'}:
    def suspend(job,response,**kwargs):
        Path(ready_path).write_text(job['job_id'])
        time.sleep(60)
    engine.accept=suspend
engine.run(max_jobs=1)
'''


class ProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = Project(self.root / "study")
        recipe = starter_recipe("neologisms")
        recipe["execution"]["concurrency"] = 1
        recipe["execution"]["resilience"].update(min_request_interval_seconds=0,
            automatic_uncertain_retries=False, model_concurrency=1)
        self.project.configure(recipe, "fake")
        self.project.add_source(parse_document(TEXT.encode(), "text/plain", "recovery-source.txt",
            {"language": "en", "community": "Gaming"}))

    def crash(self, phase):
        log, ready = self.root / "calls.txt", self.root / "ready.txt"
        owner = subprocess.Popen([sys.executable, "-c", OWNER, str(self.project.path), phase, str(log), str(ready)],
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(termfinder.__file__).resolve().parent.parent),
                 "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline and owner.poll() is None:
                time.sleep(.01)
            self.assertTrue(ready.exists(), "Collector did not reach the selected durable boundary")
            job_id = ready.read_text()
            owner.kill()
            owner.wait(timeout=2)
            return job_id, log
        finally:
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=2)

    def resumed_provider(self, log):
        class Traced(FakeProvider):
            def complete(self, request):
                with log.open("a") as handle:
                    handle.write(request["job_id"] + "\n")
                return response(request["text"])
        return Traced([])

    def test_crash_after_dispatch_retains_unknown_accounting_without_repeating_job(self):
        job_id, log = self.crash("dispatch")
        fresh = Project(self.project.path)
        fresh.resume(self.resumed_provider(log))
        job = fresh.store.get("jobs", job_id)
        self.assertEqual(job["status"], "uncertain")
        attempt = fresh.store.get("costs", job["attempt_id"])
        self.assertEqual(attempt["status"], "uncertain")
        self.assertEqual(attempt["request_count"], 1)
        self.assertNotIn("settled_usd", attempt)
        self.assertEqual(Counter(log.read_text().splitlines())[job_id], 1)
        self.assertEqual(fresh.status()["status"], "partial")

    def test_crash_after_committed_response_replays_once_and_exports_frozen_records(self):
        job_id, log = self.crash("cache")
        fresh = Project(self.project.path)
        receipt = fresh.store.get("cache", job_id)
        self.assertIsNotNone(receipt)
        fresh.resume(self.resumed_provider(log))
        self.assertEqual(fresh.store.get("jobs", job_id)["status"], "done")
        self.assertEqual(Counter(log.read_text().splitlines())[job_id], 1)
        self.assertEqual(fresh.status()["status"], "complete")
        self.assertEqual(fresh.store.count("occurrences"), 1)
        occurrence = next(fresh.store.iter_rows("occurrences"))
        source = fresh.store.get("sources", occurrence["source_id"])
        self.assertEqual(source["text"][occurrence["start"]:occurrence["end"]], "moonstep")
        version = fresh.snapshot("crash-recovery")
        fresh.export(version, self.root / "export-a", ["jsonl", "csv", "parquet", "annotation"])
        Project(self.project.path).export(version, self.root / "export-b", ["jsonl", "csv", "parquet", "annotation"])
        a = {p.name: p.read_bytes() for p in (self.root / "export-a").iterdir() if p.is_file()}
        b = {p.name: p.read_bytes() for p in (self.root / "export-b").iterdir() if p.is_file()}
        self.assertEqual(a, b)

    def test_unknown_usage_receipt_replays_grounding_without_releasing_reservation(self):
        job_id, log = self.crash("unknown-cache")
        fresh = Project(self.project.path)
        receipt = fresh.store.get("cache", job_id)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["usage_status"], "unknown")
        fresh.resume(self.resumed_provider(log))
        self.assertEqual(Counter(log.read_text().splitlines())[job_id], 1)
        occurrence = next(fresh.store.iter_rows("occurrences"))
        self.assertIn(job_id, [p["job_id"] for p in occurrence["provenance"]])
        job = fresh.store.get("jobs", job_id)
        attempt = fresh.store.get("costs", job["attempt_id"])
        self.assertEqual(attempt["status"], "uncertain")
        self.assertNotIn("settled_usd", attempt)
        self.assertEqual(job["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
