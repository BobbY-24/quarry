"""Real local process-loss boundaries with fake schedulers/providers only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_cluster as fixtures
from termfinder.cluster import ClusterController, read_json, write_json
from termfinder.cluster_worker import run_bundle
from termfinder.dispatch_journal import DispatchJournal, JournalError
from termfinder.store import Store

# The child inherits the verified outer OS sandbox. Its provider makes no
# network request and deliberately exits the whole process after durable intent.
CRASH_CHILD = r'''
import os, sys
from termfinder import FakeProvider
from termfinder.cluster_worker import run_bundle
class Crash(FakeProvider):
    def complete(self, request):
        os._exit(73)
run_bundle(sys.argv[1], sys.argv[2], execute=True, provider=Crash([]), scratch_root=sys.argv[3])
'''


class ClusterJournalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClusterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_actual_process_loss_after_intent_restores_attempt_before_any_resume_call(self):
        f = self.fixture
        review, first = f.submitted()
        environment = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        child = subprocess.run([sys.executable, "-c", CRASH_CHILD, review["bundle"], first["job_id"], str(f.scratch)],
            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=15)
        self.assertEqual(child.returncode, 73)
        journal = Path(review["bundle"]) / "dispatch-journal"
        intent_paths = list(journal.glob("*.intent.json"))
        self.assertEqual(len(intent_paths), 1)
        intent = json.loads(intent_paths[0].read_text())
        self.assertEqual(intent["attempt"]["request_count"], 1)
        self.assertGreater(intent["attempt"]["reserved_seconds"], 0)
        self.assertEqual(list(journal.glob("*.terminal.json")), [])
        self.assertEqual(f.project.store.count("costs"), 0)
        self.assertEqual(f.controller.status()["blocked_reason"], "active_or_uncertain_allocation")
        # Simulate loss of scratch, then an explicit terminal Slurm observation.
        for path in f.scratch.iterdir():
            shutil.rmtree(path)
        f.scheduler.states[first["scheduler_job_id"]] = "node_fail"
        f.controller.status(first["job_id"], scheduler=f.scheduler)
        second = f.controller.resume(review["cluster_review_id"], approval_reference="Synthetic explicit postfailure allocation",
            human_approved=True, allow_execution=True, scheduler=f.scheduler)
        provider = f.provider()
        original_complete = provider.complete
        def complete(request):
            active = list(f.scratch.glob("quarry-active-*/study/project.sqlite3"))
            self.assertEqual(len(active), 1)
            with sqlite3.connect(active[0]) as db:
                row = db.execute("SELECT data FROM costs WHERE id=?", (intent["attempt"]["attempt_id"],)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row[0])["status"], "uncertain")
            return original_complete(request)
        provider.complete = complete
        result = run_bundle(review["bundle"], second["job_id"], execute=True, provider=provider, scratch_root=f.scratch)
        self.assertEqual(result["result"]["status"], "partial")
        self.assertNotIn(intent["job"]["job_id"], provider.calls)
        self.assertEqual(len(provider.calls), 1)  # Other healthy extractor can proceed.
        f.controller.import_result(second["job_id"])
        costs = f.project.store.rows("costs")
        self.assertEqual(len(costs), 2)
        recovered = f.project.store.get("costs", intent["attempt"]["attempt_id"])
        self.assertEqual(recovered["status"], "uncertain")
        self.assertEqual(recovered["reserved_seconds"], intent["attempt"]["reserved_seconds"])
        self.assertTrue(f.project.store.rows("jobs", where="json_extract(data,'$.status')='uncertain'"))
        # A second import cannot duplicate the recovered accounting identity.
        f.controller.import_result(second["job_id"])
        self.assertEqual(f.project.store.count("costs"), 2)

    def test_missing_journal_never_resets_request_accounting_on_resume(self):
        f = self.fixture
        review, first = f.submitted()
        run_bundle(review["bundle"], first["job_id"], execute=True,
            provider=f.provider(), max_jobs=1, scratch_root=f.scratch)
        shutil.rmtree(Path(review["bundle"]) / "dispatch-journal")
        with self.assertRaisesRegex(ValueError, "accounting is unavailable"):
            f.controller.resume(review["cluster_review_id"], approval_reference="Synthetic blocked resume",
                human_approved=True, allow_execution=True, scheduler=f.scheduler)
        self.assertEqual(len(f.scheduler.submitted), 1)

    def test_intent_storage_failure_does_not_start_provider(self):
        f = self.fixture
        review, first = f.submitted()
        original = DispatchJournal._write
        def fail_intent(journal, path, value):
            if path.name.endswith(".intent.json"):
                raise OSError("synthetic-private-storage-marker")
            return original(journal, path, value)
        provider = f.provider()
        with patch.object(DispatchJournal, "_write", fail_intent):
            result = run_bundle(review["bundle"], first["job_id"], execute=True,
                provider=provider, scratch_root=f.scratch)
        self.assertEqual(provider.calls, [])
        self.assertEqual(result["result"]["status"], "partial")
        f.controller.import_result(first["job_id"])
        costs = f.project.store.rows("costs")
        self.assertEqual(costs[0]["status"], "not_sent")
        self.assertEqual(costs[0]["request_count"], 0)
        self.assertEqual(costs[0]["settled_usd"], 0)
        self.assertEqual(costs[0]["settled_seconds"], 0)

    def test_checkpoint_failure_preserves_private_local_response_receipt(self):
        f = self.fixture
        review, job = f.submitted()
        original, count = Store.backup, {"calls": 0}
        def backup(store, target):
            count["calls"] += 1
            if count["calls"] == 1:
                return original(store, target)
            raise OSError("synthetic-private-checkpoint-marker")
        with patch.object(Store, "backup", backup):
            with self.assertRaises(OSError):
                run_bundle(review["bundle"], job["job_id"], execute=True,
                    provider=f.provider(), scratch_root=f.scratch)
        record = f.controller.status()["job"]
        recovery = record["node_local_recovery"]
        self.assertTrue(recovery["required"])
        self.assertEqual(recovery["availability"], "only_if_original_node_storage_survives")
        local = Path(recovery["directory"])
        self.assertTrue(local.is_relative_to(f.scratch))
        self.assertEqual(Store(local / "project.sqlite3").count("cache"), 2)
        self.assertEqual(Store(local / "project.sqlite3").count("terms"), 1)

    def test_requeue_and_changed_scheduler_identity_never_call_provider(self):
        f = self.fixture
        review, job = f.submitted()
        provider = f.provider()
        for selected in ({"SLURM_JOB_ID": job["scheduler_job_id"], "SLURM_RESTART_COUNT": "1"},
                {"SLURM_JOB_ID": "999999", "SLURM_RESTART_COUNT": "0"}):
            with patch.dict(os.environ, selected), self.assertRaises(ValueError):
                run_bundle(review["bundle"], job["job_id"], execute=True, provider=provider, scratch_root=f.scratch)
        self.assertEqual(provider.calls, [])

    def test_unknown_scheduler_cannot_release_unfinished_worker_cleanup_fence(self):
        f = self.fixture
        review, job = f.submitted()
        state = read_json(f.controller.root / "state.json")
        state["jobs"][0].update(state="partial", execution_claim={"generation": job["execution_generation"]})
        write_json(f.controller.root / "state.json", state)
        f.scheduler.states[job["scheduler_job_id"]] = "unknown"
        self.assertEqual(f.controller.status(job["job_id"], scheduler=f.scheduler)["blocked_reason"], "active_or_uncertain_allocation")
        with self.assertRaises(ValueError):
            f.controller.resume(review["cluster_review_id"], approval_reference="Synthetic denied overlap",
                human_approved=True, allow_execution=True, scheduler=f.scheduler)
        f.scheduler.states[job["scheduler_job_id"]] = "node_fail"
        self.assertIsNone(f.controller.status(job["job_id"], scheduler=f.scheduler)["blocked_reason"])

    def test_same_host_quota_cannot_be_copied_to_gt_allocation(self):
        f = self.fixture
        f.project.configure_quota(f.base / "local-quota.sqlite3", "synthetic-account")
        with self.assertRaisesRegex(ValueError, "Same-host"):
            f.controller.configure(f.profile)
        self.assertEqual(f.scheduler.submitted, [])


if __name__ == "__main__":
    unittest.main()
