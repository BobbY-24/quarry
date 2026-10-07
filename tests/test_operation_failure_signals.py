"""Mutation failure receipts keep machine-readable failure signaling."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_mcp_server as fixtures
from termfinder.cli import main


class OperationFailureSignalsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MCPTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project, self.server = self.fixture.project, self.fixture.server
        self.fixture.init()

    def tool(self, name, arguments):
        response = self.server.dispatch({"jsonrpc": "2.0", "id": 23, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}})
        return response["result"]

    def test_failed_mutation_is_mcp_error_but_receipt_inspection_is_successful(self):
        with patch.object(self.project, "cancel", side_effect=RuntimeError("Synthetic failure")):
            result = self.tool("cancel", {"operation_id": "fixture-failed-cancel"})
        receipt = json.loads(result["content"][0]["text"])
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(result["isError"])
        lookup = self.tool("operation_status", {"operation_id": "fixture-failed-cancel"})
        self.assertFalse(lookup["isError"])
        self.assertEqual(json.loads(lookup["content"][0]["text"])["operation_id"], receipt["operation_id"])

    def test_uncertain_mutation_is_mcp_error_but_normal_status_is_successful(self):
        with patch("termfinder.workflow.release_dataset", side_effect=RuntimeError("Synthetic external effect uncertainty")):
            result = self.tool("release", {"name": "synthetic-release", "operation_id": "fixture-uncertain-release"})
        self.assertEqual(json.loads(result["content"][0]["text"])["status"], "uncertain")
        self.assertTrue(result["isError"])
        with patch.object(self.project, "status", return_value={"status": "uncertain"}):
            status = self.tool("status", {})
        self.assertFalse(status["isError"])

    def test_failed_cli_mutation_returns_nonzero_with_durable_receipt(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["--project", str(self.project.path), "--operation-id", "fixture-cli-failed",
                "annotate", "missing-synthetic-record", "approved"])
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "failed")
        self.assertNotEqual(exit_code, 0)
        lookup = io.StringIO()
        with contextlib.redirect_stdout(lookup):
            self.assertEqual(main(["--project", str(self.project.path), "operation", receipt["operation_id"]]), 0)

    def test_uncertain_cli_quota_mutation_returns_nonzero(self):
        output = io.StringIO()
        with patch("termfinder.project.Project.configure_quota", side_effect=RuntimeError("Synthetic configuration interruption")), \
             contextlib.redirect_stdout(output):
            exit_code = main(["--project", str(self.project.path), "--operation-id", "fixture-cli-quota",
                "configure-quota", "--registry", str(Path(self.fixture.base) / "synthetic-quota.sqlite3"),
                "--scope-id", "synthetic-account"])
        self.assertEqual(json.loads(output.getvalue())["status"], "uncertain")
        self.assertNotEqual(exit_code, 0)

    def test_pending_receipt_keeps_successful_acknowledgement_signal(self):
        pending = {"operation_id": "fixture-pending", "parameter_sha256": "0" * 64,
            "status": "pending"}
        with patch.object(self.server, "call_tool", return_value=pending):
            self.assertFalse(self.tool("cancel", {"operation_id": "fixture-pending"})["isError"])
        output = io.StringIO()
        with patch("termfinder.operations.OperationManager.execute", return_value=pending), \
             contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(self.project.path), "--operation-id", "fixture-pending",
                "annotate", "missing-synthetic-record", "approved"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "pending")


if __name__ == "__main__":
    unittest.main()
