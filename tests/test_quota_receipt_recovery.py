"""Replay durable local terminal proof without inference or lost capacity."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import FakeProvider, Project
from termfinder.config import starter_recipe
from termfinder.engine import Engine
from termfinder.providers import ProviderError
from termfinder.quotas import QuotaLimits
from termfinder.sources import parse_document


class QuotaReceiptRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = Project(root / "study")
        recipe = starter_recipe("neologisms")
        recipe["execution"]["resilience"].update(min_request_interval_seconds=0,
            automatic_uncertain_retries=False)
        self.project.configure(recipe, "fake")
        self.project.configure_quota(root / "quota.sqlite3", "fixture-account",
            QuotaLimits(max_inflight=1, requests_per_window=1000, tokens_per_window=1000000))
        self.project.add_source(parse_document(b"The crew calls a pause a moonstep.",
            "text/plain", "fixture.txt", {"language": "en", "community": "Gaming"}))

    def prepared(self, provider=None):
        provider = provider or FakeProvider([])
        engine = Engine(self.project, provider)
        job = self.project.store.get("jobs", engine.prepare()[0])
        attempt, reason = engine.admit(job)
        self.assertIsNone(reason)
        self.assertIsNotNone(attempt)
        return engine, provider, job, attempt

    def settle_without_quota_receipt(self):
        engine, provider, job, attempt = self.prepared()
        response = engine._invoke(engine.request(job), attempt)
        with patch.object(engine.quota, "release", side_effect=RuntimeError("fixture registry temporarily busy")):
            result = engine.settle(job, attempt, response)
        self.assertEqual(result, "local_accounting_receipt_failure")
        self.assertEqual(self.project.store.get("costs", attempt["attempt_id"])["status"], "settled")
        self.assertEqual(engine.quota.diagnostics()["inflight"], 1)
        return engine, provider, job, attempt

    def test_lost_terminal_release_resumes_without_repeating_completed_inference(self):
        engine, provider, job, attempt = self.settle_without_quota_receipt()
        resumed = self.project.resume(provider)
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls.count(job["job_id"]), 1)
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)

    def test_terminal_release_failure_keeps_lease_available_in_engine(self):
        engine, _, _, attempt = self.settle_without_quota_receipt()
        self.assertIn(attempt["attempt_id"], engine.quota_leases)

    def test_known_completion_resolves_uncertain_registry_using_local_receipt(self):
        engine, provider, _, attempt = self.settle_without_quota_receipt()
        lease = engine.quota.lease(attempt["quota_lease_id"])
        engine.quota.release(lease, outcome="uncertain")
        recovered = Engine(self.project, provider)
        recovered.prepare()
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        self.assertEqual(len(provider.calls), 1)

    def test_not_sent_receipt_frees_reserved_capacity_after_lost_release(self):
        engine, provider, job, attempt = self.prepared()
        with patch.object(engine.quota, "release", side_effect=RuntimeError("fixture registry temporarily busy")):
            with self.assertRaises(RuntimeError):
                engine.not_sent(job, attempt, "fixture_not_invoked")
        self.assertEqual(self.project.store.get("costs", attempt["attempt_id"])["status"], "not_sent")
        Engine(self.project, provider).prepare()
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        self.assertFalse(provider.calls)

    def test_rejected_terminal_receipt_frees_capacity_without_fabricated_response(self):
        engine, provider, job, attempt = self.prepared()
        engine.quota.mark_dispatched(engine.quota_leases[attempt["attempt_id"]])
        with patch.object(engine.quota, "release", side_effect=RuntimeError("fixture registry temporarily busy")):
            with self.assertRaises(RuntimeError):
                engine.failure(job, attempt, ProviderError("http_422", uncertain=False, retryable=False))
        Engine(self.project, provider).prepare()
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        self.assertIsNone(self.project.store.get("cache", job["job_id"]))
        self.assertEqual(self.project.store.get("costs", attempt["attempt_id"])["status"], "rejected")

    def test_actual_rejection_finalization_failure_preserves_terminal_proof(self):
        provider = FakeProvider([], [ProviderError("http_422", uncertain=False, retryable=False)])
        engine = Engine(self.project, provider)
        with patch.object(engine.quota, "release", side_effect=RuntimeError("fixture registry temporarily busy")):
            result = engine.run(max_jobs=1)
        self.assertEqual(result["status"], "partial")
        attempt = self.project.store.all("costs")[0]
        self.assertEqual(attempt["status"], "rejected")
        self.assertEqual(engine.quota.diagnostics()["inflight"], 1)
        Engine(self.project, provider).prepare()
        self.assertEqual(engine.quota.diagnostics()["inflight"], 0)
        self.assertEqual(len(provider.calls), 1)

    def test_unknown_execution_and_usage_are_never_automatically_resolved(self):
        engine, provider, job, attempt = self.prepared()
        engine.quota.mark_dispatched(engine.quota_leases[attempt["attempt_id"]])
        engine.failure(job, attempt, ProviderError("accepted_response_lost", uncertain=True, retryable=False))
        Engine(self.project, provider).prepare()
        self.assertEqual(engine.quota.diagnostics()["inflight"], 1)
        self.assertEqual(self.project.store.get("costs", attempt["attempt_id"])["status"], "uncertain")
        self.assertFalse(provider.calls)

    def test_foreign_study_binding_cannot_be_released_by_copied_local_cost(self):
        engine, provider, job, attempt = self.prepared()
        own_lease = engine.quota_leases[attempt["attempt_id"]]
        engine.not_sent(job, attempt, "fixture_not_invoked")
        foreign = engine.quota.try_acquire("other-study", "other-job", "other-attempt", 10).lease
        self.assertIsNotNone(foreign)
        attempt.update(status="settled", settled_usd=0, input_tokens=1, output_tokens=1,
            quota_lease_id=foreign.lease_id)
        self.project.store.put("costs", attempt["attempt_id"], attempt)
        with self.assertRaises((ValueError, RuntimeError)):
            Engine(self.project, provider).prepare()
        self.assertEqual(engine.quota.diagnostics()["inflight"], 1)
        self.assertEqual(engine.quota.lease(foreign.lease_id), foreign)
        self.assertNotEqual(own_lease.lease_id, foreign.lease_id)

    def test_reconciliation_work_limit_blocks_admission_and_preserves_progress(self):
        engine, provider, job, attempt = self.prepared()
        engine.not_sent(job, attempt, "fixture_not_invoked")
        second = next(saved for saved in self.project.store.all("jobs") if saved["job_id"] != job["job_id"])
        attempt, reason = engine.admit(second)
        self.assertIsNone(reason)
        engine.not_sent(second, attempt, "fixture_not_invoked")
        recovered = Engine(self.project, provider)
        recovered.deadline = recovered.clock.monotonic() + 30
        with patch("termfinder.engine.MAX_PLANNED_JOBS", 1):
            recovered.reconcile_quota_receipts()
        self.assertFalse(recovered.quota_reconciliation_complete)
        self.assertEqual(sum(bool(row.get("quota_receipt_version")) for row in self.project.store.all("costs")), 1)
        admitted, reason = recovered.admit(job)
        self.assertIsNone(admitted)
        self.assertEqual(reason, "quota_receipt_reconciliation_pending")
        self.assertFalse(provider.calls)
        recovered.reconcile_quota_receipts()
        self.assertTrue(recovered.quota_reconciliation_complete)
        self.assertEqual(sum(bool(row.get("quota_receipt_version")) for row in self.project.store.all("costs")), 2)

    def test_pruned_known_terminal_lease_needs_no_inference_or_capacity(self):
        engine, provider, job, attempt = self.prepared()
        first_lease_id = attempt["quota_lease_id"]
        engine.not_sent(job, attempt, "fixture_not_invoked")
        second = next(saved for saved in self.project.store.all("jobs") if saved["job_id"] != job["job_id"])
        attempt, reason = engine.admit(second)
        self.assertIsNone(reason)
        engine.not_sent(second, attempt, "fixture_not_invoked")
        self.project.configure_quota(engine.quota.path, "fixture-account",
            QuotaLimits(max_inflight=1, requests_per_window=1000, tokens_per_window=1000000,
                max_history=1))
        self.project._quota_coordinator.diagnostics()
        self.assertIsNone(self.project._quota_coordinator.lease(first_lease_id))
        Engine(self.project, provider).prepare()
        self.assertEqual(self.project._quota_coordinator.diagnostics()["inflight"], 0)
        self.assertFalse(provider.calls)


if __name__ == "__main__":
    unittest.main()
