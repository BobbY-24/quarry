"""Contracts for the simple UI without models, browsers, or network transport."""
import io
from copy import deepcopy
import json
import os
import tempfile
import threading
import unittest
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from termfinder import Project
from termfinder.web import Handler, ResearchServer, STATIC, MAX_DOWNLOAD, _read_artifact, _review_state, _setup_revision, _agent_setup_state


def request(path, body=None, *, running=False):
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(project=SimpleNamespace(store=object()), token="session",
        host="127.0.0.1:8765", origin="http://127.0.0.1:8765",
        worker=SimpleNamespace(is_alive=lambda: True) if running else None,
        worker_error=None, worker_result=None, allow_paid=False)
    handler.path = path
    handler.headers = Message()
    for name, value in (("Host", handler.server.host), ("Origin", handler.server.origin),
                        ("X-Termfinder-Token", "session"), ("Content-Type", "application/json")):
        handler.headers[name] = value
    data = json.dumps(body or {}).encode("utf-8")
    handler.headers["Content-Length"] = str(len(data))
    handler.rfile = io.BytesIO(data)
    handler.responses = []
    handler._send = lambda code, result, content_type=None, **kwargs: handler.responses.append((code, result, kwargs))
    return handler


class Layout(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.visible_brief_controls, self.ids, self.tabs = [], [], [], []

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if attrs.get("role") == "tab":
            self.tabs.append(attrs)
        if tag in {"select", "input", "textarea"}:
            in_brief = any(parent.get("id") == "agent-setup" for _, parent in self.stack)
            concealed = any("hidden" in parent or name == "details" and "open" not in parent for name, parent in self.stack)
            if in_brief and not concealed:
                self.visible_brief_controls.append(attrs.get("id"))
        if tag not in {"input", "meta", "link", "br", "hr", "img"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break


class SimpleBrowserTests(unittest.TestCase):
    def test_default_brief_only_exposes_question_type_scope_and_budget(self):
        layout = Layout()
        layout.feed((STATIC / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(layout.visible_brief_controls,
            ["brief-data-type", "brief-question", "brief-domains", "brief-local-roots", "brief-budget"])
        self.assertEqual(len(layout.ids), len(set(layout.ids)))
        self.assertEqual([tab["id"] for tab in layout.tabs], ["tab-plan", "tab-evidence", "tab-dataset"])
        self.assertEqual([tab["aria-selected"] for tab in layout.tabs], ["true", "false", "false"])
        for tab in layout.tabs:
            self.assertIn(tab["aria-controls"], layout.ids)

    def test_bundle_and_uuid_are_disclosed_fallbacks_not_ordinary_controls(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        for disclosure in ("brief-advanced", "chat-agent-help", "agent-bundle-import", "advanced-dataset"):
            self.assertIn(f'id="{disclosure}"', html)
            self.assertNotIn(f'id="{disclosure}" open', html)
        for feature in ("human-attribute-fields", "relation-search", "relation-choice", "approve-start", "release-dataset"):
            self.assertIn(f'id="{feature}"', html)
        self.assertIn("renderAttributeFields(latest?.attributes||{})", script)
        self.assertIn("attributes:readHumanAttributes()", script)
        self.assertIn("max_jobs:number('max-jobs')", script)
        for unsafe in ("innerHTML", "eval(", "new Function(", "document.write("):
            self.assertNotIn(unsafe, script)

    def test_combined_prepare_passes_only_bundle_and_explicit_fetch_decision(self):
        bundle = {"sources": []}
        handler = request("/api/review", {"bundle_text": json.dumps(bundle), "fetch_remote": True,
            "allow_paid": True, "urls": ["https://outside.example"]})
        with patch("termfinder.workflow.prepare_review", return_value={"review_id": "r1", "ready": True}) as prepare:
            handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        prepare.assert_called_once_with(handler.server.project, bundle=bundle, fetch_remote=True)

    def test_fetch_requires_boolean_and_plan_requires_unique_object(self):
        for body in ({"fetch_remote": "yes"}, {"bundle_text": "[]"},
                     {"bundle_text": '{"sources":[],"sources":[{}]}'}, {"fetch_remote": 1}):
            handler = request("/api/review", body)
            with patch("termfinder.workflow.prepare_review") as prepare:
                handler.do_POST()
            self.assertEqual(handler.responses[0][0], 400)
            prepare.assert_not_called()

    def test_approval_and_release_do_not_collect(self):
        handler = request("/api/review/approve", {"review_id": "r1", "allow_paid": True})
        with patch("termfinder.workflow.approve_review", return_value={"approval_id": "a1"}) as approve, \
             patch("termfinder.workflow.run_review") as run:
            handler.do_POST()
        approve.assert_called_once_with(handler.server.project, "r1")
        run.assert_not_called()
        self.assertEqual(handler.responses[0][0], 200)
        handler = request("/api/release", {"name": "study-v1", "allow_paid": True})
        with patch("termfinder.workflow.release_dataset", return_value={"version_id": "d1"}) as release, \
             patch("termfinder.workflow.run_review") as run:
            handler.do_POST()
        release.assert_called_once_with(handler.server.project, "study-v1",
            formats=["csv", "jsonl", "parquet", "annotation"], version_id=None)
        run.assert_not_called()
        self.assertEqual(handler.responses[0][0], 200)

    def test_running_worker_blocks_prepare_approval_and_release(self):
        for path in ("/api/review", "/api/review/approve", "/api/release"):
            handler = request(path, {"review_id": "r1"}, running=True)
            with patch("termfinder.workflow.prepare_review") as prepare, \
                 patch("termfinder.workflow.approve_review") as approve, \
                 patch("termfinder.workflow.release_dataset") as release:
                handler.do_POST()
            self.assertEqual(handler.responses[0][0], 400)
            for call in (prepare, approve, release):
                call.assert_not_called()

    def test_same_origin_token_still_required_for_all_workflow_mutations(self):
        for path in ("/api/review", "/api/review/approve", "/api/review/run", "/api/release"):
            for name, value in (("Origin", "https://outside.example"), ("X-Termfinder-Token", "wrong")):
                handler = request(path, {"review_id": "r1"})
                handler.headers.replace_header(name, value)
                handler.do_POST()
                self.assertEqual(handler.responses[0][0], 403)

    def test_reviewed_worker_uses_saved_admission_and_never_hides_real_profile(self):
        server = ResearchServer.__new__(ResearchServer)
        server.project = SimpleNamespace(profile={"id": "fake"}, store=SimpleNamespace(setting=lambda *args: None))
        server.allow_paid, server.worker, server.worker_lock = False, None, threading.Lock()
        with patch("termfinder.workflow.run_review", return_value={"status": "complete"}) as run, \
             patch("termfinder.workflow.check_review", return_value={"ready": True}) as preflight:
            result = server.start_collection(max_jobs=1, review_id="review-1")
            server.worker.join(2)
        self.assertFalse(server.worker.is_alive())
        self.assertTrue(result["offline"])
        preflight.assert_called_once_with(server.project, "review-1", allow_paid=False)
        self.assertEqual(run.call_args.args, (server.project, "review-1"))
        self.assertEqual(run.call_args.kwargs["max_jobs"], 1)
        self.assertFalse(run.call_args.kwargs["provider"].paid)
        server.project.profile = {"id": "glm-deepseek"}
        with self.assertRaisesRegex(ValueError, "offline fake"):
            server.start_collection(review_id="review-1")

    def test_stale_or_unapproved_review_is_rejected_before_worker_creation(self):
        server = ResearchServer.__new__(ResearchServer)
        server.project = SimpleNamespace(profile={"id": "fake"})
        server.allow_paid, server.worker, server.worker_lock = False, None, threading.Lock()
        for reason in ("This collection review is outdated", "Explicit approval is required"):
            with patch("termfinder.workflow.check_review", side_effect=ValueError(reason)), \
                 patch("termfinder.workflow.run_review") as run:
                with self.assertRaisesRegex(ValueError, reason):
                    server.start_collection(review_id="review-1")
            self.assertIsNone(server.worker)
            run.assert_not_called()

    def test_polling_review_is_lightweight_but_explicit_review_rechecks(self):
        project = SimpleNamespace(store=object())
        with patch("termfinder.workflow.current_review", return_value={"review_id": "r1"}) as review:
            _review_state(project)
            _review_state(project, check=True)
        self.assertEqual(review.call_args_list[0].kwargs, {"check": False})
        self.assertEqual(review.call_args_list[1].kwargs, {"check": True})

    def test_native_agent_changes_have_lightweight_revision_and_read_only_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus"
            corpus.mkdir()
            source = corpus / "fixture.md"
            source.write_text("This corpus uses byte-level BPE.", encoding="utf-8")
            project = Project(root / "study")
            self.assertIsNone(_setup_revision(project))
            setup = project.prepare_agent_setup({"research_question": "Which technical terms occur?",
                "data_type": "term", "starter_recipe": "jargon", "local_roots": [str(corpus)],
                "budget_usd": 0, "model_profile": "fake", "max_sources": 1})
            first = _setup_revision(project)
            self.assertEqual(first, setup["event_sha256"])
            bundle = deepcopy(setup["starter_bundle"])
            bundle["unresolved_questions"] = []
            bundle["sources"] = [{"source_key": "local-1", "kind": "local", "locator": str(source),
                "metadata": {"language": "en", "community": "research-corpus", "domain": "synthetic",
                    "publication_date": None, "publication_date_reason": "synthetic_fixture",
                    "constraints": {"content_origin": "synthetic_fixture", "license": "test-only"}},
                "why_selected": "Synthetic browser revision check", "origin": "researcher_supplied",
                "search_refs": [], "family_id": "fixture-family"}]
            self.assertTrue(project.validate_agent_bundle(bundle)["valid"])
            project.store.setting("agent_proposal", bundle)
            before_events = project.store.read_setting("agent_workflow")
            read = _agent_setup_state(project)
            self.assertEqual(read["proposed_bundle"], bundle)
            self.assertEqual(read["ui_setup_revision"], first)
            self.assertEqual(project.store.read_setting("agent_workflow"), before_events)
            self.assertEqual(project.store.count("jobs"), 0)
            project.apply_agent_bundle(bundle)
            self.assertNotEqual(_setup_revision(project), first)
            self.assertNotIn("proposed_bundle", _agent_setup_state(project))
            handler = request("/api/state")
            handler.server.project = project
            handler.do_GET()
            self.assertEqual(handler.responses[0][0], 200)
            self.assertEqual(handler.responses[0][1]["setup_revision"], _setup_revision(project))
            self.assertNotIn("proposed_bundle", handler.responses[0][1])
            self.assertNotIn("agent_setup", handler.responses[0][1])
            self.assertEqual(project.store.count("jobs"), 0)

    def test_download_reads_only_saved_regular_files_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exports = root / "exports" / "dataset-1"
            exports.mkdir(parents=True)
            (exports / "records.csv").write_bytes(b"observed_text\nfixture\n")
            project = SimpleNamespace(path=root)
            self.assertEqual(_read_artifact(project, "exports/dataset-1/records.csv"),
                (b"observed_text\nfixture\n", "records.csv"))
            for path in ("/exports/dataset-1/records.csv", "exports/dataset-1/../records.csv",
                         "exports//dataset-1/records.csv", "exports/dataset-1/.env",
                         "agent-inputs/dataset-1/records.csv", "exports/dataset-1/records.py"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    _read_artifact(project, path)
            (exports / "linked.csv").symlink_to(exports / "records.csv")
            with self.assertRaises(OSError):
                _read_artifact(project, "exports/dataset-1/linked.csv")
            (root / "human-review").symlink_to(root / "exports", target_is_directory=True)
            with self.assertRaises(OSError):
                _read_artifact(project, "human-review/dataset-1/records.csv")
            with (exports / "large.csv").open("wb") as stream:
                stream.truncate(MAX_DOWNLOAD + 1)
            with self.assertRaisesRegex(ValueError, "20 MB"):
                _read_artifact(project, "exports/dataset-1/large.csv")
            os.mkfifo(exports / "pipe.csv")
            with self.assertRaisesRegex(ValueError, "regular file"):
                _read_artifact(project, "exports/dataset-1/pipe.csv")

    def test_download_endpoint_requires_authentication(self):
        handler = request("/api/download?path=exports/dataset-1/records.csv")
        handler.headers.replace_header("X-Termfinder-Token", "wrong")
        with patch("termfinder.web._read_artifact") as read:
            handler.do_GET()
        self.assertEqual(handler.responses[0][0], 403)
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
