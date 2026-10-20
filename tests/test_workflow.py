"""Guided setup is a shorter interface over the same finite research contracts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from quarry import Project, FakeProvider, Response
from quarry.sources import parse_document
from quarry.store import digest
from quarry.engine import Engine
from quarry.workflow import (prepare_review, approve_review, current_review,
                                 check_review, run_review, release_dataset)
from quarry import workflow

TEXT = "😀 Our system uses byte-level BPE. I think bilingual signs improve access."


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.corpus = self.base / "corpus"
        self.corpus.mkdir()
        self.path = self.corpus / "source.md"
        self.path.write_text(TEXT, encoding="utf-8")
        self.project = Project(self.base / "study")
        self.brief = {"research_question": "Which technical expressions occur in this source?",
            "data_type": "term", "starter_recipe": "jargon", "local_roots": [str(self.corpus)],
            "languages": ["en"], "communities": ["research-corpus"], "domains": ["example.org"],
            "budget_usd": 0, "max_sources": 3, "model_profile": "fake"}
        self.configure_brief()

    def configure_brief(self):
        setup = self.project.prepare_agent_setup(self.brief)
        self.bundle = deepcopy(setup["starter_bundle"])
        self.bundle["unresolved_questions"] = []
        self.bundle["recipe"]["execution"]["concurrency"] = 1
        self.bundle["agent"]["tool"] = "offline_test_object"
        self.bundle["sources"] = [{"source_key": "local-1", "kind": "local", "locator": str(self.path),
            "metadata": {"language": "en", "community": "research-corpus", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "synthetic_fixture",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                                "permitted_use": "offline_verification", "redistribution": "fixture_only"}},
            "why_selected": "Synthetic workflow verification", "origin": "researcher_supplied",
            "search_refs": [], "family_id": "fixture-family"}]

    def provider(self):
        proposal = {"expression": "byte-level BPE", "language": "en", "sense": "A tokenization method",
                    "context": TEXT, "start": None, "definition_quote": None,
                    "translation": None, "attributes": {}}
        def response(items):
            return Response(json.dumps({"candidates": items, "coverage_complete": True}),
                            40, 40, "stop", "fixture-v1")
        return FakeProvider([], [response([proposal]), response([])])

    def prepared(self):
        review = prepare_review(self.project, self.bundle)
        self.assertTrue(review["ready"], review)
        return review

    def approved(self):
        review = self.prepared()
        approve_review(self.project, review["review_id"])
        return review

    def test_preparation_automates_freeze_and_length_estimate_without_jobs_or_provider(self):
        with patch("quarry.providers.HTTPProvider", side_effect=AssertionError("No model")), \
             patch("quarry.sources.SafeFetcher.fetch", side_effect=AssertionError("No network")):
            review = self.prepared()
        self.assertEqual(review["source_count"], 1)
        self.assertEqual(review["sources"][0]["characters"], len(TEXT))
        self.assertEqual(review["estimate"]["assumptions"]["count_only_lengths"], None)
        self.assertEqual(self.project.store.count("jobs"), 0)
        packet = Path(review["freeze"]["out"]) / "annotation_sources.jsonl"
        self.assertFalse(json.loads(packet.read_text())["complete"])
        self.assertIsNone(review["approval"])
        self.assertFalse(current_review(self.project)["stale"])

    def test_preparation_records_system_action_without_claiming_human_approval(self):
        review = self.prepared()
        history = self.project.store.read_setting("agent_workflow")
        applied = [event for event in history if event["event_type"] == "plan_applied"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["payload"]["approval"], "validated_plan_preparation")
        self.assertNotIn("collection_review_approved", {event["event_type"] for event in history})
        self.assertEqual(self.project.store.count("jobs"), 0)
        frozen = self.project.publication_audit(review["freeze"]["version_id"])
        self.assertTrue(frozen["integrity_passed"], frozen)

    def test_legacy_dispatch_after_system_preparation_cannot_claim_prior_approval(self):
        review = self.prepared()
        self.project.collect(self.provider())  # Advanced API deliberately bypasses guided approval.
        version = self.project.snapshot("unapproved-advanced-dispatch")
        report = self.project.publication_audit(version)
        self.assertFalse(report["integrity_passed"])
        self.assertIn("collection_approval_missing", {issue["code"] for issue in report["issues"]})
        approve_review(self.project, review["review_id"])
        late = self.project.publication_audit(self.project.snapshot("late-approval-declaration"))
        self.assertFalse(late["integrity_passed"])
        self.assertIn("collection_approval_missing", {issue["code"] for issue in late["issues"]})

    def test_preparation_and_approval_are_idempotent_even_after_resume(self):
        review = self.approved()
        first_approval = current_review(self.project)["approval"]
        provider = self.provider()
        partial = run_review(self.project, review["review_id"], provider=provider, max_jobs=1)
        self.assertEqual(partial["status"], "partial")
        reopened = Project(self.project.path)
        again = prepare_review(reopened)
        self.assertEqual(again["review_id"], review["review_id"])
        self.assertEqual(again["freeze"]["version_id"], review["freeze"]["version_id"])
        self.assertEqual(approve_review(reopened, review["review_id"]), first_approval)
        run_review(reopened, review["review_id"], provider=provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(reopened.store.count("versions"), 1)
        self.assertEqual(reopened.store.count("terms"), 1)
        self.assertTrue(current_review(reopened)["approved"])

    def test_captured_source_resumes_after_original_file_is_moved(self):
        review = self.approved()
        provider = self.provider()
        run_review(self.project, review["review_id"], provider=provider, max_jobs=1)
        self.path.rename(self.corpus / "original-archive.md")
        reopened = Project(self.project.path)
        again = prepare_review(reopened)
        self.assertEqual(again["review_id"], review["review_id"])
        self.assertTrue(current_review(reopened)["approved"])
        run_review(reopened, review["review_id"], provider=provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(reopened.store.count("terms"), 1)
        # An agent cannot use retained validation to approve a changed bundle.
        modified = deepcopy(self.bundle)
        modified["sources"][0]["why_selected"] = "A changed source selection"
        self.assertFalse(prepare_review(reopened, modified)["ready"])

    def test_persisted_plan_cannot_change_under_an_archived_source(self):
        review = self.approved()
        self.path.unlink()
        setup = self.project.agent_setup()
        setup["bundle"]["sources"][0]["why_selected"] = "Tampered selection"
        self.project.store.setting("agent_setup", setup)
        with self.assertRaisesRegex(ValueError, "no longer valid"):
            run_review(self.project, review["review_id"], provider=self.provider())

    def test_run_requires_explicit_approval_and_paid_authorization(self):
        review = self.prepared()
        provider = self.provider()
        with self.assertRaisesRegex(ValueError, "explicitly approve"):
            run_review(self.project, review["review_id"], provider=provider)
        self.assertFalse(provider.calls)
        approve_review(self.project, review["review_id"])
        provider.paid = True
        with self.assertRaisesRegex(ValueError, "explicit authorization"):
            run_review(self.project, review["review_id"], provider=provider)
        self.assertFalse(provider.calls)
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_agent_preflight_records_declared_approval_without_identity_claim(self):
        review = self.prepared()
        with self.assertRaisesRegex(ValueError, "explicitly approve"):
            check_review(self.project, review["review_id"])
        approval = approve_review(self.project, review["review_id"], approval_origin="agent_relay",
                                  approval_reference="Synthetic explicit user decision")
        self.assertEqual(check_review(self.project, review["review_id"])["approval_id"], approval["approval_id"])
        history = self.project.store.read_setting("agent_workflow")
        declaration = next(e for e in history if e["event_sha256"] == approval["approval_id"])["payload"]
        self.assertEqual(declaration["approval_origin"], "agent_relay")
        self.assertIn("not an authentication", declaration["identity_note"])
        saved = self.project.store.read_setting("guided_review")
        saved["approval"]["approval_id"] = "invented"
        self.project.store.setting("guided_review", saved)
        self.assertFalse(current_review(self.project)["approved"])
        with self.assertRaisesRegex(ValueError, "history integrity"):
            run_review(self.project, review["review_id"], provider=self.provider())

    def test_polling_does_not_rehash_sources_or_claim_fresh_approval(self):
        review = self.approved()
        with patch("quarry.workflow._selected", side_effect=AssertionError("No corpus scan")):
            saved = current_review(self.project, check=False)
        self.assertEqual(saved["review_id"], review["review_id"])
        self.assertTrue(saved["check_deferred"])
        self.assertFalse(saved["approval_verified"])
        self.assertIsNone(saved["stale"])

    def test_configuration_or_budget_change_invalidates_approval(self):
        review = self.approved()
        recipe = deepcopy(self.project.recipe)
        recipe["execution"]["budget_usd"] = 1
        self.project.configure(recipe, self.project.profile)
        self.assertTrue(current_review(self.project)["stale"])
        provider = self.provider()
        with self.assertRaisesRegex(ValueError, "settings changed"):
            run_review(self.project, review["review_id"], provider=provider)
        self.assertFalse(provider.calls)

    def test_source_text_and_packet_tampering_cannot_run(self):
        review = self.approved()
        packet = Path(review["freeze"]["out"]) / "annotation_sources.jsonl"
        original = packet.read_text()
        packet.write_text(original + " ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "packet changed"):
            run_review(self.project, review["review_id"], provider=self.provider())
        packet.write_text(original, encoding="utf-8")
        source_id = review["sources"][0]["source_id"]
        source = self.project.store.get("sources", source_id)
        source["text"] += " extra"
        self.project.store.put("sources", source_id, source)
        with self.assertRaisesRegex(ValueError, "content hash"):
            approve_review(self.project, review["review_id"])

    def test_streaming_packet_hash_matches_saved_unicode_hash_and_refuses_symlink(self):
        review = self.prepared()
        version = review["freeze"]["version_id"]
        packet = Path(review["freeze"]["out"]) / "annotation_sources.jsonl"
        self.assertIn("😀", packet.read_text(encoding="utf-8"))
        self.assertEqual(workflow._packet_sha256(self.project, version, packet.name),
                         digest(packet.read_text(encoding="utf-8")))
        archived = packet.with_name("preserved-packet.jsonl")
        packet.rename(archived)
        packet.symlink_to(archived.name)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            workflow._packet_sha256(self.project, version, packet.name)

    def test_sparse_packet_above_previous_size_cap_hashes_in_finite_chunks(self):
        review = self.prepared()
        version = review["freeze"]["version_id"]
        packet = Path(review["freeze"]["out"]) / "synthetic-large-packet.jsonl"
        size = 100_000_001
        with packet.open("wb") as stream:
            stream.truncate(size)  # Sparse fixture; no 100 MB Python allocation.
        expected, remaining = hashlib.sha256(), size
        chunk = b"\x00" * 65_536
        while remaining:
            length = min(len(chunk), remaining)
            expected.update(chunk[:length])
            remaining -= length
        self.assertEqual(workflow._packet_sha256(self.project, version, packet.name), expected.hexdigest())

    def test_unrelated_inventory_is_preserved_but_not_collected(self):
        review = self.approved()
        unrelated = self.project.add_source(parse_document(b"Another document has byte-level BPE.",
            "text/plain", "unrelated.txt", {"language": "en", "community": "research-corpus"}))
        provider = self.provider()
        run_review(self.project, review["review_id"], provider=provider)
        self.assertEqual(self.project.store.count("sources"), 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn(unrelated, {j["source_id"] for j in self.project.store.all("jobs")})

    def test_preexisting_pending_jobs_outside_review_cannot_dispatch(self):
        review = self.approved()
        unrelated = self.project.add_source(parse_document(b"Another document has byte-level BPE.",
            "text/plain", "unrelated.txt", {"language": "en", "community": "research-corpus"}))
        # Prepare legacy jobs without dispatching; preserve this older inventory.
        with self.project._lock():
            Engine(self.project, FakeProvider([])).prepare()
        pending = {j["job_id"] for j in self.project.store.all("jobs") if j["source_id"] == unrelated}
        self.assertEqual(len(pending), 2)
        provider = self.provider()
        result = run_review(self.project, review["review_id"], provider=provider)
        self.assertTrue(pending.isdisjoint(provider.calls))
        self.assertEqual({self.project.store.get("jobs", job)["status"] for job in pending}, {"pending"})
        self.assertEqual(result["review_scope"]["coverage"]["roots"], 2)
        self.assertEqual(result["review_scope"]["jobs"], {"done": 2})
        self.assertEqual(result["jobs"]["pending"], 2)
        self.assertEqual(result["review_scope"]["eligible_source_count"], 1)

    def test_source_map_cannot_substitute_another_document(self):
        review = self.approved()
        unrelated = self.project.add_source(parse_document(TEXT.encode(), "text/plain", "unrelated.txt",
                                             {"language": "en", "community": "research-corpus"}))
        mapping = self.project.store.read_setting("agent_source_map")
        mapping[next(iter(mapping))] = unrelated
        self.project.store.setting("agent_source_map", mapping)
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            run_review(self.project, review["review_id"], provider=self.provider())

    def test_scope_expansion_rejected_and_pending_websites_do_not_silently_fetch(self):
        bad = deepcopy(self.bundle)
        bad["recipe"]["source_scope"]["domains"] = ["outside.example"]
        self.assertFalse(prepare_review(self.project, bad)["ready"])
        self.assertIsNone(self.project.recipe)
        remote = deepcopy(self.bundle["sources"][0])
        remote.update(source_key="web-2", kind="url", locator="https://example.org/article", family_id="web-family")
        self.bundle["sources"].append(remote)
        with patch("quarry.sources.SafeFetcher.fetch", side_effect=AssertionError("No network")):
            review = prepare_review(self.project, self.bundle)
        self.assertFalse(review["ready"])
        self.assertEqual(review["pending_sources"][0]["source_key"], "web-2")
        with self.assertRaisesRegex(ValueError, "pending sources"):
            approve_review(self.project, review["review_id"])

    def test_explicit_fetch_failures_remain_visible_while_local_sources_are_usable(self):
        remote = deepcopy(self.bundle["sources"][0])
        remote.update(source_key="web-2", kind="url", locator="https://example.org/article")
        self.bundle["sources"].append(remote)
        with patch("quarry.sources.SafeFetcher.fetch", side_effect=ValueError("synthetic_failure")) as fetch:
            review = prepare_review(self.project, self.bundle, fetch_remote=True)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(review["ready"])
        self.assertEqual(len(review["failures"]), 1)
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_existing_blind_freeze_is_reused_after_legacy_collection(self):
        self.project.apply_agent_bundle(self.bundle)
        frozen = self.project.freeze_agent_corpus()
        self.project.collect(self.provider(), max_jobs=1)
        review = prepare_review(self.project)
        self.assertEqual(review["freeze"]["version_id"], frozen["version_id"])
        approve_review(self.project, review["review_id"])
        run_review(self.project, review["review_id"], provider=FakeProvider([]))
        self.assertEqual(self.project.store.count("versions"), 1)

    def test_unfrozen_previously_processed_sources_cannot_be_retroactively_blind(self):
        self.project.apply_agent_bundle(self.bundle)
        self.project.collect(self.provider(), max_jobs=1)
        with self.assertRaisesRegex(ValueError, "already prepared"):
            prepare_review(self.project)

    def test_budget_stop_keeps_pending_jobs_and_does_not_dispatch(self):
        self.brief["model_profile"] = "glm-deepseek"
        self.configure_brief()
        review = self.approved()
        self.assertGreater(review["estimate"]["range_usd"][0], 0)
        provider = self.provider()
        result = run_review(self.project, review["review_id"], provider=provider)
        self.assertFalse(provider.calls)
        self.assertEqual(result["status"], "partial")
        self.assertIn("budget", result["stop_reason"])
        self.assertGreater(result["jobs"]["pending"], 0)

    def test_collection_lock_spans_review_check_and_provider_call(self):
        review = self.approved()
        other = Project(self.project.path)
        provider = self.provider()
        original = provider.complete
        held = []
        def checked(request):
            try:
                other.configure(other.recipe, other.profile)
            except RuntimeError:
                held.append(True)
            else:
                raise AssertionError("configuration changed during approved admission")
            return original(request)
        provider.complete = checked
        run_review(self.project, review["review_id"], provider=provider)
        self.assertEqual(held, [True, True])

    def test_cancel_during_startup_checks_survives_admission_and_can_resume(self):
        review = self.approved()
        provider = self.provider()
        run_review(self.project, review["review_id"], provider=provider, max_jobs=1)
        self.assertEqual(len(provider.calls), 1)
        entered, release = threading.Event(), threading.Event()
        original = workflow._check_review_unlocked
        results, errors = [], []
        def blocked_check(project, review_id):
            entered.set()
            if not release.wait(3):
                raise AssertionError("finite startup test deadline")
            return original(project, review_id)
        def run():
            try:
                results.append(run_review(self.project, review["review_id"], provider=provider))
            except BaseException as error:
                errors.append(error)
        with patch("quarry.workflow._check_review_unlocked", side_effect=blocked_check):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(3), "review check did not start")
                self.project.cancel()
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive(), "startup did not finish within its bound")
        self.assertEqual(errors, [])
        self.assertEqual(results[0]["status"], "cancelled")
        self.assertTrue(self.project.store.read_setting("cancel_requested"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(self.project.store.status_counts("jobs"), {"done": 1, "pending": 1})
        run_review(self.project, review["review_id"], provider=provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(self.project.store.status_counts("jobs"), {"done": 2})

    def test_named_release_is_reproducible_and_does_not_call_models(self):
        review = self.approved()
        run_review(self.project, review["review_id"], provider=self.provider())
        released = release_dataset(self.project, "release-one")
        self.assertTrue(released["audit"]["integrity_passed"], released["audit"])
        self.assertIn("records.parquet", released["files"])
        before = {p.name: p.read_bytes() for p in Path(released["out"]).iterdir()}
        self.project.annotate(self.project.store.all("terms")[0]["term_id"], "approved")
        with patch("quarry.workflow.HTTPProvider", side_effect=AssertionError("No model")):
            again = release_dataset(self.project, "release-one")
        self.assertEqual(again["version_id"], released["version_id"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in Path(again["out"]).iterdir()})
        second = release_dataset(self.project, "release-two")
        self.assertNotEqual(second["version_id"], released["version_id"])
        self.assertEqual(self.project.dataset(second["version_id"])["records"][0]["review_status"], "approved")

    def test_export_failure_retries_same_snapshot_and_active_runs_cannot_release(self):
        review = self.approved()
        run_review(self.project, review["review_id"], provider=self.provider())
        with patch.object(self.project, "export", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                release_dataset(self.project, "retry-release", formats=["jsonl"])
        expected = self.project.store.read_setting("guided_releases")["retry-release"]
        versions = self.project.store.count("versions")
        self.assertEqual(release_dataset(self.project, "retry-release", formats=["jsonl"])["version_id"], expected)
        self.assertEqual(self.project.store.count("versions"), versions)
        self.project.store.put("runs", "synthetic-running", {"run_id": "synthetic-running", "status": "running"})
        with self.assertRaisesRegex(ValueError, "active collection"):
            release_dataset(self.project, "cannot-release", formats=["jsonl"])


if __name__ == "__main__":
    unittest.main()
