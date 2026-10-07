"""Offline protocol and research-boundary verification with inert fixtures."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from termfinder import Project, FakeProvider, Response
from termfinder import mcp_server
from termfinder.mcp_server import MCPServer, decode_json, write_skill
from termfinder.workflow import run_review

TEXT = "😀 Our system uses byte-level BPE. I think bilingual signs improve access."
ROOT = Path(__file__).resolve().parents[1]


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.corpus = self.base / "corpus"
        self.corpus.mkdir()
        self.source = self.corpus / "source.md"
        self.source.write_text(TEXT, encoding="utf-8")
        self.project = Project(self.base / "project")
        self.server = MCPServer(self.project)
        self.addCleanup(self.server.close)
        self.brief = {"research_question": "Which technical expressions occur in this source?",
                      "data_type": "term", "starter_recipe": "jargon", "local_roots": [str(self.corpus)],
                      "languages": ["en"], "communities": ["research-corpus"], "domains": ["example.org"],
                      "budget_usd": 0, "max_sources": 2, "model_profile": "fake"}

    def init(self, server=None, protocol="2025-06-18"):
        server = server or self.server
        result = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": protocol, "capabilities": {}, "clientInfo": {"name": "offline-fixture", "version": "1"}}})
        server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def bundle(self, server=None):
        server = server or self.server
        setup = server.call_tool("prepare_study", {"brief": self.brief})
        bundle = deepcopy(setup["starter_bundle"])
        bundle["unresolved_questions"] = []
        bundle["recipe"]["execution"]["concurrency"] = 1
        bundle["agent"]["tool"] = "offline_fixture"
        bundle["sources"] = [{"source_key": "source-1", "kind": "local", "locator": str(self.source),
            "metadata": {"language": "en", "community": "research-corpus", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "synthetic_fixture",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                                "permitted_use": "offline_verification", "redistribution": "fixture_only"}},
            "why_selected": "Synthetic protocol verification", "origin": "researcher_supplied",
            "search_refs": [], "family_id": "synthetic-family"}]
        return bundle

    def prepared(self):
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": self.bundle()})["valid"])
        return self.server.call_tool("prepare_review", {})

    def approved(self):
        review = self.prepared()
        self.server.call_tool("approve_review", {"review_id": review["review_id"],
            "researcher_approved": True, "approval_reference": "Synthetic researcher decision in test."})
        return review

    def with_record(self):
        review = self.approved()
        proposal = {"expression": "byte-level BPE", "language": "en", "sense": "A tokenization method",
                    "context": TEXT, "start": None, "definition_quote": None, "translation": None, "attributes": {}}
        def response(items):
            return Response(json.dumps({"candidates": items, "coverage_complete": True}), 40, 40, "stop", "fixture-v1")
        run_review(self.project, review["review_id"], provider=FakeProvider([], [response([proposal]), response([])]))
        return self.project.store.all("terms")[0]["term_id"]

    def test_supported_protocols_negotiate_and_unknown_version_returns_supported_one(self):
        for protocol in (*mcp_server.PROTOCOLS, "2099-01-01"):
            server = MCPServer(self.project)
            result = self.init(server, protocol)
            self.assertEqual(result["result"]["protocolVersion"], protocol if protocol in mcp_server.PROTOCOLS else mcp_server.PROTOCOLS[-1])
            self.assertEqual(result["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(self.server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"], {})

    def test_lifecycle_requires_initialized_and_notifications_do_not_execute_tools(self):
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        self.assertEqual(self.server.dispatch(request)["error"]["code"], -32002)
        noid = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "prepare_study", "arguments": {"brief": self.brief}}}
        self.assertIsNone(self.server.dispatch(noid))
        self.assertFalse(self.project.agent_setup())
        self.init()
        self.assertTrue(self.server.dispatch(request)["result"]["tools"])
        again = self.server.dispatch({"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}})
        self.assertEqual(again["error"]["code"], -32600)

    def test_protocol_malformed_duplicates_nonfinite_and_unknown_arguments_fail_safely(self):
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e10000}'):
            with self.assertRaises(ValueError):
                decode_json(value)
        self.assertEqual(self.server.dispatch([{"jsonrpc": "2.0"}])["error"]["code"], -32600)
        self.init()
        for params in ({"name": "status", "arguments": {"project": "/outside"}},
                       {"name": "collect", "arguments": {"review_id": "r", "allow_paid": True}},
                       {"name": "records", "arguments": {"limit": True}},
                       {"name": "records", "arguments": {"limit": 101}},
                       {"name": "release", "arguments": {"name": "v", "out": "/outside"}}):
            result = self.server.dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": params})
            self.assertTrue(result["result"]["isError"], params)
        with self.assertRaises(ValueError):
            self.server.call_tool("release", {"name": "v", "version_id": "../outside"})
        unknown = self.server.dispatch({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "execute_shell", "arguments": {}}})
        self.assertEqual(unknown["error"]["code"], -32602)

    def test_invalid_secret_input_and_exception_bodies_never_echo_to_protocol(self):
        self.init()
        marker = "secret-marker-not-a-real-credential"
        result = self.server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "prepare_study", "arguments": {"brief": dict(self.brief, api_key=marker)}}})
        self.assertTrue(result["result"]["isError"])
        self.assertNotIn(marker, json.dumps(result))
        with patch.object(self.project, "status", side_effect=RuntimeError(marker)):
            result = self.server.dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "status"}})
        self.assertNotIn(marker, json.dumps(result))

    def test_plan_submission_is_inert_then_preparation_freezes_without_model_calls(self):
        bundle = self.bundle()
        with patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("No URL fetch")), \
             patch("termfinder.workflow.HTTPProvider", side_effect=AssertionError("No paid provider")):
            result = self.server.call_tool("submit_plan", {"bundle": bundle})
            self.assertTrue(result["valid"])
            self.assertIsNone(self.project.recipe)
            self.assertEqual(self.project.store.count("sources"), 0)
            review = self.server.call_tool("prepare_review", {})
        self.assertTrue(review["ready"])
        self.assertEqual(self.project.store.count("jobs"), 0)
        packet = json.loads((Path(review["freeze"]["out"]) / "annotation_sources.jsonl").read_text())
        self.assertFalse(packet["complete"])

    def test_scope_expansion_and_invalid_plan_do_not_replace_valid_proposal(self):
        bundle = self.bundle()
        self.server.call_tool("submit_plan", {"bundle": bundle})
        original_revision = self.project.store.read_setting("ui_setup_revision")
        self.assertTrue(original_revision)
        bad = deepcopy(bundle)
        bad["recipe"]["source_scope"]["domains"] = ["outside.example"]
        self.assertFalse(self.server.call_tool("submit_plan", {"bundle": bad})["valid"])
        self.assertEqual(self.project.store.read_setting("agent_proposal"), bundle)
        self.assertEqual(self.project.store.read_setting("ui_setup_revision"), original_revision)
        revised = deepcopy(bundle)
        revised["sources"][0]["why_selected"] = "Revised permitted sampling rationale"
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": revised})["valid"])
        self.assertNotEqual(self.project.store.read_setting("ui_setup_revision"), original_revision)

    def test_approval_is_required_and_relay_is_recorded_as_declaration(self):
        review = self.prepared()
        with self.assertRaises(ValueError):
            self.server.call_tool("collect", {"review_id": review["review_id"]})
        for approval in (False, None):
            args = {"review_id": review["review_id"], "researcher_approved": approval, "approval_reference": "test"}
            with self.assertRaises(ValueError):
                self.server.call_tool("approve_review", args)
        self.server.call_tool("approve_review", {"review_id": review["review_id"], "researcher_approved": True, "approval_reference": "Human decision in synthetic test"})
        event = [e for e in self.project.store.read_setting("agent_workflow") if e["event_type"] == "collection_review_approved"][-1]
        self.assertEqual(event["payload"]["approval_origin"], "agent_relay")
        self.assertIn("not an authentication", event["payload"]["identity_note"])

    def test_launch_paid_gate_cannot_be_enabled_by_tool_input(self):
        self.brief["model_profile"] = "glm-deepseek"
        review = self.approved()
        with patch("termfinder.workflow.HTTPProvider", side_effect=AssertionError("No paid provider")):
            with self.assertRaises(ValueError):
                self.server.call_tool("collect", {"review_id": review["review_id"]})
        self.assertIsNone(self.server.worker)
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_safe_errors_have_actionable_codes_without_supplied_exception_text(self):
        self.init()
        def call(name, arguments):
            response = self.server.dispatch({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                            "params": {"name": name, "arguments": arguments}})
            self.assertTrue(response["result"]["isError"])
            return json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(call("collect", {"review_id": "unused"})["error_code"], "study_not_prepared")
        self.assertEqual(call("prepare_review", {})["error_code"], "plan_required")
        self.assertEqual(call("records", {"limit": 101})["error_code"], "invalid_arguments")
        review = self.prepared()
        self.assertEqual(call("collect", {"review_id": review["review_id"]})["error_code"], "approval_required")
        self.assertEqual(call("collect", {"review_id": "old-review"})["error_code"], "review_stale")

    def test_async_collection_returns_then_status_and_cancel_remain_responsive(self):
        review = self.approved()
        entered, release = threading.Event(), threading.Event()
        def slow_run(*args, **kwargs):
            entered.set()
            release.wait(2)
            return {"status": "synthetic-stopped"}
        with patch("termfinder.workflow.run_review", side_effect=slow_run):
            result = self.server.call_tool("collect", {"review_id": review["review_id"], "max_jobs": 1})
            self.assertTrue(result["started"])
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.server.call_tool("status", {})["running"])
            with self.assertRaises(ValueError):
                self.server.call_tool("collect", {"review_id": review["review_id"]})
            with self.assertRaises(ValueError):
                self.server.call_tool("prepare_study", {"brief": self.brief})
            self.assertTrue(self.server.call_tool("cancel", {})["cancellation_requested"])
            self.assertTrue(self.project.store.read_setting("cancel_requested"))
            release.set()
            self.server.worker.join(2)
        self.assertFalse(self.server.running)

    def test_actual_async_fake_extraction_resumes_without_repeating_completed_jobs(self):
        review = self.approved()
        proposal = {"expression": "byte-level BPE", "language": "en", "sense": "A tokenization method",
                    "context": TEXT, "start": None, "definition_quote": None, "translation": None, "attributes": {}}
        def response(items):
            return Response(json.dumps({"candidates": items, "coverage_complete": True}), 40, 40, "stop", "fixture-v1")
        fake = FakeProvider([], [response([proposal]), response([])])
        with patch("termfinder.workflow.FakeProvider", return_value=fake):
            self.server.call_tool("collect", {"review_id": review["review_id"], "max_jobs": 1})
            self.server.worker.join(3)
            self.assertFalse(self.server.running)
            self.assertEqual(self.server.worker_result["status"], "partial")
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(self.project.store.count("terms"), 1)
            self.server.call_tool("collect", {"review_id": review["review_id"]})
            self.server.worker.join(3)
            self.assertFalse(self.server.running)
        self.assertIsNone(self.server.worker_error)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(self.project.store.count("terms"), 1)
        self.assertEqual(self.project.status()["jobs"], {"done": 2})

    def test_eof_requests_cancel_and_stops_future_collection(self):
        review = self.approved()
        entered = threading.Event()
        def cooperative(*args, **kwargs):
            entered.set()
            deadline = time.monotonic() + 2
            while not self.project.store.read_setting("cancel_requested") and time.monotonic() < deadline:
                time.sleep(0.01)
            return {"status": "cancelled"}
        with patch("termfinder.workflow.run_review", side_effect=cooperative):
            self.server.call_tool("collect", {"review_id": review["review_id"]})
            self.assertTrue(entered.wait(1))
            self.server.serve(io.BytesIO(b""), io.StringIO())
        self.assertTrue(self.project.store.read_setting("cancel_requested"))
        self.assertFalse(self.server.running)
        with self.assertRaises(ValueError):
            self.server.call_tool("collect", {"review_id": review["review_id"]})

    def test_inspection_preserves_unicode_offsets_and_cannot_open_new_paths(self):
        record_id = self.with_record()
        inspected = self.server.call_tool("inspect_record", {"record_id": record_id, "limit": 1})
        occurrence = inspected["occurrences"][0]
        source = self.server.call_tool("inspect_source", {"source_id": occurrence["source_id"], "offset": 0, "length": 20})
        self.assertEqual(source["excerpt"]["text"], TEXT[:20])
        self.assertEqual(source["excerpt"]["offset_unit"], "Unicode code points")
        self.assertEqual(TEXT[occurrence["start"]:occurrence["end"]], "byte-level BPE")
        page = self.server.call_tool("records", {"limit": 1, "query": "BPE"})
        self.assertEqual(len(page["records"]), 1)
        with self.assertRaises(ValueError):
            self.server.call_tool("inspect_source", {"source_id": "/arbitrary.txt"})

    def test_model_suggestions_never_override_human_status_or_approved_subset(self):
        record_id = self.with_record()
        original = self.project.annotate(record_id, "approved", note="Synthetic human mark")
        suggestion = self.server.call_tool("annotate", {"record_id": record_id, "status": "needs_review", "note": "Synthetic agent suggestion"})
        self.assertFalse(suggestion["changes_human_review_status"])
        self.assertEqual(self.project.page_inventory(record_id=record_id)["selected_record"]["review_status"], "approved")
        self.assertEqual(self.project.store.count("annotations"), 1)
        self.assertEqual(self.project.store.get("audit", suggestion["suggestion_id"])["proposal"]["origin"], "model_suggestion")
        for status in ("approved", "rejected"):
            with self.assertRaises(ValueError):
                self.server.call_tool("annotate", {"record_id": record_id, "status": status})
        self.assertTrue(self.project.store.get("annotations", original)["active"])

    def test_human_relay_needs_explicit_reference_and_undo_retains_history(self):
        record_id = self.with_record()
        args = {"record_id": record_id, "status": "approved", "annotation_origin": "human_relay"}
        with self.assertRaises(ValueError):
            self.server.call_tool("annotate", args)
        args.update(researcher_approved=True, approval_reference="Explicit synthetic user judgment")
        annotation = self.server.call_tool("annotate", args)
        row = self.project.store.get("annotations", annotation["annotation_id"])
        self.assertEqual(row["origin"], "human_relay")
        self.assertFalse(row["approval_identity_verified"])
        self.server.call_tool("undo_annotation", {"annotation_id": annotation["annotation_id"],
            "researcher_approved": True, "approval_reference": "Synthetic undo instruction"})
        self.assertFalse(self.project.store.get("annotations", annotation["annotation_id"])["active"])
        self.assertEqual(self.project.page_inventory(record_id=record_id)["selected_record"]["review_status"], "unreviewed")

    def test_human_relay_provenance_is_committed_atomically(self):
        record_id = self.with_record()
        other = Project(self.project.path)
        put = self.project.store.put
        observed = []
        def inspect_transition(table, key, value, *args, **kwargs):
            result = put(table, key, value, *args, **kwargs)
            if table == "annotations":
                observed.append(other.store.get(table, key))
            return result
        with patch.object(self.project.store, "put", side_effect=inspect_transition):
            saved = self.server.call_tool("annotate", {"record_id": record_id, "status": "approved",
                "annotation_origin": "human_relay", "researcher_approved": True, "approval_reference": "Synthetic user decision"})
        self.assertTrue(observed)
        self.assertTrue(all(row is None for row in observed), observed)
        self.assertEqual(other.store.get("annotations", saved["annotation_id"])["origin"], "human_relay")

    def test_release_is_fixed_local_and_byte_reproducible_without_models(self):
        self.with_record()
        with patch("termfinder.workflow.HTTPProvider", side_effect=AssertionError("No models")):
            release = self.server.call_tool("release", {"name": "mcp-v1"})
            original = {p.name: p.read_bytes() for p in Path(release["out"]).iterdir()}
            repeated = self.server.call_tool("release", {"name": "mcp-v1"})
        self.assertEqual(release["version_id"], repeated["version_id"])
        self.assertEqual(original, {p.name: p.read_bytes() for p in Path(repeated["out"]).iterdir()})
        self.assertEqual(Path(release["out"]), self.project.path / "exports" / release["version_id"])
        self.assertTrue(release["audit"]["integrity_passed"])
        self.assertIn("records.parquet", release["files"])

    def test_stdio_bytes_have_no_logging_duplicate_errors_and_size_limit_closes(self):
        incoming = b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n{"jsonrpc":"2.0","id":3,"method":"ping"}\n'
        output = io.StringIO()
        self.server.serve(io.BytesIO(incoming), output)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["error"]["code"], -32700)
        self.assertEqual(rows[1]["result"], {})
        server = MCPServer(self.project)
        output = io.StringIO()
        with patch.object(mcp_server, "MAX_MESSAGE_BYTES", 16):
            server.serve(io.BytesIO(b"x" * 17 + b"\n"), output)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)
        self.assertTrue(server.closing.is_set())

    def test_large_result_is_marked_preview_and_remains_valid_json(self):
        result = mcp_server._result({"sources": [{"text": "x" * 100_000}] * 200})
        payload = json.loads(result["content"][0]["text"])
        self.assertTrue(payload["preview_only"])
        self.assertLess(len(result["content"][0]["text"].encode()), mcp_server.MAX_RESULT_BYTES)

    def test_oversized_review_release_and_status_keep_routing_fields_and_full_review_warning(self):
        large = [{"source_id": "s", "why_selected": "x" * 10_000}] * 100
        review = {"review_id": "review_synthetic", "ready": True, "source_count": 5000,
                  "budget_usd": 10, "mode": "broad", "model_profile": "fake", "sources": large,
                  "freeze": {"version_id": "dataset_" + "a" * 32, "out": "/study/human-review/corpus"}}
        payload = json.loads(mcp_server._result(review)["content"][0]["text"])
        self.assertEqual(payload["review_id"], review["review_id"])
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["freeze"], review["freeze"])
        self.assertTrue(payload["preview_only"])
        self.assertTrue(payload["full_review_required_before_approval"])
        self.assertIn("complete source list", payload["approval_guidance"])
        release = {"version_id": "dataset_" + "b" * 32, "out": "/study/exports/version", "name": "release-v1",
                   "manifest": {"sources": large}, "audit": {"integrity_passed": True, "findings": large}}
        payload = json.loads(mcp_server._result(release)["content"][0]["text"])
        self.assertEqual(payload["version_id"], release["version_id"])
        self.assertEqual(payload["out"], release["out"])
        self.assertTrue(payload["audit"]["integrity_passed"])
        self.assertTrue(payload["preview_only"])
        status = {"running": False, "review": review,
                  "status": {"status": "partial", "stop_reason": "budget", "counts": {"records": 5}, "failures": large}}
        payload = json.loads(mcp_server._result(status)["content"][0]["text"])
        self.assertEqual(payload["review"]["review_id"], review["review_id"])
        self.assertEqual(payload["status"]["stop_reason"], "budget")
        self.assertEqual(payload["status"]["counts"], {"records": 5})
        self.assertTrue(payload["full_review_required_before_approval"])
        self.assertLess(len(json.dumps(payload).encode()), mcp_server.MAX_RESULT_BYTES)

    def test_nested_clipping_is_promoted_to_top_level_before_plan_approval(self):
        value = {"review_id": "review_fixture", "ready": True, "sources": [{"source_id": str(i)} for i in range(101)]}
        payload = json.loads(mcp_server._result(value)["content"][0]["text"])
        self.assertTrue(payload["preview_only"])
        self.assertTrue(payload["sources"]["preview_only"])
        self.assertEqual(payload["sources"]["total_items"], 101)
        self.assertTrue(payload["full_review_required_before_approval"])
        self.assertEqual(payload["review_id"], value["review_id"])

    def test_review_pages_cover_complete_plan_costs_and_source_provenance_in_harness(self):
        review = self.prepared()
        sections = {}
        for section in mcp_server.REVIEW_SECTIONS:
            offset, items, checksum = 0, [], None
            while True:
                page = self.server.call_tool("inspect_review", {"review_id": review["review_id"],
                    "section": section, "offset": offset, "limit": 1})
                self.assertEqual(page["review_id"], review["review_id"])
                if checksum is not None:
                    self.assertEqual(checksum, page["section_sha256"])
                checksum = page["section_sha256"]
                items.extend(page["items"])
                if page["page"]["next_offset"] is None:
                    break
                offset = page["page"]["next_offset"]
            sections[section] = items
        summary = {i["key"]: i["value"] for i in sections["summary"]}
        self.assertEqual(summary["cost_range_usd"], [0, 0])
        self.assertEqual(summary["source_count"], 1)
        self.assertEqual(summary["failure_count"], 0)
        costs = {i["key"]: i["value"] for i in sections["costs"]}
        self.assertEqual(costs["budget_usd"], 0)
        self.assertEqual(costs["external_agent_costs"]["actual_usd"], None)
        self.assertIn("assumptions", costs["estimate"])
        source_page = self.server.call_tool("review_sources", {"review_id": review["review_id"], "limit": 1})
        source = source_page["sources"][0]
        self.assertEqual(source["declaration"]["metadata"]["constraints"]["content_origin"], "synthetic_fixture")
        provenance = source["source_provenance"]["provenance"]
        self.assertEqual(provenance["text_sha256"], mcp_server.digest(TEXT))
        self.assertIn("retrieved_at", provenance)
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_large_nested_review_strings_are_exactly_reassembled_by_unicode_chunks(self):
        bundle = self.bundle()
        value = "😀 Multilingual source selection rationale. " * 350
        bundle["sources"][0]["why_selected"] = value
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": bundle})["valid"])
        review = self.server.call_tool("prepare_review", {})
        offset, parts, checksum = 0, [], None
        while True:
            result = self.server.call_tool("review_text", {"review_id": review["review_id"], "section": "source_plan",
                "json_pointer": "/0/why_selected", "offset": offset, "length": 127})
            if checksum is not None:
                self.assertEqual(result["value_sha256"], checksum)
            checksum = result["value_sha256"]
            self.assertEqual(result["start"], offset)
            self.assertEqual(result["text"], value[result["start"]:result["end"]])
            parts.append(result["text"])
            if result["next_offset"] is None:
                break
            offset = result["next_offset"]
        self.assertEqual("".join(parts), value)
        self.assertEqual(checksum, mcp_server.digest(value))
        complete = self.server.call_tool("review_text", {"review_id": review["review_id"], "section": "costs"})
        self.assertTrue(complete["complete_value"])
        self.assertEqual(json.loads(complete["text"])["budget_usd"], 0)

    def test_review_tools_reject_stale_ids_invalid_pointers_and_outside_file_requests(self):
        review = self.prepared()
        for arguments in ({"review_id": "stale", "section": "brief"},
                          {"review_id": review["review_id"], "section": "brief", "json_pointer": "../outside"},
                          {"review_id": review["review_id"], "section": "brief", "json_pointer": "/~2"},
                          {"review_id": review["review_id"], "section": "brief", "json_pointer": "/missing"},
                          {"review_id": review["review_id"], "section": "brief", "offset": 10_000_000},
                          {"review_id": review["review_id"], "section": "/outside/file"}):
            with self.assertRaises(ValueError):
                self.server.call_tool("review_text", arguments)
        recipe = deepcopy(self.project.recipe)
        recipe["execution"]["budget_usd"] = 1
        self.project.configure(recipe, self.project.profile)
        for name, arguments in (("review_sources", {"review_id": review["review_id"]}),
                                ("inspect_review", {"review_id": review["review_id"], "section": "costs"})):
            with self.assertRaises(ValueError):
                self.server.call_tool(name, arguments)

    def test_source_parse_failures_are_available_in_exact_harness_review_pages(self):
        bundle = self.bundle()
        broken = self.corpus / "broken.pdf"
        broken.write_bytes(b"Synthetic invalid PDF bytes")
        source = deepcopy(bundle["sources"][0])
        source.update(source_key="broken-2", locator=str(broken))
        bundle["sources"].append(source)
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": bundle})["valid"])
        review = self.server.call_tool("prepare_review", {})
        self.assertTrue(review["ready"])
        failures = self.server.call_tool("inspect_review", {"review_id": review["review_id"], "section": "failures"})
        self.assertEqual(failures["page"]["total"], 1)
        self.assertEqual(failures["items"][0]["value"]["source_key"], "broken-2")
        page = self.server.call_tool("review_sources", {"review_id": review["review_id"], "offset": 1, "limit": 1})
        self.assertEqual(page["sources"][0]["inspection"]["status"], "failed")
        self.assertIsNotNone(page["sources"][0]["inspection"]["reason"])
        self.assertGreaterEqual(self.project.status()["failure_count"], 1)
        self.assertTrue(all(failure["locator"] == str(broken) for failure in self.project.status()["failures"]))

    def test_pending_remote_source_plan_is_inspectable_without_fetch_or_approval(self):
        bundle = self.bundle()
        remote = deepcopy(bundle["sources"][0])
        remote.update(source_key="web-2", kind="url", locator="https://example.org/article")
        bundle["sources"].append(remote)
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": bundle})["valid"])
        with patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("No network")):
            review = self.server.call_tool("prepare_review", {})
            self.assertFalse(review["ready"])
            page = self.server.call_tool("inspect_review", {"review_id": review["review_id"], "section": "pending_sources"})
            self.assertEqual(page["items"][0]["value"]["source_key"], "web-2")
            source = self.server.call_tool("review_sources", {"review_id": review["review_id"], "offset": 1, "limit": 1})
            self.assertEqual(source["sources"][0]["inspection"]["status"], "pending")
        with self.assertRaises(ValueError):
            self.server.call_tool("approve_review", {"review_id": review["review_id"], "researcher_approved": True, "approval_reference": "Synthetic pending plan"})
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_review_json_pointer_escapes_are_data_navigation_only(self):
        bundle = self.bundle()
        bundle["sources"][0]["metadata"]["constraints"]["a/b"] = {"~key": "😀 Original metadata value"}
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": bundle})["valid"])
        review = self.server.call_tool("prepare_review", {})
        result = self.server.call_tool("review_text", {"review_id": review["review_id"], "section": "source_plan",
            "json_pointer": "/0/metadata/constraints/a~1b/~0key"})
        self.assertEqual(result["text"], "😀 Original metadata value")
        self.assertEqual(result["representation"], "original_string")

    def test_url_only_plan_is_fully_inspectable_before_fetch_without_a_review_id(self):
        bundle = self.bundle()
        bundle["sources"][0].update(kind="url", locator="https://example.org/source")
        result = self.server.call_tool("submit_plan", {"bundle": bundle})
        self.assertTrue(result["valid"])
        checksum = result["bundle_sha256"]
        with patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("No fetch")):
            proposed = self.server.call_tool("inspect_plan", {"plan_sha256": checksum, "section": "sources"})
            self.assertEqual(proposed["stage"], "proposed")
            self.assertEqual(json.loads(proposed["text"])[0]["locator"], "https://example.org/source")
            review = self.server.call_tool("prepare_review", {})
            self.assertIsNone(review["review_id"])
            self.assertFalse(review["ready"])
            inspection = self.server.call_tool("inspect_plan", {"plan_sha256": checksum, "section": "ingestion"})
        self.assertTrue(inspection["inspection_only"])
        self.assertEqual(inspection["stage"], "applied")
        self.assertEqual(json.loads(inspection["text"])[0]["status"], "not_captured")
        self.assertEqual(self.project.store.count("sources"), 0)
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_all_failed_sources_keep_inspectable_plan_and_historical_failure_reasons(self):
        bundle = self.bundle()
        broken = self.corpus / "broken.pdf"
        broken.write_bytes(b"Synthetic invalid PDF")
        bundle["sources"][0]["locator"] = str(broken)
        submitted = self.server.call_tool("submit_plan", {"bundle": bundle})
        self.assertTrue(submitted["valid"])
        review = self.server.call_tool("prepare_review", {})
        self.assertFalse(review["ready"])
        self.assertIsNone(review["review_id"])
        inspected = self.server.call_tool("inspect_plan", {"plan_sha256": submitted["bundle_sha256"], "section": "ingestion"})
        row = json.loads(inspected["text"])[0]
        self.assertEqual(row["status"], "not_captured")
        self.assertIsNotNone(row["historical_parse_failure"])
        self.assertTrue(self.project.status()["failures"])
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_plan_inspection_tokens_and_chunks_cannot_cross_changed_briefs_or_bundles(self):
        bundle = self.bundle()
        checksum = self.server.call_tool("submit_plan", {"bundle": bundle})["bundle_sha256"]
        for section in ("brief", "recipe", "sources", "sampling", "evaluation", "search_log", "agent", "validation", "ingestion"):
            result = self.server.call_tool("inspect_plan", {"plan_sha256": checksum, "section": section, "length": 50})
            self.assertEqual(result["plan_sha256"], checksum)
            self.assertTrue(result["inspection_only"])
        changed = deepcopy(bundle)
        changed["sources"][0]["why_selected"] = "A revised source selection rationale"
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": changed})["valid"])
        with self.assertRaises(ValueError):
            self.server.call_tool("inspect_plan", {"plan_sha256": checksum, "section": "sources"})
        new_checksum = mcp_server.digest(changed)
        self.server.call_tool("prepare_study", {"brief": dict(self.brief, research_question="Changed question")})
        with self.assertRaises(ValueError):
            self.server.call_tool("inspect_plan", {"plan_sha256": new_checksum, "section": "sources"})

    def test_skill_export_is_self_contained_fresh_and_never_overwrites_or_installs(self):
        target = self.base / "v6-collect-research"
        result = write_skill(target)
        self.assertFalse(result["installed_globally"])
        skill = (target / "SKILL.md").read_text()
        self.assertTrue(skill.startswith("---\nname: v6-collect-research\ndescription:"))
        self.assertTrue((target / "references" / "workflow.md").is_file())
        with self.assertRaises(ValueError):
            write_skill(target)
        original = (target / "SKILL.md").read_text()
        self.assertEqual(skill, original)
        linked = self.base / "linked"
        linked.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            write_skill(linked / "new-skill")


class MCPSubprocessTests(unittest.TestCase):
    def environment(self, base):
        environment = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src"), "TMPDIR": str(base)}
        # Only CI's reviewed native-runtime path survives; no provider keys or
        # unrelated variables are inherited by these actual stdio processes.
        for name in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
            if name in os.environ:
                environment[name] = os.environ[name]
        return environment

    def test_actual_stdio_subprocess_negotiates_lists_tools_and_prepares_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            child = subprocess.Popen([sys.executable, "-m", "termfinder.mcp_server", "--project", str(base / "project")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self.environment(base), cwd=base)
            try:
                def request(payload):
                    child.stdin.write((json.dumps(payload) + "\n").encode())
                    child.stdin.flush()
                    self.assertTrue(select.select([child.stdout], [], [], 5)[0], "Finite stdio response deadline")
                    return json.loads(child.stdout.readline())
                init = request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "offline-pipe", "version": "1"}}})
                self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
                child.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                child.stdin.flush()
                tools = request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                names = {t["name"] for t in tools["result"]["tools"]}
                self.assertIn("prepare_review", names)
                self.assertIn("collect", names)
                self.assertNotIn("execute_shell", names)
                prepared = request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "prepare_study", "arguments": {"brief": {"research_question": "Synthetic stdio smoke", "model_profile": "fake", "budget_usd": 0}}}})
                payload = json.loads(prepared["result"]["content"][0]["text"])
                self.assertFalse(payload["paid_transport_permitted"])
                self.assertIn("starter_bundle", payload)
                child.stdin.close()
                self.assertEqual(child.wait(timeout=5), 0)
                self.assertEqual(child.stderr.read(), b"")
                self.assertEqual(child.stdout.read(), b"")
                self.assertEqual(Project(base / "project").store.count("jobs"), 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=2)
                child.stdout.close()
                child.stderr.close()

    def test_stdio_workspace_connection_reuses_multiple_studies_without_reconfiguration(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            child = subprocess.Popen([sys.executable, "-m", "termfinder.mcp_server", "--workspace", str(base)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self.environment(base), cwd=base)
            try:
                def request(payload):
                    child.stdin.write((json.dumps(payload) + "\n").encode())
                    child.stdin.flush()
                    self.assertTrue(select.select([child.stdout], [], [], 5)[0])
                    return json.loads(child.stdout.readline())
                request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
                child.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                child.stdin.flush()
                def call(name, arguments):
                    response = request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
                    self.assertFalse(response["result"]["isError"], response)
                    return json.loads(response["result"]["content"][0]["text"])
                self.assertIsNone(call("status", {})["selected_study"])
                self.assertEqual(call("create_study", {"slug": "first-study"})["study_slug"], "first-study")
                self.assertEqual(call("create_study", {"slug": "second-study"})["study_slug"], "second-study")
                self.assertEqual(call("open_study", {"slug": "first-study"})["study_slug"], "first-study")
                listed = call("list_studies", {"limit": 1})
                self.assertEqual(listed["page"]["total"], 2)
                self.assertEqual(listed["selected_study"], "first-study")
                child.stdin.close()
                self.assertEqual(child.wait(timeout=5), 0)
                self.assertEqual(child.stderr.read(), b"")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=2)
                child.stdout.close()
                child.stderr.close()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / "studies"
        self.workspace.mkdir()
        self.server = MCPServer(workspace=self.workspace)
        self.addCleanup(self.server.close)

    def test_workspace_requires_selection_then_preserves_independent_studies(self):
        self.assertIsNone(self.server.call_tool("status", {})["selected_study"])
        with self.assertRaises(ValueError):
            self.server.call_tool("prepare_study", {"brief": {"research_question": "No study"}})
        first = self.server.call_tool("create_study", {"slug": "first-study", "brief": {"research_question": "First source vocabulary", "model_profile": "fake"}})
        self.assertTrue(first["created"])
        self.assertEqual(self.server.project.store.count("jobs"), 0)
        self.server.project.store.setting("fixture_marker", "first")
        first_path = self.server.project.path
        self.server.call_tool("create_study", {"slug": "second-study"})
        self.server.project.store.setting("fixture_marker", "second")
        self.assertEqual(self.server.project.agent_setup(), {})
        self.server.call_tool("open_study", {"slug": "first-study"})
        self.assertEqual(self.server.project.path, first_path)
        self.assertEqual(self.server.project.store.read_setting("fixture_marker"), "first")
        self.assertEqual(self.server.project.agent_setup()["brief"]["research_question"], "First source vocabulary")
        page = self.server.call_tool("list_studies", {"limit": 1})
        self.assertEqual(page["page"]["total"], 2)
        self.assertEqual(page["page"]["next_offset"], 1)
        self.assertEqual(self.server.call_tool("list_studies", {"offset": 1, "limit": 1})["studies"][0]["slug"], "second-study")
        self.assertTrue(first_path.is_relative_to(self.workspace))

    def test_bad_slugs_no_paths_hidden_names_reserved_devices_or_overwrites(self):
        for slug in ("../outside", "/absolute", ".hidden", "nested/study", "Uppercase", "con", "nul", "com0", "lpt9", "a" * 65):
            for tool in ("create_study", "open_study"):
                with self.assertRaises(ValueError):
                    self.server.call_tool(tool, {"slug": slug})
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.server.call_tool("create_study", {"slug": "safe-study"})
        before = self.server.project.store.read_setting("schema_version")
        with self.assertRaises(ValueError):
            self.server.call_tool("create_study", {"slug": "safe-study"})
        self.assertEqual(self.server.project.store.read_setting("schema_version"), before)

    def test_symlink_workspace_study_database_and_lock_are_rejected_without_opening_target(self):
        outside = self.base / "outside"
        Project(outside)
        linked = self.base / "linked"
        linked.symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(ValueError):
            MCPServer(workspace=linked)
        (self.workspace / "linked-study").symlink_to(outside, target_is_directory=True)
        with patch("termfinder.mcp_server.Project", side_effect=AssertionError("No unrelated project open")):
            with self.assertRaises(ValueError):
                self.server.call_tool("open_study", {"slug": "linked-study"})
        for filename in ("project.sqlite3", ".collection.lock"):
            study = self.workspace / ("database-study" if filename == "project.sqlite3" else "lock-study")
            Project(study)
            (study / filename).unlink(missing_ok=True)
            (study / filename).symlink_to(outside / "project.sqlite3")
            with self.assertRaises(ValueError):
                self.server.call_tool("open_study", {"slug": study.name})
        self.assertEqual(self.server.call_tool("list_studies", {})["studies"], [])

    def test_selected_directory_replacement_is_rejected_before_next_operation(self):
        self.server.call_tool("create_study", {"slug": "first-study"})
        path = self.workspace / "first-study"
        path.rename(self.workspace / "original-study")
        path.symlink_to(self.base / "outside", target_is_directory=True)
        for name, arguments in (("status", {}), ("open_study", {"slug": "original-study"})):
            with self.assertRaises(ValueError):
                self.server.call_tool(name, arguments)

    def test_constructor_directory_race_cannot_initialize_an_outside_database(self):
        for operation in ("create_study", "open_study"):
            with self.subTest(operation=operation):
                slug = "create-race" if operation == "create_study" else "open-race"
                path = self.workspace / slug
                outside = self.base / (slug + "-outside")
                outside.mkdir()
                if operation == "open_study":
                    Project(path).store.setting("fixture_marker", "retained")
                def replace_before_constructor(candidate_path, **kwargs):
                    self.assertIn("path_guard", kwargs)
                    Path(candidate_path).rename(self.workspace / (slug + "-original"))
                    Path(candidate_path).symlink_to(outside, target_is_directory=True)
                    return Project(candidate_path, **kwargs)
                with patch("termfinder.mcp_server.Project", side_effect=replace_before_constructor):
                    with self.assertRaises(ValueError):
                        self.server.call_tool(operation, {"slug": slug})
                self.assertFalse((outside / "project.sqlite3").exists())
                self.assertEqual(list(outside.iterdir()), [])
                self.assertIsNone(self.server.project)
                if operation == "open_study":
                    self.assertEqual(Project(self.workspace / (slug + "-original")).store.read_setting("fixture_marker"), "retained")

    def test_store_constructor_race_cannot_initialize_an_outside_database(self):
        from termfinder.store import Store
        slug = "store-race"
        path = self.workspace / slug
        outside = self.base / "store-outside"
        outside.mkdir()
        def replace_before_store(database_path, **kwargs):
            self.assertIn("path_guard", kwargs)
            path.rename(self.workspace / "store-original")
            path.symlink_to(outside, target_is_directory=True)
            return Store(database_path, **kwargs)
        with patch("termfinder.project.Store", side_effect=replace_before_store):
            with self.assertRaises(ValueError):
                self.server.call_tool("create_study", {"slug": slug})
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIsNone(self.server.project)

    def test_guard_rechecks_database_links_before_later_connections(self):
        self.server.call_tool("create_study", {"slug": "guarded-study"})
        outside = Project(self.base / "outside-db")
        outside.store.setting("fixture_marker", "outside")
        path = self.server.project.path / "project.sqlite3"
        path.rename(path.with_name("retained.sqlite3"))
        path.symlink_to(outside.path / "project.sqlite3")
        with self.assertRaises(ValueError):
            self.server.project.store.setting("fixture_marker", "must-not-write")
        self.assertEqual(outside.store.read_setting("fixture_marker"), "outside")

    def test_close_retains_guard_descriptor_until_bounded_worker_finishes(self):
        self.server.call_tool("create_study", {"slug": "closing-study"})
        entered, release = threading.Event(), threading.Event()
        def wait_then_persist():
            entered.set()
            release.wait(2)
            self.server.project.store.setting("fixture_marker", "final-outcome")
        self.server.worker = threading.Thread(target=wait_then_persist, daemon=True)
        self.server.worker.start()
        self.assertTrue(entered.wait(1))
        try:
            self.assertFalse(self.server.close(timeout=0))
            self.assertIsNotNone(self.server.workspace_fd)
        finally:
            release.set()
            self.server.worker.join(2)
        self.assertEqual(Project(self.workspace / "closing-study").store.read_setting("fixture_marker"), "final-outcome")
        self.assertTrue(self.server.close())
        self.assertIsNone(self.server.workspace_fd)

    def test_broad_and_credential_workspace_roots_are_rejected(self):
        for root in ("/", "/home", "/tmp", "/private/tmp", "/private", "/var", str(Path.home())):
            with self.subTest(root=root), self.assertRaises(ValueError):
                MCPServer(workspace=root)
        credential_root = self.base / "credentials" / "studies"
        credential_root.mkdir(parents=True)
        with self.assertRaises(ValueError):
            MCPServer(workspace=credential_root)

    def test_workspace_switching_refuses_active_worker_or_other_process_collection_lock(self):
        self.server.call_tool("create_study", {"slug": "first-study"})
        self.server.call_tool("create_study", {"slug": "second-study"})
        self.server.call_tool("open_study", {"slug": "first-study"})
        entered, release = threading.Event(), threading.Event()
        def wait():
            entered.set()
            release.wait(2)
        self.server.worker = threading.Thread(target=wait, daemon=True)
        self.server.worker.start()
        self.assertTrue(entered.wait(1))
        try:
            for name, slug in (("open_study", "second-study"), ("create_study", "third-study")):
                with self.assertRaises(ValueError):
                    self.server.call_tool(name, {"slug": slug})
        finally:
            release.set()
            self.server.worker.join(2)
        with self.server.project._lock():
            with self.assertRaises(RuntimeError):
                self.server.call_tool("open_study", {"slug": "second-study"})
        self.assertEqual(self.server.study_slug, "first-study")
        self.assertFalse((self.workspace / "third-study").exists())

    def test_workspace_inventory_is_finite_and_skips_unmanaged_hidden_entries(self):
        (self.workspace / ".unrelated").mkdir()
        (self.workspace / "unmanaged").mkdir()
        (self.workspace / "readme.txt").write_text("Synthetic unrelated file")
        self.assertEqual(self.server.call_tool("list_studies", {})["studies"], [])
        with patch.object(mcp_server, "MAX_WORKSPACE_ENTRIES", 2):
            with self.assertRaises(ValueError):
                self.server.call_tool("list_studies", {})
            with self.assertRaises(ValueError):
                self.server.call_tool("create_study", {"slug": "another-study"})
        self.assertFalse((self.workspace / "another-study").exists())

    def test_fixed_project_mode_retains_single_project_and_cannot_use_workspace_tools(self):
        fixed = MCPServer(Project(self.base / "fixed"))
        self.addCleanup(fixed.close)
        self.assertNotIn("open_study", {tool["name"] for tool in fixed.tools})
        with self.assertRaises(LookupError):
            fixed.call_tool("open_study", {"slug": "anything"})
        with self.assertRaises(ValueError):
            MCPServer(fixed.project, workspace=self.workspace)

    def test_invalid_optional_brief_does_not_create_study_or_dispatch_sources(self):
        with self.assertRaises(ValueError):
            self.server.call_tool("create_study", {"slug": "bad-brief", "brief": {"research_question": "Synthetic", "budget_usd": -1}})
        self.assertFalse((self.workspace / "bad-brief").exists())
        self.assertIsNone(self.server.project)


if __name__ == "__main__":
    unittest.main()
