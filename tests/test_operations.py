"""Offline control receipt, crash, rollback and delivery retry contracts."""
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from termfinder import Project
from termfinder.operations import MAX_RESULT_BYTES, OperationManager, OperationRejected


def crash_effect(path, atomic):
    project = Project(path)
    manager = OperationManager(project)
    def callback():
        project.store.setting("crash-counter", 1)
        os._exit(47)
    manager.execute("crash-operation", "test:crash", {"atomic_case": atomic}, callback, atomic=atomic)


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="operations-tests-")
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / "study")
        self.manager = OperationManager(self.project)

    def test_same_identity_same_parameters_replays_after_reopen(self):
        calls = []
        def callback():
            calls.append(1)
            self.project.store.setting("counter", 1)
            return {"changed": True, "annotation_id": "ann-1"}
        first = self.manager.execute("researcher-action-1", "mcp:annotate", {"status": "accepted"}, callback, atomic=True)
        second = OperationManager(Project(self.project.path)).execute(
            "researcher-action-1", "mcp:annotate", {"status": "accepted"}, callback, atomic=True)
        self.assertEqual(first, second)
        self.assertEqual(calls, [1])
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(self.project.store.read_setting("counter"), 1)

    def test_parameter_kind_or_effect_changes_reject_without_effect(self):
        self.manager.execute("same-id", "cli:snapshot", {"name": "v1"}, lambda: {"version_id": "v1"})
        for kind, params, atomic in (("cli:snapshot", {"name": "v2"}, False),
                                     ("cli:export", {"name": "v1"}, False),
                                     ("cli:snapshot", {"name": "v1"}, True)):
            with self.assertRaises(ValueError):
                self.manager.execute("same-id", kind, params, lambda: self.fail("callback repeated"), atomic=atomic)

    def test_short_effect_and_terminal_receipt_share_transaction(self):
        def callback():
            self.project.store.setting("counter", 10)
            with self.project.store.connection() as db:
                self.assertTrue(db.in_transaction)
                self.assertEqual(self.project.store.get("operations", "atomic", db)["status"], "pending")
            return {"changed": True}
        result = self.manager.execute("atomic", "db:update", {}, callback, atomic=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.project.store.read_setting("counter"), 10)

    def test_atomic_failure_rolls_back_effect_and_returns_safe_failure(self):
        marker = "sk-QUARRY-SYNTHETIC-CANARY-00000000000000000000"
        def callback():
            self.project.store.setting("counter", 1)
            raise RuntimeError(marker)
        receipt = self.manager.execute("failed-atomic", "db:update", {}, callback, atomic=True)
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(receipt["effect_rolled_back"])
        self.assertIsNone(self.project.store.read_setting("counter"))
        self.assertNotIn(marker, json.dumps(receipt))
        repeated = self.manager.execute("failed-atomic", "db:update", {}, lambda: self.fail("failed receipt repeated"), atomic=True)
        self.assertEqual(repeated, receipt)

    def test_long_effect_has_durable_intent_and_no_writer_lock(self):
        def callback():
            with sqlite3.connect(self.project.store.path, timeout=.2) as other:
                other.execute("BEGIN IMMEDIATE")
                row = other.execute("SELECT data FROM operations WHERE id='external'").fetchone()
                self.assertEqual(json.loads(row[0])["status"], "pending")
                other.execute("INSERT INTO settings VALUES('long-effect','1')")
            return {"dispatched": True}
        receipt = self.manager.execute("external", "mcp:collect", {}, callback)
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(self.project.store.read_setting("long-effect"), 1)

    def test_unknown_external_failure_remains_uncertain_and_never_reexecutes(self):
        def callback():
            self.project.store.setting("external-side-effect", 1)
            raise RuntimeError("untrusted provider payload should not be stored")
        receipt = self.manager.execute("external-fail", "mcp:collect", {}, callback)
        self.assertEqual(receipt["status"], "uncertain")
        self.assertFalse(receipt["effect_rolled_back"])
        self.assertEqual(self.project.store.read_setting("external-side-effect"), 1)
        self.assertNotIn("untrusted provider payload", json.dumps(receipt))
        repeated = self.manager.execute("external-fail", "mcp:collect", {}, lambda: self.fail("uncertain operation repeated"))
        self.assertEqual(repeated, receipt)

    def test_known_pre_effect_rejection_is_failed_without_uncertainty(self):
        def callback(): raise OperationRejected("validation_failure")
        receipt = self.manager.execute("rejected", "mcp:collect", {}, callback)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["reason"], "validation_failure")

    def test_concurrent_same_identity_never_runs_second_callback(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def callback():
            calls.append(1); started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"one": True}
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.manager.execute, "simultaneous", "mcp:collect", {}, callback)
            self.assertTrue(started.wait(timeout=2))
            pending = OperationManager(Project(self.project.path)).execute(
                "simultaneous", "mcp:collect", {}, lambda: self.fail("second delivery called callback"))
            self.assertEqual(pending["status"], "pending")
            release.set()
            self.assertEqual(first.result(timeout=2)["status"], "succeeded")
        self.assertEqual(calls, [1])

    def test_unknown_process_identity_defers_instead_of_reclaiming(self):
        receipt = self.manager.execute("identity", "mcp:collect", {}, lambda: {"started": True})
        receipt["status"] = "pending"
        self.project.store.put("operations", "identity", receipt)
        manager = OperationManager(self.project, process_probe=lambda pid, start: "unknown")
        pending = manager.execute("identity", "mcp:collect", {}, lambda: self.fail("unknown owner reclaimed"))
        self.assertEqual(pending["status"], "pending")

    def test_other_host_and_dead_owner_are_visible_uncertain(self):
        for label, options in (("host", {"host_id": "different-host"}),
                               ("dead", {"process_probe": lambda pid, start: "dead"})):
            receipt = self.manager.execute(label, "mcp:collect", {}, lambda: True)
            receipt["status"] = "pending"
            self.project.store.put("operations", label, receipt)
            recovered = OperationManager(self.project, **options).receipt(label)
            self.assertEqual(recovered["status"], "uncertain")

    def test_late_worker_cannot_overwrite_reconciled_receipt(self):
        receipt = self.manager.execute("late", "mcp:collect", {}, lambda: {"started": True})
        receipt["status"] = "uncertain"
        self.project.store.put("operations", "late", receipt)
        with self.assertRaises(ValueError): self.manager.complete("late", {"started": True})
        self.assertEqual(self.manager.receipt("late")["status"], "uncertain")

    def test_explicit_resolution_records_receipt_and_does_not_repeat(self):
        def callback(): raise RuntimeError("unknown effect")
        self.manager.execute("resolve", "mcp:collect", {}, callback)
        resolved = self.manager.resolve("resolve", evidence="inspected-run-123", result={"run_id": "run-123"})
        self.assertEqual(resolved["status"], "succeeded")
        self.assertEqual(resolved["resolution_reference"], "inspected-run-123")
        self.assertEqual(self.manager.execute("resolve", "mcp:collect", {}, lambda: self.fail("resolved repeated")), resolved)
        self.manager.execute("no-effect", "mcp:collect", {}, callback)
        rejected = self.manager.resolve("no-effect", evidence="operator-check-1", confirmed_no_effect=True)
        self.assertEqual(rejected["status"], "failed")
        self.assertEqual(rejected["reason"], "confirmed_no_effect")

    def test_receipt_size_inventory_and_parameter_boundaries(self):
        receipt = self.manager.execute("oversized", "mcp:prepare_review", {}, lambda: {"large": "x" * MAX_RESULT_BYTES})
        self.assertEqual(receipt["status"], "succeeded")
        self.assertIsNone(receipt["result"])
        self.assertEqual(receipt["result_reason"], "result_exceeds_receipt_limit_inspect_outputs")
        self.assertEqual(len(receipt["result_sha256"]), 64)
        small = OperationManager(self.project, max_operations=1)
        self.assertEqual(small.execute("oversized", "mcp:prepare_review", {}, lambda: self.fail("capacity replay")), receipt)
        with self.assertRaises(ValueError): small.execute("new-id", "mcp:collect", {}, lambda: True)
        for identifier in ("", "../path", "line\nfeed", "x" * 129):
            with self.assertRaises(ValueError): self.manager.execute(identifier, "mcp:collect", {}, lambda: True)

    def test_credentials_never_enter_parameters_result_or_error_receipts(self):
        marker = "sk-QUARRY-SYNTHETIC-CANARY-00000000000000000000"
        with self.assertRaises(ValueError):
            self.manager.execute("secret-param", "mcp:collect", {"api_key": marker}, lambda: self.fail("secret entered callback"))
        receipt = self.manager.execute("secret-result", "db:update", {}, lambda: {"api_key": marker}, atomic=True)
        self.assertEqual(receipt["status"], "failed")
        serialized = json.dumps(self.project.store.all("operations"))
        self.assertNotIn(marker, serialized)
        self.assertIsNone(self.manager.receipt("secret-param"))

    def test_private_research_content_and_paths_remain_out_of_durable_receipts(self):
        private = "PRIVATE-SYNTHETIC-RESEARCH-CONTEXT"
        result = {"review_id": "review_123", "source_count": 2, "prompt": private,
                  "bundle": {"context": private}, "out": "/private/synthetic/corpus",
                  "unrecognized_free_text": private}
        first = self.manager.execute("private-content", "mcp:prepare_review", {}, lambda: result)
        self.assertEqual(first["transient_result"], result)
        stored = self.manager.receipt("private-content")
        self.assertEqual(stored["result"], {"review_id": "review_123", "source_count": 2})
        self.assertEqual(stored["result_reason"], "content_result_not_captured_inspect_controlled_project_artifact")
        self.assertNotIn(private, json.dumps(stored))
        self.assertNotIn("/private/synthetic", json.dumps(stored))
        self.assertNotIn("transient_result", stored)
        repeated = self.manager.execute("private-content", "mcp:prepare_review", {}, lambda: self.fail("private operation repeated"))
        self.assertEqual(repeated, stored)
        self.assertTrue(stored["owner"]["host_id"].startswith("host_"))

    def test_outer_transaction_is_rejected_before_dispatch_intent(self):
        with self.project.store.connection():
            with self.assertRaises(ValueError):
                self.manager.execute("nested", "db:update", {}, lambda: self.fail("outer transaction callback"))
        self.assertIsNone(self.manager.receipt("nested"))

    def test_complete_is_idempotent_only_for_same_result(self):
        original = self.manager.execute("complete", "mcp:collect", {}, lambda: {"started": True})
        self.assertEqual(self.manager.complete("complete", {"started": True}), original)
        with self.assertRaises(ValueError): self.manager.complete("complete", {"different": True})

    @unittest.skipUnless(os.name == "posix", "supported local POSIX execution")
    def test_process_crash_preserves_pending_intent_and_atomic_rollback_boundary(self):
        context = multiprocessing.get_context("fork")
        for atomic in (False, True):
            with self.subTest(atomic=atomic):
                project = Project(Path(self.temp.name) / ("atomic" if atomic else "external"))
                child = context.Process(target=crash_effect, args=(project.path, atomic))
                try:
                    child.start(); child.join(timeout=5)
                    self.assertFalse(child.is_alive())
                    self.assertEqual(child.exitcode, 47)
                    reopened = Project(project.path)
                    pending = reopened.store.get("operations", "crash-operation")
                    self.assertEqual(pending["status"], "pending")
                    self.assertEqual(reopened.store.read_setting("crash-counter"), None if atomic else 1)
                    manager = OperationManager(reopened)
                    receipt = manager.execute("crash-operation", "test:crash", {"atomic_case": atomic},
                                              lambda: self.fail("crashed operation redelivered"), atomic=atomic)
                    self.assertEqual(receipt["status"], "uncertain")
                finally:
                    if child.is_alive(): child.kill()
                    child.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
