"""Cluster launch gates are separate from inert setup and inference permission."""
import io
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import Project, cli
from termfinder.mcp_server import MCPServer, ToolFailure


class ClusterInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / "study")
        self.server = MCPServer(self.project)
        self.addCleanup(self.server.close)

    def test_tools_cannot_enable_scheduler_launch_gate(self):
        for name in ("submit_cluster", "resume_cluster"):
            with self.assertRaises(ToolFailure) as failure:
                self.server.call_tool(name, {"cluster_review_id": "cluster_review_fixture",
                    "researcher_approved": True, "approval_reference": "Synthetic decision"})
            self.assertEqual(failure.exception.code, "cluster_launch_gate_disabled")
        with self.assertRaises(ToolFailure) as failure:
            self.server.call_tool("submit_cluster", {"cluster_review_id": "fixture",
                "researcher_approved": True, "approval_reference": "Synthetic decision",
                "allow_cluster": True})
        self.assertEqual(failure.exception.code, "invalid_arguments")

    def test_configuration_requires_explicit_operator_declaration(self):
        with self.assertRaises(ToolFailure) as failure:
            self.server.call_tool("configure_cluster", {"profile": {},
                "researcher_configured": False, "configuration_reference": "Synthetic site choice"})
        self.assertEqual(failure.exception.code, "configuration_declaration_required")
        self.assertFalse((self.project.path / "cluster").exists())

    def test_cluster_status_without_profile_is_inert_and_has_no_external_calls(self):
        result = self.server.call_tool("inspect_cluster", {})
        self.assertFalse(result["cluster_execution_permitted"])
        self.assertFalse(result["cluster"]["configured"])
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_agent_cannot_select_unrelated_durable_storage(self):
        outside = Path(self.temp.name) / "unrelated-storage"
        outside.mkdir()
        with self.assertRaises(ToolFailure) as failure:
            self.server.call_tool("configure_cluster", {"profile": {"durable_root": str(outside)},
                "researcher_configured": True, "configuration_reference": "Synthetic operator choice"})
        self.assertEqual(failure.exception.code, "cluster_storage_scope_violation")
        self.assertEqual(list(outside.iterdir()), [])

    def test_operator_reference_is_preserved_with_dispatch_settings(self):
        result = self.server.call_tool("configure_throughput", {"concurrency": 3,
            "model_concurrency": 2, "researcher_configured": True,
            "configuration_reference": "Synthetic operator approved three requests"})
        history = self.project.store.read_setting("agent_workflow")
        self.assertEqual(history[-1]["payload"]["configuration_reference"],
                         "Synthetic operator approved three requests")
        self.assertEqual(result["configuration"]["settings"]["concurrency"], 3)

    def test_all_context_blocked_forecasts_do_not_approve_zero_work(self):
        from test_compute_interfaces import ComputeInterfaceTests
        fixture = ComputeInterfaceTests("test_mcp_configuration_is_inert_and_does_not_enable_inference_gate")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.server.call_tool("configure_compute", dict(fixture.local,
            context_limit_tokens=256, max_output_tokens=128))
        review = fixture.prepared()
        self.assertFalse(review["ready"])
        self.assertGreater(review["context_admission"]["blocked_windows"], 0)
        self.assertIn("context", review["message"])
        self.assertEqual(fixture.project.store.count("sources"), 1)

    def test_cli_exposes_distinct_execution_permissions(self):
        args = cli.parser().parse_args(["cluster-submit", "fixture", "--researcher-approved",
            "--approval-reference", "Synthetic decision", "--allow-cluster"])
        self.assertTrue(args.allow_cluster)
        self.assertFalse(args.allow_paid)
        with patch("sys.stderr", new_callable=io.StringIO) as errors, \
             patch("sys.stdout", new_callable=io.StringIO):
            result = cli.main(["--project", str(self.project.path), "cluster-submit", "fixture",
                "--researcher-approved", "--approval-reference", "Synthetic decision"])
        self.assertEqual(result, 2)
        self.assertIn("Cluster operation", errors.getvalue())

    def test_idle_connection_close_leaves_detached_collection_untouched(self):
        # A server with no local thread must not call cancellation just because
        # a durable scheduler job is recorded outside the local collection path.
        self.project.store.setting("cluster_execution", {"job_id": "cluster_job_fixture", "status": "submitted"})
        with patch.object(self.project, "cancel", side_effect=AssertionError("Detached job cancelled")):
            self.server.close()
        self.assertEqual(self.project.store.read_setting("cluster_execution")["status"], "submitted")

    def test_frozen_export_retains_accounting_without_reading_current_job_state(self):
        from termfinder.config import starter_recipe
        self.project.configure(starter_recipe("jargon"), "fake")
        self.project.store.setting("cluster_accounting", {"reserved_gpu_hours": 2.5,
            "actual_charge_usd": None, "actual_charge_reason": "invoice_unavailable"})
        version = self.project.snapshot("cluster-fixture")
        first = self.project.path / "export-one"
        second = self.project.path / "export-two"
        self.project.export(version, first, formats=["jsonl"])
        self.project.store.setting("cluster_accounting", {"reserved_gpu_hours": 99})
        self.project.export(version, second, formats=["jsonl"])
        manifest = json.loads((first / "manifest.json").read_text())
        self.assertEqual(manifest["compute_execution"]["cluster_accounting"]["reserved_gpu_hours"], 2.5)
        self.assertIsNone(manifest["compute_execution"]["cluster_accounting"]["actual_charge_usd"])
        for path in first.iterdir():
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())

    def test_throughput_change_invalidates_review_without_changing_recipe_budget(self):
        # Use the complete real planning path; this catches stale approvals
        # accepting a changed dispatch policy rather than merely checking flags.
        from test_workflow import WorkflowTests
        fixture = WorkflowTests("test_run_requires_explicit_approval_and_paid_authorization")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.approved()
        budget = fixture.project.recipe["execution"]["budget_usd"]
        original_recipe = fixture.project.recipe
        fixture.project.configure_cluster_throughput(concurrency=3, model_concurrency=2)
        from termfinder.workflow import current_review
        self.assertTrue(current_review(fixture.project)["stale"])
        self.assertEqual(fixture.project.recipe, original_recipe)
        self.assertEqual(fixture.project.recipe["execution"]["budget_usd"], budget)

    def test_agent_reconnects_to_partial_job_resumes_imports_and_inspects_evidence(self):
        from test_cluster import ClusterTests
        from termfinder.cluster_worker import run_bundle
        fixture = ClusterTests("test_partial_resume_uses_checkpoint_and_does_not_repeat_completed_calls")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        profile = fixture.profile
        server = MCPServer(fixture.project, allow_cluster=True,
            cluster_storage_roots=[profile["durable_root"]])
        self.addCleanup(server.close)
        server.call_tool("configure_cluster", {"profile": profile, "researcher_configured": True,
            "configuration_reference": "Synthetic approved durable storage and resources"})
        review = server.call_tool("prepare_cluster", {"review_id": fixture.review["review_id"]})
        with patch("termfinder.cluster.SlurmScheduler", return_value=fixture.scheduler):
            job = server.call_tool("submit_cluster", {"cluster_review_id": review["cluster_review_id"],
                "researcher_approved": True, "approval_reference": "Synthetic first allocation decision"})
        server.close()
        self.assertEqual(Project(fixture.project.path).cluster().status(job["job_id"])["job"]["state"], "submitted")
        run_bundle(review["bundle"], job["job_id"], execute=True, provider=fixture.provider(),
            max_jobs=1, scratch_root=fixture.scratch)
        reconnected = MCPServer(Project(fixture.project.path), allow_cluster=True,
            cluster_storage_roots=[profile["durable_root"]])
        self.addCleanup(reconnected.close)
        partial = reconnected.call_tool("inspect_cluster", {"job_id": job["job_id"]})
        self.assertEqual(partial["cluster"]["job"]["state"], "partial")
        self.assertTrue(reconnected.call_tool("import_cluster", {"job_id": job["job_id"]})["imported"])
        with patch("termfinder.cluster.SlurmScheduler", return_value=fixture.scheduler):
            resumed = reconnected.call_tool("resume_cluster", {"cluster_review_id": review["cluster_review_id"],
                "researcher_approved": True, "approval_reference": "Synthetic second allocation decision"})
        provider = fixture.provider()
        run_bundle(review["bundle"], resumed["job_id"], execute=True, provider=provider,
            scratch_root=fixture.scratch)
        self.assertEqual(len(provider.calls), 1)
        reconnected.call_tool("import_cluster", {"job_id": resumed["job_id"]})
        records = reconnected.call_tool("records", {})["records"]
        self.assertEqual(len(records), 1)
        evidence = reconnected.call_tool("inspect_record", {"record_id": records[0]["record_id"]})
        self.assertEqual(evidence["selected_record"]["observed_text"], "byte-level BPE")
        self.assertTrue(evidence["occurrences"])
        self.assertTrue(evidence["occurrences"][0]["provenance"][0]["declared_cluster_runtime"])

    def test_durable_backup_is_standalone_and_includes_latest_wal_commits(self):
        self.project.store.setting("fixture", "😀 committed evidence")
        target = self.project.path / "standalone.sqlite3"
        self.project.store.backup(target)
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(json.loads(db.execute("SELECT value FROM settings WHERE key='fixture'").fetchone()[0]), "😀 committed evidence")

    def test_resource_review_is_fully_inspectable_in_hash_bound_chunks(self):
        from test_cluster import ClusterTests
        from termfinder.store import digest
        fixture = ClusterTests("test_partial_resume_uses_checkpoint_and_does_not_repeat_completed_calls")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        review = fixture.prepared()
        server = MCPServer(fixture.project, cluster_storage_roots=[fixture.profile["durable_root"]])
        self.addCleanup(server.close)
        chunks, offset, hashes = [], 0, set()
        while offset is not None:
            result = server.call_tool("cluster_review_text", {"cluster_review_id": review["cluster_review_id"],
                "json_pointer": "/script_template", "offset": offset, "length": 50})
            chunks.append(result["text"])
            hashes.add(result["value_sha256"])
            offset = result["next_offset"]
        self.assertEqual("".join(chunks), review["script_template"])
        self.assertEqual(hashes, {digest(review["script_template"])})
        with self.assertRaises(ToolFailure) as failure:
            server.call_tool("cluster_review_text", {"cluster_review_id": "stale-review"})
        self.assertEqual(failure.exception.code, "cluster_review_unavailable")
        with self.assertRaises(ToolFailure):
            server.call_tool("cluster_review_text", {"cluster_review_id": review["cluster_review_id"],
                "json_pointer": "/../../unrelated-file"})

    def test_local_collection_cannot_spend_parallel_to_active_cluster_job(self):
        from test_cluster import ClusterTests
        fixture = ClusterTests("test_partial_resume_uses_checkpoint_and_does_not_repeat_completed_calls")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.submitted()
        provider = fixture.provider()
        with self.assertRaisesRegex((ValueError, RuntimeError), "cluster|allocation"):
            fixture.project.collect(provider)
        self.assertFalse(provider.calls)


if __name__ == "__main__":
    unittest.main()
