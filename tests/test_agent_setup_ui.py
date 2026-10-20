"""Browser contract checks for the external-agent setup boundary.

No provider, transport or model is used. The project fake records delegated
operations so the tests can detect an accidental prepare/apply collection call.
"""
import io
import json
import unittest
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from quarry.web import Handler, ResearchServer, STATIC


class PlanProject:
    def __init__(self):
        self.calls = []

    def agent_setup(self):
        return {"brief": None, "prompt": None, "history": []}

    def prepare_agent_setup(self, brief):
        self.calls.append(("prepare", brief))
        return {"brief": brief, "prompt": "External agent request", "starter_bundle": {"schema_version": 1}}

    def validate_agent_bundle(self, bundle):
        self.calls.append(("validate", bundle))
        return {"valid": False, "errors": [{"path": "sources[0].locator", "code": "scope", "message": "Source is outside your permitted domains"}], "warnings": [], "repair_prompt": "Fix the source list"}

    def apply_agent_bundle(self, bundle):
        self.calls.append(("apply", bundle))
        return {"valid": True, "source_ids": ["local-source"], "estimate": {"total_usd": [0, 0]}}

    def ingest_agent_sources(self):
        self.calls.append(("ingest_reviewed",))
        return {"source_ids": ["reviewed-source"]}

    def publication_audit(self, version):
        self.calls.append(("publication_audit", version))
        return {"integrity_passed": True, "requires_researcher_review": True, "issues": [], "limitations": ["No recall measurement"]}

    def freeze_agent_corpus(self, *, name, seed):
        self.calls.append(("freeze_agent_corpus", name, seed))
        return {"version_id": "corpus-1", "out": "/synthetic/project/review", "source_count": 1, "annotation_files": ["annotation_sources.jsonl"]}


def request(path, body=None, raw=None, running=False):
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(project=PlanProject(), token="session", host="127.0.0.1:8765", origin="http://127.0.0.1:8765", worker=SimpleNamespace(is_alive=lambda: True) if running else None)
    handler.path = path
    handler.headers = Message()
    handler.headers["Host"] = handler.server.host
    handler.headers["Origin"] = handler.server.origin
    handler.headers["X-Termfinder-Token"] = handler.server.token
    data = raw.encode("utf-8") if raw is not None else json.dumps(body or {}).encode("utf-8")
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = str(len(data))
    handler.rfile = io.BytesIO(data)
    handler.responses = []
    handler._send = lambda code, result, content_type=None: handler.responses.append((code, result))
    return handler


