"""Crash-boundary accounting without sources, secrets or shared SQLite WAL."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder.dispatch_journal import DispatchJournal, JournalError
from termfinder.store import Store, digest, now


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binding = {"cluster_review_id": "cluster_review_" + "a" * 24,
            "binding_sha256": "a" * 64, "profile_sha256": "b" * 64,
            "configuration_sha256": "c" * 64}
        self.journal = DispatchJournal(self.root / "journal", self.binding,
            submission_id="cluster_job_" + "d" * 32,
            generation="execution_" + "e" * 32, scheduler_job_id="101", max_records=3)
        self.store = Store(self.root / "local" / "project.sqlite3")
        self.job = {"job_id": "job_" + "1" * 24, "source_id": "source_" + "2" * 24,
            "expert": {"id": "broad-a", "model": "a", "stage": "extraction"},
            "model": {"provider": "fixture", "model": "synthetic"},
            "model_key": "model_" + "3" * 24, "start": 0, "end": 40,
            "depth": 0, "parent": None, "max_output_tokens": 512,
            "status": "running", "attempts": 1, "attempt_id": "attempt_" + "4" * 32}
        self.attempt = {"attempt_id": self.job["attempt_id"], "job_id": self.job["job_id"],
            "run_id": "run_" + "5" * 32, "stage": "extraction", "policy_hash": "6" * 64,
            "budget_scope": "simulation:offline-fixture-v1", "reserved_usd": .03,
            "status": "dispatched", "request_count": 1, "created_at": now(), "is_retry": False,
            "billing_kind": "simulated", "invoice_usd": None,
            "invoice_usd_reason": "provider_invoice_not_available"}

    def test_intent_survives_loss_of_node_local_database_and_reconciles_idempotently(self):
        self.journal.intent(self.job, self.attempt)
        first = self.journal.reconcile(self.store)
        self.assertEqual(first["unresolved_attempts"], 1)
        restored = self.store.get("costs", self.attempt["attempt_id"])
        self.assertEqual(restored["status"], "uncertain")
        self.assertEqual(restored["reserved_usd"], .03)
        self.assertEqual(self.store.count("costs"), 1)
        self.journal.reconcile(self.store)
        self.assertEqual(self.store.count("costs"), 1)
        self.store.put("jobs", self.job["job_id"], self.job)
        self.journal.reconcile(self.store)
        self.assertEqual(self.store.get("jobs", self.job["job_id"])["status"], "uncertain")

    def test_terminal_restores_known_usage_but_never_claims_lost_response_or_evidence(self):
        self.journal.intent(self.job, self.attempt)
        settled = dict(self.attempt, status="settled", settled_usd=.02,
            input_tokens=30, output_tokens=20, finished_at=now(), reservation_overrun=False)
        self.journal.terminal(self.job, settled)
        self.store.put("jobs", self.job["job_id"], self.job)
        self.journal.reconcile(self.store)
        self.assertEqual(self.store.get("costs", settled["attempt_id"])["settled_usd"], .02)
        recovered = self.store.get("jobs", self.job["job_id"])
        self.assertEqual(recovered["status"], "uncertain")
        self.assertEqual(recovered["reason"], "cluster_response_missing_from_durable_checkpoint")
        self.assertEqual(self.store.count("cache"), 0)

    def test_checkpoint_with_response_keeps_completed_evidence_and_accounts_missing_terminal(self):
        self.journal.intent(self.job, self.attempt)
        settled = dict(self.attempt, status="settled", settled_usd=.02,
            input_tokens=30, output_tokens=20, finished_at=now(), reservation_overrun=False)
        self.store.put("costs", settled["attempt_id"], settled)
        completed = dict(self.job, status="complete")
        self.store.put("jobs", completed["job_id"], completed)
        self.store.put("cache", completed["job_id"], {"attempt_id": settled["attempt_id"], "response": {}})
        self.journal.reconcile(self.store)
        self.assertEqual(self.store.get("jobs", completed["job_id"])["status"], "complete")
        self.assertEqual(self.store.get("costs", settled["attempt_id"])["status"], "settled")

    def test_duplicate_and_conflicting_identity_never_overwrite_receipt(self):
        self.journal.intent(self.job, self.attempt)
        before = list((self.root / "journal").glob("*.intent.json"))[0].read_bytes()
        self.journal.intent(self.job, self.attempt)
        with self.assertRaises(JournalError):
            self.journal.intent(self.job, dict(self.attempt, reserved_usd=.5))
        self.assertEqual(list((self.root / "journal").glob("*.intent.json"))[0].read_bytes(), before)

    def test_capacity_stops_new_dispatch_without_pruning_unresolved_records(self):
        for index in range(3):
            attempt = dict(self.attempt, attempt_id="attempt_" + format(index, "032x"))
            self.journal.intent(self.job, attempt)
        with self.assertRaises(JournalError):
            self.journal.intent(self.job, dict(self.attempt, attempt_id="attempt_" + "f" * 32))
        self.assertEqual(len(list((self.root / "journal").glob("*.intent.json"))), 3)

    def test_corrupt_or_symlink_receipts_fail_closed_without_echoing_content(self):
        self.journal.intent(self.job, self.attempt)
        path = list((self.root / "journal").glob("*.intent.json"))[0]
        path.write_text('{"unrelated":"synthetic-private-marker"}')
        with self.assertRaises(JournalError) as error:
            self.journal.reconcile(self.store)
        self.assertNotIn("synthetic-private-marker", str(error.exception))
        path.unlink()
        path.symlink_to(self.root / "unrelated")
        with self.assertRaises(JournalError):
            self.journal.reconcile(self.store)

    def test_metadata_has_no_context_prompt_raw_response_or_endpoint_credentials(self):
        self.job["prompt"] = "synthetic-source-marker"
        self.job["model"]["base_url"] = "https://synthetic.invalid/private"
        self.attempt["error"] = "synthetic-private-marker"
        self.journal.intent(self.job, self.attempt)
        data = list((self.root / "journal").glob("*.intent.json"))[0].read_text()
        self.assertNotIn("synthetic-source-marker", data)
        self.assertNotIn("synthetic-private-marker", data)
        self.assertNotIn("synthetic.invalid", data)
        self.assertNotIn("synthetic", json.loads(data)["job"]["model_sha256"])

    def test_fsync_failure_is_visible_and_no_terminal_can_invent_an_intent(self):
        with patch("termfinder.dispatch_journal.os.fsync", side_effect=OSError("synthetic-storage-marker")):
            with self.assertRaises(JournalError) as error:
                self.journal.intent(self.job, self.attempt)
        self.assertNotIn("synthetic-storage-marker", str(error.exception))
        with self.assertRaises(JournalError):
            self.journal.terminal(self.job, dict(self.attempt, status="uncertain", finished_at=now()))

    def test_known_not_sent_terminal_never_invents_execution_or_retry_count(self):
        self.journal.intent(self.job, self.attempt)
        unused = dict(self.attempt, status="not_sent", request_count=0, settled_usd=0,
            finished_at=now())
        self.journal.terminal(self.job, unused)
        pending = dict(self.job, status="pending", attempts=0)
        self.store.put("jobs", pending["job_id"], pending)
        self.journal.reconcile(self.store)
        restored = self.store.get("jobs", pending["job_id"])
        self.assertEqual(restored["status"], "pending")
        self.assertEqual(restored["attempts"], 0)
        self.assertEqual(self.store.get("costs", unused["attempt_id"])["request_count"], 0)

    def test_cumulative_request_time_reservations_survive_loss_and_reconciliation(self):
        timed = dict(self.attempt, reserved_seconds=11.5, time_accounting_version=2)
        self.journal.intent(self.job, timed)
        self.journal.reconcile(self.store)
        restored = self.store.get("costs", timed["attempt_id"])
        self.assertEqual(restored["reserved_seconds"], 11.5)
        self.assertNotIn("settled_seconds", restored)
        settled = dict(timed, status="settled", settled_usd=.02,
            input_tokens=30, output_tokens=20, settled_seconds=2.5, finished_at=now())
        self.journal.terminal(self.job, settled)
        self.journal.reconcile(self.store)
        self.assertEqual(self.store.get("costs", timed["attempt_id"])["settled_seconds"], 2.5)


if __name__ == "__main__":
    unittest.main()
