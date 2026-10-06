"""Request-keyed comparative recovery checks; entirely synthetic and offline."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from termfinder.fault_experiments import (RequestKeyedProvider, SCENARIOS,
    fixture_sources, logical_request_key, logical_response, run_fault_suite)
from termfinder.providers import ProviderError


class FaultExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.report = run_fault_suite(cls.root / "suite", concurrency=2)
        cls.arms = {arm["arm"]: arm for arm in cls.report["arms"]}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_suite_uses_real_engine_fresh_projects_and_full_source_denominator(self):
        report = self.report
        self.assertEqual(report["source_count"], 4)
        self.assertEqual(report["reference"]["provider_dispatches"], 8)
        self.assertEqual(len(report["reference"]["evidence"]["occurrences"]), 4)
        self.assertEqual(len(report["reference"]["evidence"]["expert_evidence"]), 8)
        self.assertEqual(set(self.arms), set(SCENARIOS))
        for arm in (report["reference"], *report["arms"]):
            database = self.root / "suite" / arm["arm"] / "project" / "project.sqlite3"
            self.assertTrue(database.is_file())
            self.assertTrue(arm["simulated_only"])
            self.assertFalse(any(event["billing_observed"] for event in arm["dispatch_events"]))
        self.assertFalse(report["provider_billing_exactly_once_claimed"])

    def test_recoverable_faults_retain_reference_occurrences_and_expert_evidence(self):
        excluded = {"call_exhaustion", "budget_exhaustion", "deadline_exhaustion"}
        for name, arm in self.arms.items():
            if name in excluded: continue
            with self.subTest(scenario=name):
                self.assertTrue(arm["evidence_identity_vs_reference"])
                self.assertEqual(arm["occurrences_comparison"]["missing"], [])
                self.assertEqual(arm["expert_evidence_comparison"]["missing"], [])
                self.assertEqual(arm["final_status"]["coverage"]["partial"], 0)
                self.assertEqual(arm["warm_resume_dispatches"], 0)

    def test_interruption_before_dispatch_has_neither_call_nor_reservation(self):
        arm = self.arms["before_dispatch"]
        self.assertEqual(arm["first_checkpoint"]["provider_dispatches"], 0)
        self.assertEqual(arm["first_checkpoint"]["ledger_attempts"], 0)
        self.assertEqual(arm["provider_dispatches"], 8)
        self.assertEqual(arm["repeated_logical_dispatches"], 0)

    def test_lost_uncertain_response_and_cache_rollback_hold_reserve_on_resume(self):
        for name in ("during_uncertain_request", "before_cache_persistence", "cache_transaction_rollback"):
            arm = self.arms[name]
            with self.subTest(scenario=name):
                self.assertEqual(arm["first_checkpoint"]["cache_entries"], 0)
                self.assertEqual(arm["first_checkpoint"]["unsettled_attempts"], 1)
                self.assertEqual(arm["uncertain_reservations"]["attempts"], 1)
                self.assertGreater(arm["uncertain_reservations"]["held_simulated_usd"], 0)
                self.assertEqual(arm["provider_dispatches"], 9)
                self.assertEqual(arm["repeated_logical_dispatches"], 1)

    def test_committed_cache_replays_after_grounding_interrupt_without_redispatch(self):
        for name in ("after_cache_persistence", "grounding_transaction_rollback", "after_grounding_before_completion"):
            arm = self.arms[name]
            with self.subTest(scenario=name):
                self.assertEqual(arm["first_checkpoint"]["cache_entries"], 1)
                self.assertEqual(arm["first_checkpoint"]["unsettled_attempts"], 0)
                self.assertEqual(arm["provider_dispatches"], 8)
                self.assertEqual(arm["repeated_logical_dispatches"], 0)
                self.assertEqual(arm["uncertain_reservations"]["attempts"], 0)
        self.assertEqual(self.arms["grounding_transaction_rollback"]["first_checkpoint"]["evidence"]["occurrences"], [])
        self.assertEqual(len(self.arms["after_grounding_before_completion"]["first_checkpoint"]["evidence"]["occurrences"]), 1)

    def test_truncated_grounded_candidate_survives_and_split_recovery_is_measured(self):
        for name in ("truncation", "malformed", "refusal"):
            arm = self.arms[name]
            self.assertEqual(arm["recovery_effort"]["split_children"], 2)
            self.assertEqual(arm["dispatch_delta_vs_reference"], 2)
            self.assertEqual(arm["occurrences_comparison"]["retained"], 4)
        self.assertEqual(self.arms["timeout"]["uncertain_reservations"]["attempts"], 1)
        self.assertEqual(self.arms["transient"]["uncertain_reservations"]["attempts"], 0)

    def test_exhausted_work_keeps_reference_denominators_and_does_not_expand_limits(self):
        for name, reason in (("call_exhaustion", "request_budget_exhausted"),
                             ("budget_exhaustion", "spending_budget_reservation_exhausted"),
                             ("deadline_exhaustion", "run_deadline_exhausted")):
            arm = self.arms[name]
            with self.subTest(scenario=name):
                self.assertEqual(arm["occurrences_comparison"]["reference"], 4)
                self.assertEqual(arm["expert_evidence_comparison"]["reference"], 8)
                self.assertTrue(arm["expert_evidence_comparison"]["missing"])
                self.assertEqual(arm["final_status"]["stop_reason"], reason)
                self.assertIsNone(arm["warm_resume_dispatches"])
        self.assertEqual(self.arms["call_exhaustion"]["provider_dispatches"], 8)
        self.assertEqual(self.arms["budget_exhaustion"]["provider_dispatches"], 1)
        self.assertEqual(self.arms["budget_exhaustion"]["uncertain_reservations"]["attempts"], 1)

    def test_cancel_resume_and_model_revision_invalidation_are_explicit(self):
        cancel = self.arms["cancellation"]
        self.assertEqual(cancel["first_status"]["stop_reason"], "cancelled_by_researcher")
        self.assertEqual(cancel["recovery_effort"]["explicit_cancel_clears"], 1)
        invalidate = self.arms["cache_invalidation"]
        self.assertEqual(invalidate["intentional_identity_change_dispatches"], 4)
        self.assertEqual(invalidate["dispatch_delta_vs_reference"], 4)
        self.assertEqual(invalidate["repeated_logical_dispatches"], 4)
        self.assertEqual(invalidate["retry_ledger_attempts"], 0)

    def test_each_frozen_export_is_byte_identical_after_live_annotation_and_resume(self):
        for arm in (self.report["reference"], *self.report["arms"]):
            self.assertTrue(arm["frozen_export"]["identity_preserved"])
            self.assertEqual(arm["frozen_export"]["before_sha256_by_file"],
                             arm["frozen_export"]["after_sha256_by_file"])
            self.assertIn("dataset.json", arm["frozen_export"]["before_sha256_by_file"])

    def test_fault_assignments_and_results_are_stable_at_concurrency_one_and_four(self):
        selected = ("during_uncertain_request", "cache_transaction_rollback", "after_cache_persistence",
                    "truncation", "timeout", "transient", "malformed", "refusal", "cache_invalidation")
        low = run_fault_suite(self.root / "serial", concurrency=1, scenarios=selected)
        high = run_fault_suite(self.root / "parallel", concurrency=4, scenarios=selected)
        for left, right in zip(low["arms"], high["arms"]):
            with self.subTest(scenario=left["arm"]):
                self.assertEqual(left["target_logical_request_key"], right["target_logical_request_key"])
                self.assertEqual(left["provider_dispatches_by_logical_request"], right["provider_dispatches_by_logical_request"])
                self.assertEqual(left["dispatch_events"], right["dispatch_events"])
                self.assertEqual(left["evidence"], right["evidence"])
                self.assertEqual(left["uncertain_reservations"], right["uncertain_reservations"])

    def test_per_request_schedule_survives_provider_reconstruction_and_other_threads(self):
        source = fixture_sources()[0]
        source["source_id"] = "synthetic-source"
        first = {"job_id": "job-a", "source": source, "text": source["text"],
                 "start": 0, "prompt": "a", "expert": {"id": "a"}, "max_output_tokens": 128}
        second = deepcopy(first)
        second.update(job_id="job-b", prompt="b", expert={"id": "b"})
        journal = self.root / "provider-test.jsonl"
        key = logical_request_key(first)
        provider = RequestKeyedProvider({key: ["timeout"]}, journal=journal)
        with ThreadPoolExecutor(max_workers=2) as pool:
            healthy = pool.submit(provider.complete, second)
            failed = pool.submit(provider.complete, first)
            self.assertEqual(healthy.result(), logical_response(second))
            with self.assertRaises(ProviderError): failed.result()
        restored = RequestKeyedProvider({key: ["timeout"]}, journal=journal)
        self.assertEqual(restored.complete(first), logical_response(first))
        self.assertEqual(restored.counts[key], 2)
        self.assertEqual([event["action"] for event in restored.events if event["logical_request_key"] == key], ["timeout", "success"])

    def test_output_reuse_and_invalid_configuration_are_rejected(self):
        with self.assertRaises(FileExistsError): run_fault_suite(self.root / "suite")
        for concurrency in (True, 0, 9):
            with self.assertRaises(ValueError): run_fault_suite(self.root / "invalid", concurrency)
        with self.assertRaises(ValueError): run_fault_suite(self.root / "unknown", scenarios=["made_up"])
        self.assertFalse((self.root / "unknown").exists())


if __name__ == "__main__": unittest.main()
