"""Offline researcher compute configuration through CLI and agent tools.

Fixtures declare local or synthetic institutional endpoints; no service is
started and no credentials, network requests, or compute allocations are used.
"""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import cli, Project
from termfinder.mcp_server import MCPServer, ToolFailure
from termfinder.workflow import current_review


class ComputeInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root / "study")
        self.server = MCPServer(self.project)
        self.addCleanup(self.server.close)
        self.local = {"backend": "local", "base_url": "http://127.0.0.1:11434/v1",
            "model": "fixture-model", "model_version": "fixture-revision-1",
            "context_limit_tokens": 32768, "max_output_tokens": 2048,
            "researcher_configured": True,
            "configuration_reference": "Synthetic researcher chose a local fixture endpoint."}

    def prepared(self):
        corpus = self.root / "corpus"
        corpus.mkdir(exist_ok=True)
        source = corpus / "source.md"
        source.write_text("😀 This tokenizer uses byte-level BPE.", encoding="utf-8")
        setup = self.server.call_tool("prepare_study", {"brief": {
            "research_question": "Which technical expressions occur?", "data_type": "term",
            "starter_recipe": "jargon", "local_roots": [str(corpus)], "languages": ["en"],
            "communities": ["synthetic-corpus"], "domains": ["example.org"],
            "budget_usd": 1, "max_sources": 2}})
        self.assertEqual(setup["brief"]["model_profile"], "configured")
        bundle = deepcopy(setup["starter_bundle"])
        bundle["unresolved_questions"] = []
        bundle["agent"]["tool"] = "offline_fixture"
        bundle["sources"] = [{"source_key": "source-1", "kind": "local", "locator": str(source),
            "metadata": {"language": "en", "community": "synthetic-corpus", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "synthetic_fixture",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                    "permitted_use": "offline_verification", "redistribution": "fixture_only"}},
            "why_selected": "Synthetic compute protocol verification", "origin": "researcher_supplied",
            "search_refs": [], "family_id": "synthetic-family"}]
        self.assertTrue(self.server.call_tool("submit_plan", {"bundle": bundle})["valid"])
        return self.server.call_tool("prepare_review", {})

    def test_mcp_configuration_is_inert_and_does_not_enable_inference_gate(self):
        with patch("termfinder.workflow.HTTPProvider", side_effect=AssertionError("No inference")), \
             patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("No fetch")):
            result = self.server.call_tool("configure_compute", self.local)
            summary = self.server.call_tool("inspect_compute", {})
        self.assertFalse(result["paid_transport_permitted"])
        self.assertFalse(result["configuration_identity_verified"])
        self.assertEqual(result["compute"], summary["compute"])
        self.assertEqual(self.project.store.count("jobs"), 0)
        self.assertEqual(self.project.store.count("sources"), 0)
        self.assertIn("fixture-revision-1", json.dumps(summary))

    def test_mcp_requires_researcher_declaration_for_compute_changes(self):
        for changes in ({"researcher_configured": False}, {"configuration_reference": " "}):
            with self.assertRaises(ToolFailure) as failure:
                self.server.call_tool("configure_compute", dict(self.local, **changes))
            self.assertEqual(failure.exception.code, "configuration_declaration_required")
        self.assertIsNone(self.project.store.read_setting("configured_profile"))

    def test_mcp_rejects_secret_fields_nonfinite_rates_and_tool_scope_expansion(self):
        for changes in ({"api_key": "synthetic-marker"}, {"allow_paid": True},
                        {"input_per_million": float("nan")}, {"output_per_million": True},
                        {"input_per_million": -1}, {"context_limit_tokens": True},
                        {"max_output_tokens": 0}, {"max_output_tokens": 131073}):
            with self.assertRaises(ToolFailure) as failure:
                self.server.call_tool("configure_compute", dict(self.local, **changes))
            self.assertEqual(failure.exception.code, "invalid_arguments")
        self.assertIsNone(self.project.store.read_setting("configured_profile"))

    def test_compute_summary_is_reviewable_and_operator_changes_invalidate_approval(self):
        self.server.call_tool("configure_compute", self.local)
        review = self.prepared()
        inspected = self.server.call_tool("inspect_review", {
            "review_id": review["review_id"], "section": "compute"})
        self.assertIn("fixture-revision-1", json.dumps(inspected))
        self.assertIn("compute", self.server.call_tool("status", {}))
        self.server.call_tool("approve_review", {"review_id": review["review_id"],
            "researcher_approved": True, "approval_reference": "Synthetic plan decision."})
        self.assertFalse(current_review(self.project)["stale"])
        self.server.call_tool("configure_compute", dict(self.local, model_version="fixture-revision-2"))
        changed = current_review(self.project)
        self.assertTrue(changed["stale"])
        self.assertFalse(changed.get("approved"))
        with self.assertRaises(ToolFailure):
            self.server.call_tool("collect", {"review_id": review["review_id"]})
        self.assertEqual(self.project.store.count("jobs"), 0)

    def test_custom_institutional_env_value_never_appears_in_results_or_store(self):
        marker = "synthetic-secret-marker-never-export"
        values = {"backend": "institutional", "base_url": "https://inference.example.edu/v1",
            "model": "fixture-model", "model_version": "pinned-fixture",
            "credential_env": "FIXTURE_INFERENCE_TOKEN", "researcher_configured": True,
            "configuration_reference": "Synthetic permitted institutional endpoint."}
        with patch.dict(os.environ, {"FIXTURE_INFERENCE_TOKEN": marker}, clear=True):
            result = self.server.call_tool("configure_compute", values)
            summary = self.server.call_tool("inspect_compute", {})
        self.assertIn("FIXTURE_INFERENCE_TOKEN", json.dumps(summary))
        self.assertNotIn(marker, json.dumps(result))
        self.assertNotIn(marker, json.dumps(summary))
        self.assertNotIn(marker, json.dumps(self.project.store.read_setting("configured_profile")))

    def test_nullable_auth_and_rates_are_accepted_for_local_configuration(self):
        result = self.server.call_tool("configure_compute", dict(self.local,
            credential_env=None, input_per_million=None, output_per_million=None,
            preset=None, response_format="none"))
        self.assertIn("fixture-model", json.dumps(result))

    def test_cli_configures_local_then_defaults_plain_language_study_to_it(self):
        args = ["--project", str(self.project.path), "configure-compute", "--backend", "local",
            "--base-url", "http://127.0.0.1:11434/v1", "--model", "fixture-model",
            "--model-version", "fixture-revision-1", "--max-output-tokens", "2048"]
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(cli.main(args), 0)
        self.assertIn("fixture-revision-1", output.getvalue())
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(cli.main(["--project", str(self.project.path), "compute"]), 0)
        self.assertIn("fixture-model", output.getvalue())
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(["--project", str(self.project.path), "prepare-agent",
                "--idea", "Collect jargon", "--policy", "jargon", "--out", str(self.root / "handoff")]), 0)
        self.assertEqual(self.project.agent_setup()["brief"]["model_profile"], "configured")

    def test_cli_invalid_compute_does_not_echo_supplied_credential_like_endpoint(self):
        marker = "synthetic-secret-marker"
        with patch("sys.stderr", new_callable=io.StringIO) as errors, \
             patch("sys.stdout", new_callable=io.StringIO):
            code = cli.main(["--project", str(self.project.path), "configure-compute", "--backend", "api",
                "--base-url", "https://user:" + marker + "@api.example.org/v1",
                "--model", "fixture", "--model-version", "fixture-v1",
                "--credential-env", "FIXTURE_KEY", "--input-per-million", "1", "--output-per-million", "2"])
        self.assertEqual(code, 2)
        self.assertNotIn(marker, errors.getvalue())
        self.assertIn("No supplied values are echoed", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
