"""Known pre-submit failures cannot retain a live owner's account capacity."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from termfinder import FakeProvider, Project
from termfinder.config import starter_recipe
from termfinder.engine import Engine
from termfinder.quotas import QuotaLimits
from termfinder.sources import parse_document


class AdmissionFailureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = Project(root / "study")
        recipe = starter_recipe("neologisms")
        recipe["execution"]["resilience"]["min_request_interval_seconds"] = 0
        self.project.configure(recipe, "fake")
        self.project.configure_quota(root / "quota.sqlite3", "fixture-account",
            QuotaLimits(max_inflight=1, requests_per_window=1000,
                tokens_per_window=1000000))
        self.project.add_source(parse_document(b"The crew calls a pause a moonstep.",
            "text/plain", "fixture.txt", {"language": "en", "community": "Gaming"}))

    def prepared(self):
        provider = FakeProvider([])
        engine = Engine(self.project, provider)
        job = self.project.store.get("jobs", engine.prepare()[0])
        return engine, provider, job

    def test_health_write_failure_releases_known_uninvoked_reservation(self):
        engine, provider, job = self.prepared()
        with patch.object(engine, "_save_health", side_effect=OSError("fixture health write failed")):
            with self.assertRaises(OSError):
                engine.admit(job)
        attempt = self.project.store.all("costs")[0]
        self.assertEqual(attempt["status"], "not_sent")
        self.assertEqual(attempt["request_count"], 0)
        self.assertEqual(attempt["settled_usd"], 0)
        self.assertEqual(attempt["settled_seconds"], 0)
        saved_job = self.project.store.get("jobs", job["job_id"])
        self.assertEqual(saved_job["status"], "pending")
        self.assertEqual(saved_job["attempts"], 0)
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        self.assertEqual(engine._ledger()["calls"], 0)
        self.assertEqual(engine._ledger()["request_seconds"], 0)
        self.assertFalse(provider.calls)

    def test_run_reports_partial_then_same_process_resume_uses_freed_capacity(self):
        provider = FakeProvider([])
        engine = Engine(self.project, provider)
        original = engine._save_health
        failures = []

        def fail_after_reservation():
            if engine.ledger and engine.ledger["calls"] and not failures:
                failures.append(True)
                raise RuntimeError("fixture health update failed before submit")
            return original()

        with patch.object(engine, "_save_health", side_effect=fail_after_reservation):
            result = engine.run()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(provider.calls)
        self.assertFalse(any(job["status"] == "running" for job in self.project.store.all("jobs")))
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        self.assertEqual(self.project.store.all("costs")[0]["status"], "not_sent")
        resumed = self.project.resume(provider)
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(len(provider.calls), 2)

    def test_unavailable_local_settlement_still_frees_proven_uninvoked_quota(self):
        engine, provider, job = self.prepared()
        original = self.project.store.put

        def reject_not_sent_commit(table, key, value, *args, **kwargs):
            if table == "costs" and value.get("status") == "not_sent":
                raise sqlite3.OperationalError("fixture local settlement unavailable")
            return original(table, key, value, *args, **kwargs)

        with patch.object(engine, "_save_health", side_effect=OSError("fixture health write failed")), \
                patch.object(self.project.store, "put", side_effect=reject_not_sent_commit):
            with self.assertRaises((OSError, sqlite3.Error)):
                engine.admit(job)
        self.assertFalse(provider.calls)
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        # The disk failure cannot erase the last durable accounting reservation.
        self.assertEqual(self.project.store.all("costs")[0]["status"], "dispatched")


if __name__ == "__main__":
    unittest.main()
