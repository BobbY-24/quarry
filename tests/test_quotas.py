"""Finite offline account-admission contracts, including real processes."""
from dataclasses import asdict
from hashlib import sha256
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from termfinder.quotas import QuotaCoordinator, QuotaLimits, process_start_identity, process_state


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


def compete(path, number, barrier, results, active, peak, lock):
    """Reviewed synthetic contention: no adapters, remote calls or secrets."""
    try:
        gate = QuotaCoordinator(path, "shared-test-account", {"max_inflight": 2})
        barrier.wait(timeout=5)
        deadline = time.monotonic() + 6
        token = f"process-{number}"
        while time.monotonic() < deadline:
            admission = gate.try_acquire(f"study-{number % 2}", token, token, 10)
            if admission.admitted:
                gate.mark_dispatched(admission.lease)
                with lock:
                    active.value += 1
                    peak.value = max(peak.value, active.value)
                time.sleep(0.03)
                with lock: active.value -= 1
                gate.release(admission.lease, actual_tokens=8)
                results.put((number, "settled"))
                return
            time.sleep(0.01)
        results.put((number, "deadline"))
    except BaseException as error:
        results.put((number, type(error).__name__))


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quota-tests-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "quota.sqlite"
        self.clock = Clock()

    def gate(self, limits=None, **options):
        return QuotaCoordinator(self.path, "opaque-account-A", limits, clock=self.clock, **options)

    def admit(self, gate, token="a", study="study-A", tokens=10, retry=False):
        return gate.try_acquire(study, "job-" + token, token, tokens, retry)

    def test_aliases_and_projects_share_atomic_inflight_limit(self):
        glm = self.gate({"max_inflight": 1})
        deepseek = self.gate({"max_inflight": 1})
        lease = self.admit(glm).lease
        self.assertIsNotNone(lease)
        glm.mark_dispatched(lease)
        denied = self.admit(deepseek, "b", "study-B")
        self.assertEqual(denied.reason, "account_inflight_limit")
        glm.release(lease)
        self.assertTrue(self.admit(deepseek, "b", "study-B").admitted)

    def test_independent_scopes_are_not_conflated(self):
        a = self.gate({"max_inflight": 1})
        b = QuotaCoordinator(self.path, "opaque-account-B", {"max_inflight": 1}, clock=self.clock)
        self.assertTrue(self.admit(a).admitted)
        self.assertTrue(self.admit(b).admitted)

    def test_waiting_creates_no_execution_or_retry_events(self):
        gate = self.gate({"max_inflight": 1})
        lease = self.admit(gate).lease
        for _ in range(20):
            self.assertEqual(self.admit(gate, "b", retry=True).reason, "account_inflight_limit")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM quota_events").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM quota_leases").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM quota_waiters").fetchone()[0], 1)
        gate.release(lease, outcome="not_sent")
        self.assertTrue(self.admit(gate, "b", retry=True).admitted)

    def test_request_and_token_windows_survive_reopen(self):
        gate = self.gate({"requests_per_window": 2, "tokens_per_window": 20})
        a = self.admit(gate, "a", tokens=15).lease
        gate.mark_dispatched(a); gate.release(a, actual_tokens=3)
        self.assertEqual(self.admit(gate, "b", tokens=10).reason, "account_token_rate")
        reopened = self.gate({"requests_per_window": 2, "tokens_per_window": 20})
        self.clock.advance(60)
        b = self.admit(reopened, "b", tokens=10).lease
        reopened.mark_dispatched(b); reopened.release(b)
        c = self.admit(reopened, "c", tokens=10).lease
        reopened.mark_dispatched(c); reopened.release(c)
        self.assertEqual(self.admit(reopened, "d", tokens=0).reason, "account_request_rate")

    def test_actual_token_overrun_is_conservative(self):
        gate = self.gate({"tokens_per_window": 20})
        lease = self.admit(gate, tokens=5).lease
        gate.mark_dispatched(lease); gate.release(lease, actual_tokens=21)
        self.assertEqual(self.admit(gate, "b", tokens=0).reason, "account_token_rate")
        self.clock.advance(60)
        self.assertTrue(self.admit(gate, "b", tokens=0).admitted)

    def test_aggregate_retry_budget_preserves_healthy_other_study(self):
        gate = self.gate({"retry_requests_per_window": 1})
        lease = self.admit(gate, retry=True).lease
        gate.mark_dispatched(lease); gate.release(lease)
        denied = self.admit(gate, "retry2", retry=True)
        self.assertEqual(denied.reason, "account_retry_budget")
        self.assertTrue(self.admit(gate, "healthy", "study-B").admitted)
        self.clock.advance(3600)
        self.assertTrue(self.admit(gate, "retry2", retry=True).admitted)

    def test_zero_retry_budget_is_valid_and_not_a_spin(self):
        gate = self.gate({"retry_requests_per_window": 0})
        admission = self.admit(gate, retry=True)
        self.assertEqual(admission.reason, "account_retry_budget")
        self.assertEqual(gate.diagnostics()["inflight"], 0)

    def test_bounded_queue_and_explicit_cancellation(self):
        gate = self.gate({"max_inflight": 1, "max_queue": 2, "max_queue_per_study": 1})
        self.admit(gate)
        self.assertEqual(self.admit(gate, "b").reason, "account_inflight_limit")
        self.assertEqual(self.admit(gate, "c").reason, "account_queue_full")
        self.assertEqual(self.admit(gate, "d", "study-B").reason, "account_inflight_limit")
        self.assertEqual(self.admit(gate, "e", "study-C").reason, "account_queue_full")
        gate.cancel_waiter("b")
        self.assertEqual(gate.diagnostics()["queued"], 1)

    def test_fifo_within_study_and_round_robin_between_studies(self):
        gate = self.gate({"max_inflight": 1})
        a = self.admit(gate).lease
        self.admit(gate, "a2"); self.admit(gate, "a3"); self.admit(gate, "b1", "study-B")
        gate.release(a, outcome="not_sent")
        self.assertEqual(self.admit(gate, "a2").reason, "account_fair_queue")
        b = self.admit(gate, "b1", "study-B").lease
        gate.release(b, outcome="not_sent")
        self.assertEqual(self.admit(gate, "a3").reason, "account_fair_queue")
        self.assertTrue(self.admit(gate, "a2").admitted)

    def test_cooldown_shared_persistent_and_does_not_shorten(self):
        gate = self.gate()
        gate.cooldown(100); gate.cooldown(10)
        self.assertEqual(self.admit(self.gate()).reason, "account_cooldown")
        self.clock.advance(99)
        self.assertAlmostEqual(self.admit(gate).retry_after, 1)
        self.clock.advance(1)
        self.assertTrue(self.admit(gate).admitted)
        with self.assertRaises(ValueError): gate.cooldown(86401)

    def test_conflicting_settings_only_tighten_and_are_visible(self):
        self.gate({"max_inflight": 4, "window_seconds": 60})
        tight = self.gate({"max_inflight": 1, "window_seconds": 120})
        loose = self.gate({"max_inflight": 10, "window_seconds": 30})
        state = loose.diagnostics()
        self.assertEqual(state["effective_limits"]["max_inflight"], 1)
        self.assertEqual(state["effective_limits"]["window_seconds"], 120)
        self.assertTrue(state["config_conflict"])
        self.assertTrue(self.admit(tight).config_conflict)

    def test_expired_live_and_unknown_leases_never_reclaim(self):
        for probe in (lambda pid, start: "alive", lambda pid, start: "unknown"):
            with self.subTest(probe=probe):
                path = Path(self.temp.name) / (str(id(probe)) + ".sqlite")
                gate = QuotaCoordinator(path, "scope", {"max_inflight": 1, "lease_seconds": 1}, clock=self.clock, process_probe=probe)
                self.admit(gate); self.clock.advance(100)
                self.assertEqual(self.admit(gate, "b").reason, "account_inflight_limit")
                self.assertEqual(gate.diagnostics()["expired_unresolved_leases"], 1)

    def test_dead_reserved_reclaims_only_after_expiry_and_dead_dispatched_never_reclaims(self):
        gate = self.gate({"max_inflight": 1, "lease_seconds": 1})
        lease = self.admit(gate).lease
        gate.process_probe = lambda pid, start: "dead"
        self.assertEqual(self.admit(gate, "b").reason, "account_inflight_limit")
        self.clock.advance(1)
        next_lease = self.admit(gate, "b").lease
        self.assertIsNotNone(next_lease)
        gate.mark_dispatched(next_lease)
        self.clock.advance(10000)
        self.assertEqual(self.admit(gate, "c").reason, "account_inflight_limit")

    def test_uncertain_remote_outcome_retains_capacity_until_explicit_resolution(self):
        gate = self.gate({"max_inflight": 1})
        lease = self.admit(gate).lease
        gate.mark_dispatched(lease); gate.release(lease, outcome="uncertain")
        self.clock.advance(10000)
        self.assertEqual(self.admit(gate, "b").reason, "account_inflight_limit")
        with self.assertRaises(ValueError): gate.release(lease)
        with self.assertRaises(ValueError): gate.release(lease, outcome="not_sent")
        gate.resolve_uncertain(lease, evidence="operator-receipt-reference", actual_tokens=12)
        self.assertTrue(self.admit(gate, "b").admitted)

    def test_idempotent_reservation_and_no_duplicate_dispatch(self):
        gate = self.gate()
        a = self.admit(gate)
        self.assertEqual(self.admit(gate).lease, a.lease)
        with self.assertRaises(ValueError): self.admit(gate, tokens=12)
        gate.mark_dispatched(a.lease)
        self.assertEqual(self.admit(gate).reason, "attempt_already_dispatched")
        with self.assertRaises(ValueError): gate.mark_dispatched(a.lease)
        gate.release(a.lease); gate.release(a.lease)
        self.assertEqual(self.admit(gate).reason, "attempt_already_settled")

    def test_terminal_receipts_are_bounded_without_dropping_active_leases(self):
        gate = self.gate({"max_history": 2})
        active = self.admit(gate, "active").lease
        for number in range(5):
            lease = self.admit(gate, str(number), "other-study").lease
            gate.release(lease, outcome="not_sent")
        state = gate.diagnostics()
        self.assertEqual(state["states"]["not_sent"], 2)
        self.assertEqual(state["inflight"], 1)
        gate.release(active, outcome="not_sent")

    def test_host_mismatch_refuses_false_multihost_coordination(self):
        self.gate(host_id="host-A")
        with self.assertRaisesRegex(ValueError, "another host"):
            self.gate(host_id="host-B")

    def test_different_pid_namespace_cannot_reclaim_another_container(self):
        self.gate()
        with patch("termfinder.quotas._pid_namespace", return_value="different-pid-namespace"):
            with self.assertRaisesRegex(ValueError, "another PID namespace"):
                self.gate()

    def test_registry_rejects_symlink_public_permissions_and_invalid_limits(self):
        outside = Path(self.temp.name) / "other.sqlite"
        outside.write_text("marker", encoding="utf-8")
        self.path.symlink_to(outside)
        with self.assertRaises(ValueError): self.gate()
        self.assertEqual(outside.read_text(), "marker")
        self.path.unlink()
        self.path.touch(mode=0o644)
        with self.assertRaises(ValueError): self.gate()
        self.path.unlink()
        for options in ({"max_inflight": 0}, {"window_seconds": float("nan")},
                        {"max_queue": True}, {"max_queue": 1, "max_queue_per_study": 2}, {"unknown": 1}):
            with self.assertRaises((ValueError, TypeError)): self.gate(options)

    def test_busy_registry_defers_without_dispatch(self):
        gate = self.gate()
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            admission = self.admit(gate)
            self.assertEqual(admission.reason, "account_registry_busy")
            db.rollback()
        self.assertEqual(gate.diagnostics()["inflight"], 0)

    def test_existing_wal_registry_is_rejected_without_silent_journal_reset(self):
        self.gate()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.assertRaisesRegex(ValueError, "DELETE journal mode"):
            self.gate()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_symlink_ancestor_is_rejected_before_directory_creation(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = Path(self.temp.name) / "link"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            QuotaCoordinator(link / "new" / "quota.sqlite", "scope")
        self.assertFalse((outside / "new").exists())

    def test_unrelated_sqlite_output_is_preserved_byte_for_byte(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE researcher_dataset(id TEXT,value TEXT)")
            db.execute("INSERT INTO researcher_dataset VALUES('synthetic','private synthetic context')")
        self.path.chmod(0o600)
        original = sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "unrelated data"):
            self.gate()
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), original)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM researcher_dataset").fetchone()[0], 1)

    def test_future_registry_schema_is_rejected_before_writes(self):
        self.gate()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE registry_meta SET value='2' WHERE key='schema_version'")
        original = sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.gate()
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), original)

    def test_os_identity_never_reads_process_environment(self):
        identity = process_start_identity(os.getpid())
        self.assertIsNotNone(identity)
        self.assertEqual(process_state(os.getpid(), identity), "alive")
        self.assertEqual(process_state(os.getpid(), identity + "-different-generation"), "dead")
        with patch("termfinder.quotas.os.kill", side_effect=PermissionError()):
            self.assertEqual(process_state(os.getpid(), identity), "unknown")

    @unittest.skipUnless(os.name == "posix", "same-host POSIX operating envelope")
    def test_real_cross_process_atomic_limit_and_progress(self):
        # Forked child app code stays inside the parent's verified OS sandbox.
        context = multiprocessing.get_context("fork")
        QuotaCoordinator(self.path, "shared-test-account", {"max_inflight": 2})
        barrier, results = context.Barrier(6), context.Queue()
        active, peak, lock = context.Value("i", 0), context.Value("i", 0), context.Lock()
        workers = [context.Process(target=compete, args=(self.path, n, barrier, results, active, peak, lock)) for n in range(6)]
        try:
            for worker in workers: worker.start()
            deadline = time.monotonic() + 10
            for worker in workers: worker.join(timeout=max(0, deadline - time.monotonic()))
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            receipts = [results.get(timeout=1) for _ in workers]
            self.assertTrue(all(status == "settled" for _, status in receipts), receipts)
            self.assertGreater(peak.value, 0)
            self.assertLessEqual(peak.value, 2)
            self.assertTrue(all(worker.exitcode == 0 for worker in workers))
        finally:
            for worker in workers:
                if worker.is_alive(): worker.kill()
                worker.join(timeout=1)
            results.close(); results.join_thread()


if __name__ == "__main__":
    unittest.main()
