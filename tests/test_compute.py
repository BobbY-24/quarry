"""Offline compute security and operator/provenance contracts; mocked transports only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from termfinder import Project, FakeProvider
from termfinder.compute import build_compute_profile
from termfinder.config import load_profile, starter_recipe, experts
from termfinder.costs import estimate
from termfinder.providers import HTTPProvider, ProviderError
from termfinder.sources import parse_document


class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(backend="local", base_url="http://127.0.0.1:8000/v1",
            model="fixture-model", model_version="fixture-checkpoint-and-template-v1")
        self.profile = build_compute_profile(**self.settings)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / "study")
        self.request = {"expert": {"model": "researcher"}, "prompt": "synthetic fixture",
                        "timeout_seconds": 5, "max_output_tokens": 256}

    def test_endpoint_policy_rejects_plaintext_remote_auth_and_embedded_credentials(self):
        invalid = [dict(base_url="http://10.0.0.1:8000/v1", backend="institutional"),
            dict(base_url="https://example.edu/v1", backend="institutional"),
            dict(base_url="http://127.0.0.1:8000/v1", credential_env="TEST_API_KEY"),
            dict(base_url="https://user:synthetic-marker@example.edu/v1", backend="institutional", credential_env="TEST_API_KEY"),
            dict(base_url="https://example.edu/v1?key=synthetic-marker", backend="institutional", credential_env="TEST_API_KEY"),
            dict(base_url="https://example.edu/v1#fragment", backend="institutional", credential_env="TEST_API_KEY"),
            dict(base_url="http://127.0.0.1:999999/v1"),
            dict(base_url="http://127.0.0.1:8000/v1\n"),
            dict(base_url="https://example.edu/v1", backend="institutional", credential_env="PATH")]
        for name in ("LD_PRELOAD", "LD_INFERENCE_KEY", "DYLD_INSERT_LIBRARIES", "PYTHONSTARTUP", "PYTHON_API_KEY", "SSL_CERT_FILE", "SSL_API_KEY", "OPENSSL_CONF", "GCONV_PATH", "BASH_ENV"):
            invalid.append(dict(base_url="https://example.edu/v1", backend="institutional", credential_env=name))
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_compute_profile(**dict(self.settings, **change))

    def test_numeric_loopback_and_localhost_canonicalization_without_dns(self):
        for endpoint in ("http://127.0.0.2:8000/v1", "http://[::1]:8000/v1", "http://localhost:8000/v1"):
            profile = build_compute_profile(**dict(self.settings, base_url=endpoint))
            self.assertIsNone(profile["providers"]["researcher"]["credential_env"])
            self.assertEqual(profile["providers"]["researcher"]["auth"], "none")
            if "localhost" in endpoint:
                self.assertEqual(profile["providers"]["researcher"]["base_url"], "http://127.0.0.1:8000/v1")

    def test_personal_presets_keep_independent_models_and_separate_gemini(self):
        preset = build_compute_profile(backend="api", preset="glm-deepseek")
        baseline = load_profile("glm-deepseek")
        self.assertEqual(preset["models"], baseline["models"])
        self.assertEqual(preset["broad"], baseline["broad"])
        self.assertEqual(preset["providers"], baseline["providers"])
        self.assertEqual(len(preset["broad"]), 2)
        self.assertIn("gemini", build_compute_profile(backend="api", preset="gemini")["models"])

    def test_custom_api_requires_explicit_rates_and_version(self):
        settings = dict(self.settings, backend="api", base_url="https://service.example/v1", credential_env="TEST_API_KEY")
        for changes in ({}, {"input_per_million": 1}, {"input_per_million": 1, "output_per_million": 2, "model_version": None}):
            with self.assertRaises(ValueError): build_compute_profile(**dict(settings, **changes))
        profile = build_compute_profile(**dict(settings, input_per_million=1, output_per_million=2))
        self.assertEqual(profile["compute"]["cost_basis"], "token_rates")

    def test_no_auth_transport_sends_no_header_and_does_not_require_environment(self):
        envelope = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "model": "fixture-runtime"}
        with patch.dict(os.environ, {}, clear=True), patch("termfinder.providers.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
            response = HTTPProvider(self.profile, _direct=True).complete(self.request)
            sent = opener.return_value.open.call_args.args[0]
        self.assertEqual(response.text, "{}")
        self.assertNotIn("Authorization", sent.headers)
        self.assertEqual(sent.full_url, "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(json.loads(sent.data)["response_format"], {"type": "json_object"})

    def test_response_format_option_is_transport_only_validation_stays_external(self):
        profile = build_compute_profile(**dict(self.settings, response_format="none"))
        envelope = {"choices": [{"message": {"content": "not valid extraction JSON"}}]}
        with patch("termfinder.providers.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
            result = HTTPProvider(profile, _direct=True).complete(self.request)
            body = json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertNotIn("response_format", body)
        self.assertEqual(result.text, "not valid extraction JSON")

    def test_worker_receives_only_selected_credential_and_no_credentials_for_local(self):
        profile = build_compute_profile(**dict(self.settings, backend="institutional", base_url="https://service.example/v1", credential_env="TEST_API_KEY"))
        from termfinder.process_transport import TransportResult
        answer = TransportResult(json.dumps({"response": {"text": "{}"}}).encode(), 0)
        with patch.dict(os.environ, {"TEST_API_KEY": "synthetic-selected", "UNRELATED_TOKEN": "synthetic-unrelated"}, clear=True), patch("termfinder.providers.bounded_exchange", return_value=answer) as run:
            HTTPProvider(profile).complete(self.request)
            self.assertEqual(run.call_args.kwargs["env"]["TEST_API_KEY"], "synthetic-selected")
            self.assertNotIn("UNRELATED_TOKEN", run.call_args.kwargs["env"])
            self.assertNotIn("synthetic-selected", json.dumps(run.call_args.args[0]))
            self.assertNotIn("synthetic-selected", run.call_args.args[1].decode())
            HTTPProvider(self.profile).complete(self.request)
            self.assertNotIn("TEST_API_KEY", run.call_args.kwargs["env"])

    def test_provider_cannot_echo_credential_into_text_or_provenance(self):
        profile = build_compute_profile(**dict(self.settings, backend="institutional", base_url="https://service.example/v1", credential_env="TEST_API_KEY"))
        marker = "synthetic-selected-marker"
        for field in ("text", "model", "id"):
            envelope = {"choices": [{"message": {"content": marker if field == "text" else "{}"}}], field: marker}
            with patch.dict(os.environ, {"TEST_API_KEY": marker}, clear=True), patch("termfinder.providers.build_opener") as opener:
                opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
                with self.assertRaises(ProviderError) as raised:
                    HTTPProvider(profile, _direct=True).complete(self.request)
                self.assertEqual(raised.exception.reason, "credential_echo_in_provider_response")
                self.assertTrue(raised.exception.uncertain)
                self.assertNotIn(marker, str(raised.exception))

    def test_human_compute_survives_planning_and_cannot_be_replaced_by_bundle(self):
        self.project.configure_compute(**self.settings)
        setup = self.project.prepare_agent_setup({"research_question": "Collect technical jargon", "starter_recipe": "jargon"})
        self.assertEqual(setup["brief"]["model_profile"], "configured")
        self.assertEqual(set(ex["model"] for ex in setup["starter_bundle"]["recipe"]["specialist_lenses"]), {"researcher"})
        with self.assertRaises(ValueError):
            self.project.prepare_agent_setup({"research_question": "Collect jargon", "model_profile": "gemini"})
        bundle = deepcopy(setup["starter_bundle"])
        bundle["recipe"]["providers"] = {"evil": "https://unreviewed.example"}
        self.assertFalse(self.project.validate_agent_bundle(bundle)["valid"])
        self.assertEqual(self.project.store.read_setting("configured_profile"), self.profile)
        with self.assertRaises(ValueError):
            self.project.configure(starter_recipe("jargon"), "gemini")
        self.assertEqual(self.project.profile, self.profile)

    def test_zero_token_rate_leaves_infrastructure_unknown_and_request_budget_finite(self):
        recipe = starter_recipe("jargon")
        recipe["mode"] = "specialists"
        for lens in recipe["specialist_lenses"]:
            lens["model"] = "researcher"
            lens["communities"] = ["*"]
        forecast = estimate(recipe, self.profile, links=30)
        self.assertEqual(forecast["range_usd"], [0, 0])
        self.assertEqual(forecast["compute_cost_basis"], "unmetered_infrastructure")
        self.assertIsNone(forecast["infrastructure_cost_usd"])
        self.assertEqual(len(experts(recipe, self.profile)), 1 + len(recipe["specialist_lenses"]))
        recipe["execution"]["max_calls"] = 1
        self.project.configure(recipe, self.profile)
        self.project.add_source(parse_document(b"This tokenizer uses BPE.", "text/plain", "synthetic.txt"))
        provider = FakeProvider([])
        self.project.collect(provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertIn(self.project.status()["stop_reason"], {"planning_limit_or_cancel_exhausted", "request_budget_exhausted"})
        with self.assertRaises(ValueError): self.project.configure_compute(**dict(self.settings, model_version="v2"))

    def test_snapshot_reexport_keeps_endpoint_version_without_environment_values(self):
        profile = self.project.configure_compute(**self.settings)
        recipe = starter_recipe("jargon")
        recipe["model_profile"] = "configured"
        for lens in recipe["specialist_lenses"]: lens["model"] = "researcher"
        self.project.configure(recipe)
        self.project.add_source(parse_document(b"This tokenizer uses BPE.", "text/plain", "synthetic.txt"))
        self.project.collect(FakeProvider([]))
        version = self.project.snapshot("compute-v1")
        first, second = Path(self.temp.name) / "one", Path(self.temp.name) / "two"
        for dest in (first, second): self.project.export(version, dest, formats=["jsonl", "csv"])
        for file in first.iterdir():
            if file.is_file(): self.assertEqual(file.read_bytes(), (second / file.name).read_bytes())
        self.assertIn("fixture-checkpoint", json.dumps(self.project.dataset(version)["profile"]))
        self.assertNotIn("UNRELATED_TOKEN", json.dumps(self.project.dataset(version)))
        with self.assertRaises(ValueError): self.project.collect()


if __name__ == "__main__": unittest.main()