class FormNames(HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls = []
        self.labels = {}
        self.current_label = None
        self.nested_controls = []

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == "label":
            self.current_label = attrs.get("for")
            self.labels.setdefault(self.current_label, "")
        if tag in {"input", "textarea", "select"}:
            self.controls.append(attrs)
            if self.current_label is not None:
                self.nested_controls.append(attrs.get("id"))

    def handle_data(self, data):
        if self.current_label is not None:
            self.labels[self.current_label] += data

    def handle_endtag(self, tag):
        if tag == "label":
            self.current_label = None


class ReportVisibility(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.elements = {}

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if "id" in attrs:
            self.elements[attrs["id"]] = {"tag": tag, "closed_disclosure": any(parent == "details" and "open" not in values for parent, values in self.stack)}
        if tag not in {"input", "meta", "link", "br", "hr", "img"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break


class AgentSetupBrowserTests(unittest.TestCase):
    def test_saved_setup_get_is_read_only(self):
        handler = request("/api/agent-setup")
        handler.do_GET()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.server.project.calls, [])

    def test_prepare_only_delegates_the_human_brief(self):
        brief = {"data_type": "opinion", "research_question": "Which opinions occur?", "budget_usd": 0}
        handler = request("/api/agent-setup/prepare", {"brief": brief})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.server.project.calls, [("prepare", brief)])

    def test_invalid_plan_returns_repair_report_without_apply(self):
        bundle = {"sources": [{"locator": "https://outside.example/paper"}]}
        handler = request("/api/agent-setup/validate", {"bundle_text": json.dumps(bundle)})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertFalse(handler.responses[0][1]["valid"])
        self.assertIn("repair_prompt", handler.responses[0][1])
        self.assertEqual(handler.server.project.calls, [("validate", bundle)])

    def test_apply_delegates_only_bundle_and_remote_fetch_is_separate(self):
        bundle = {"sources": [{"kind": "local", "locator": "/corpus/a.txt"}]}
        handler = request("/api/agent-setup/apply", {"bundle": bundle, "allow_paid": True, "urls": ["https://outside.example"]})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.server.project.calls, [("apply", bundle)])
        handler = request("/api/agent-setup/ingest", {"urls": ["https://outside.example"]})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.server.project.calls, [("ingest_reviewed",)])

    def test_plan_must_be_object_and_duplicate_keys_are_rejected(self):
        for bundle_text in ('[]', '{"sources":[],"sources":[{}]}', '{"budget":NaN}'):
            handler = request("/api/agent-setup/apply", {"bundle_text": bundle_text})
            handler.do_POST()
            self.assertEqual(handler.responses[0][0], 400)
            self.assertEqual(handler.server.project.calls, [])

    def test_malformed_plan_has_readable_location_without_echoing_input(self):
        handler = request("/api/agent-setup/validate", {"bundle_text": '{"source-secret-marker":'})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 400)
        self.assertIn("line 1, column", handler.responses[0][1]["error"])
        self.assertNotIn("source-secret-marker", handler.responses[0][1]["error"])
        self.assertEqual(handler.server.project.calls, [])

    def test_untrusted_origin_cannot_prepare_apply_or_fetch(self):
        for path in ("prepare", "validate", "apply", "ingest", "freeze"):
            handler = request("/api/agent-setup/" + path, {"brief": {}, "bundle": {}})
            handler.headers.replace_header("Origin", "https://outside.example")
            handler.do_POST()
            self.assertEqual(handler.responses[0][0], 403)
            self.assertEqual(handler.server.project.calls, [])

    def test_collection_blocks_plan_mutations_and_remote_ingestion(self):
        for path in ("prepare", "apply", "ingest", "freeze"):
            handler = request("/api/agent-setup/" + path, {"brief": {}, "bundle": {}}, running=True)
            handler.do_POST()
            self.assertEqual(handler.responses[0][0], 400)
            self.assertEqual(handler.server.project.calls, [])

    def test_real_profile_never_silently_runs_fake_collection(self):
        server = ResearchServer.__new__(ResearchServer)
        server.allow_paid = False
        server.project = SimpleNamespace(profile={"id": "glm-deepseek"})
        with self.assertRaisesRegex(ValueError, "offline fake profile"):
            server.start_collection()

    def test_saved_version_audit_is_explicit_and_does_not_collect(self):
        handler = request("/api/publication-audit", {"version": "dataset-1"})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.server.project.calls, [("publication_audit", "dataset-1")])

    def test_blind_source_packets_delegate_only_freeze_without_collection(self):
        handler = request("/api/agent-setup/freeze", {})
        handler.do_POST()
        self.assertEqual(handler.responses[0][0], 200)
        self.assertEqual(handler.server.project.calls, [("freeze_agent_corpus", "corpus-v1", "v6-agent-study-v1")])

    def test_default_interface_hides_manual_json_and_keeps_inert_rendering(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="advanced-setup"', html)
        self.assertNotIn('id="advanced-setup" open', html)
        self.assertIn('id="apply-agent-bundle" disabled', html)
        self.assertIn("validatedBundleText===$('agent-bundle').value", script)
        self.assertIn("bundle_text:checkedText", script)
        for dangerous in ("innerHTML", "eval(", "new Function(", "document.write("):
            self.assertNotIn(dangerous, script)

    def test_every_form_control_has_a_stable_explicit_accessible_name(self):
        parser = FormNames()
        parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(parser.controls)
        self.assertEqual(parser.nested_controls, [])
        for control in parser.controls:
            with self.subTest(control=control.get("id")):
                name = control.get("aria-label") or parser.labels.get(control.get("id"))
                self.assertIsInstance(name, str)
                self.assertTrue(name.strip())
        self.assertEqual(parser.labels["brief-data-type"], "What do you want to collect?")
        self.assertEqual(parser.labels["brief-mode"], "Collection mode")
        self.assertEqual(parser.labels["brief-profile"], "Model profile")
        self.assertEqual(list(parser.labels.values()).count("Model profile"), 1)

    def test_progress_cost_and_export_raw_reports_start_collapsed(self):
        parser = ReportVisibility()
        parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
        for record in ("progress", "estimate-result", "export-result"):
            with self.subTest(record=record):
                self.assertEqual(parser.elements[record]["tag"], "div")
                self.assertFalse(parser.elements[record]["closed_disclosure"])
        for record in ("progress-json", "estimate-json", "export-json", "audit", "term-detail"):
            with self.subTest(raw_report=record):
                self.assertEqual(parser.elements[record]["tag"], "pre")
                self.assertTrue(parser.elements[record]["closed_disclosure"])

    def test_definition_fixture_matches_structured_public_record_contract(self):
        from quarry.exports import record_view
        fixtures = json.loads((Path(__file__).parent / "fixtures/ui_definition_records.json").read_text(encoding="utf-8"))
        records = {row["record_id"]: row for row in record_view(fixtures)}
        present = records["term-quote-present"]["source_support_quote"]
        absent = records["record-quote-absent"]["source_support_quote"]
        self.assertIsInstance(present, dict)
        self.assertEqual(present["text"], "a pause 🧪")
        self.assertFalse(present["semantic_entailment_verified"])
        self.assertIsNone(absent["text"])
        self.assertEqual(absent["reason"], "no_exact_definition_quote")
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("const support=explanatoryQuote(record)", script)
        self.assertIn("appendText(root,'blockquote',support.text)", script)
        self.assertNotIn("appendText(root,'blockquote',support)", script)


if __name__ == "__main__":
    unittest.main()
