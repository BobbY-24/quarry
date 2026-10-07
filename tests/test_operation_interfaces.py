"""Lost-reply handling is explicit and separate from transport identifiers."""
import contextlib
import io
import json
import unittest

import test_mcp_server as fixtures
import test_simple_ui as browser_fixtures
from termfinder.cli import main, parser


class OperationInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MCPTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.record = self.fixture.with_record()
        if isinstance(self.record, dict):
            self.record = self.record.get("record_id", self.record.get("term_id"))
        if self.record is None:
            self.record = self.fixture.project.store.rows("terms")[0]["term_id"]
        self.project, self.server = self.fixture.project, self.fixture.server

    def annotation(self):
        return {"record_id": self.record, "status": "approved", "annotation_origin": "human_relay",
            "researcher_approved": True, "approval_reference": "Synthetic human review",
            "operation_id": "fixture-annotation-1"}

    def test_mcp_duplicate_annotation_returns_same_receipt_without_duplicate_row(self):
        first = self.server.call_tool("annotate", self.annotation())
        second = self.server.call_tool("annotate", self.annotation())
        self.assertEqual({k: v for k, v in first.items() if k != "transient_result"}, second)
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(self.project.store.count("annotations"), 1)
        changed = dict(self.annotation(), status="rejected")
        with self.assertRaises(ValueError):
            self.server.call_tool("annotate", changed)
        self.assertEqual(self.project.store.count("annotations"), 1)

    def test_mcp_explicit_operation_id_survives_different_jsonrpc_ids(self):
        self.fixture.init()
        for transport_id in (100, 101):
            response = self.server.dispatch({"jsonrpc": "2.0", "id": transport_id,
                "method": "tools/call", "params": {"name": "annotate", "arguments": self.annotation()}})
            self.assertEqual(response["id"], transport_id)
            self.assertFalse(response["result"].get("isError", False))
        self.assertEqual(self.project.store.count("annotations"), 1)
        tools = {tool["name"]: tool for tool in self.server.tools}
        self.assertIn("operation_id", tools["annotate"]["inputSchema"]["properties"])
        self.assertNotIn("operation_id", tools["records"]["inputSchema"]["properties"])

    def test_browser_duplicate_mutation_keeps_host_origin_auth_and_receipt(self):
        body = {"term_id": self.record, "status": "approved", "operation_id": "fixture-browser-1"}
        responses = []
        for _ in range(2):
            handler = browser_fixtures.request("/api/annotate", body)
            handler.server.project = self.project
            handler.do_POST()
            self.assertEqual(handler.responses[0][0], 200)
            responses.append(handler.responses[0][1])
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(self.project.store.count("annotations"), 1)
        bad = browser_fixtures.request("/api/annotate", dict(body, operation_id="fixture-browser-2"))
        bad.server.project = self.project
        bad.headers.replace_header("Origin", "https://synthetic.invalid")
        bad.do_POST()
        self.assertEqual(bad.responses[0][0], 403)
        self.assertEqual(self.project.store.count("annotations"), 1)

    def test_cli_global_operation_id_replays_and_can_inspect_receipt(self):
        argv = ["--project", str(self.project.path), "--operation-id", "fixture-cli-1",
            "annotate", self.record, "approved", "--note", "Synthetic review"]
        values = []
        for _ in range(2):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(argv), 0)
            values.append(json.loads(output.getvalue()))
        self.assertEqual(values[0], values[1])
        self.assertEqual(self.project.store.count("annotations"), 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(self.project.path), "operation", "fixture-cli-1"]), 0)
        self.assertEqual(json.loads(output.getvalue())["operation_id"], "fixture-cli-1")
        self.assertEqual(parser().parse_args(["doctor"]).command, "doctor")

    def test_lost_study_setup_reply_can_be_read_without_repeating_preparation(self):
        args = {"brief": self.fixture.brief, "operation_id": "fixture-setup-1"}
        first = self.server.call_tool("prepare_study", args)
        repeated = self.server.call_tool("prepare_study", args)
        self.assertEqual(first["operation_id"], repeated["operation_id"])
        self.assertNotIn("transient_result", repeated)
        self.assertNotIn("prompt", repeated.get("result") or {})
        brief_hash = self.project.agent_setup()["brief_sha256"]
        chunks, offset = [], 0
        while True:
            chunk = self.server.call_tool("study_setup_text", {"brief_sha256": brief_hash,
                "section": "prompt", "offset": offset, "length": 12000})
            chunks.append(chunk["text"])
            if chunk["next_offset"] is None:
                break
            offset = chunk["next_offset"]
        self.assertEqual("".join(chunks), self.project.agent_setup()["prompt"])


if __name__ == "__main__":
    unittest.main()
