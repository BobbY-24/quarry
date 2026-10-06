"""Offline token admission, runtime declarations and bounded GPU scheduling."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from termfinder import Project, FakeProvider
from termfinder.config import load_profile, starter_recipe
from termfinder.costs import estimate
from termfinder.engine import Engine
from termfinder.resilience import cluster_execution
from termfinder.runtime import PromptTokenizer, validate_runtime
from termfinder.sources import parse_document
from termfinder.token_windows import token_admission, planned_windows


class GPUExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / "study")
        self.recipe = starter_recipe("jargon")
        self.recipe["execution"]["concurrency"] = 1
        self.recipe["execution"].pop("resilience", None)
        self.profile = load_profile("fake")

    def test_tokenizer_windows_preserve_every_unicode_codepoint_and_overlap(self):
        text = ("🧪 Cafe\u0301 中文 العربية " * 24)
        tokenizer = PromptTokenizer("fixture", "v1", lambda prompt: len(prompt))
        execution = dict(self.recipe["execution"], window_chars=160, overlap_chars=12)
        model = dict(self.profile["models"]["glm"], context_limit_tokens=230)
        rows = list(planned_windows(text, execution, model, lambda fragment: "HEAD:" + fragment,
                                    tokenizer=tokenizer, max_output_tokens=128))
        self.assertGreater(len(rows), 3)
        covered = set()
        for start, end, admission in rows:
            covered.update(range(start, end))
            self.assertTrue(admission["admitted"])
            self.assertEqual(admission["input_tokens"], 5 + len(text[start:end]))
            self.assertEqual(admission["method"], "trusted_registered_prompt_tokenizer")
        self.assertEqual(covered, set(range(len(text))))

    def test_fallback_is_explicit_and_includes_output_and_template_reserve(self):
        model = dict(self.profile["models"]["glm"], context_limit_tokens=400,
                     prompt_overhead_tokens=30)
        result = token_admission(model, "🧪汉字", 128)
        self.assertEqual(result["input_tokens"], 40)
        self.assertEqual(result["total_reserved_tokens"], 168)
        self.assertIn("unavailable", result["reason"])
        self.assertEqual(result["method"], "utf8_bytes_plus_template_reserve")
        self.assertTrue(result["admitted"])
        with self.assertRaises(ValueError): token_admission(model, "x", -1)

    def test_oversized_recipe_prompt_is_partial_without_dispatch_or_lost_source(self):
        model = self.profile["models"]["glm"]
        model.update(context_limit_tokens=256, input_token_ceiling=256, output_token_ceiling=128, prompt_overhead_tokens=30)
        self.profile["broad"] = [self.profile["broad"][0]]
        self.recipe["execution"]["max_output_tokens"] = 128
        self.recipe["execution"]["recovery_output_tokens"] = 128
        self.project.configure(self.recipe, self.profile)
        text = "A 🧪 tokenizer preserves Cafe\u0301 and 汉字." * 50
        self.project.add_source(parse_document(text.encode(), "text/plain", "fixture.txt"))
        provider = FakeProvider([])
        self.project.collect(provider)
        self.assertFalse(provider.calls)
        jobs = self.project.inventory()["jobs"]
        self.assertTrue(jobs)
        self.assertTrue(all(j["status"] == "partial" for j in jobs))
        self.assertTrue(all(j["reason"] == "prompt_overhead_exceeds_context_capacity" for j in jobs))
        self.assertEqual(self.project.status()["status"], "partial")
        self.assertTrue(self.project.inventory()["audit"])
        self.assertEqual(self.project.inventory()["sources"][0]["text"], text)

    def test_registered_tokenizer_identity_invalidates_jobs_and_retains_pass_identity(self):
        self.profile["models"]["glm"].update(context_limit_tokens=20000, input_token_ceiling=20000, output_token_ceiling=8192)
        self.project.configure(self.recipe, self.profile)
        self.project.add_source(parse_document(b"This tokenizer uses BPE.", "text/plain", "fixture.txt"))
        one = Engine(self.project, FakeProvider([]), tokenizers={"glm": PromptTokenizer("fixture", "v1", len)})
        first = one.prepare()
        two = Engine(self.project, FakeProvider([]), tokenizers={"glm": PromptTokenizer("fixture", "v2", len)})
        second = two.prepare()
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(first[1], second[1])
        self.assertEqual(self.project.store.get("jobs", first[0])["expert"]["id"], "glm-general")
        self.assertEqual(self.project.store.get("jobs", first[1])["expert"]["id"], "deepseek-general")

    def test_runtime_changes_invalidate_cache_and_preserve_grounded_provenance(self):
        runtime = validate_runtime({"checkpoint_sha256": "a" * 64, "runtime_name": "fixture", "runtime_version": "1"})
        self.profile["models"]["glm"]["runtime"] = runtime
        self.project.configure(self.recipe, self.profile)
        text = "This tokenizer uses BPE."
        self.project.add_source(parse_document(text.encode(), "text/plain", "fixture.txt"))
        expectation = dict(expression="BPE", language="en", sense="a tokenizer", context=text)
        provider = FakeProvider([expectation])
        self.project.collect(provider)
        count = len(provider.calls)
        self.project.resume(provider)
        self.assertEqual(len(provider.calls), count)
        self.profile["models"]["glm"]["runtime"]["checkpoint_sha256"] = "b" * 64
        self.project.configure(self.recipe, self.profile)
        self.project.resume(provider)
        self.assertEqual(len(provider.calls), count + 1)
        rows = self.project.inventory()["occurrences"]
        self.assertEqual(len(rows), 1)
        declared = [p["runtime"] for p in rows[0]["provenance"] if p["expert_id"] == "glm-general"]
        self.assertEqual({r["checkpoint_sha256"] for r in declared}, {"a" * 64, "b" * 64})
        self.assertTrue(all(r["origin"] == "operator_declared" for r in declared))

    def test_runtime_allowlist_rejects_code_credentials_and_nonfinite_decoding(self):
        invalid = [{"shell": "anything"}, {"checkpoint_sha256": "wrong"},
                   {"container_digest": "latest"}, {"decode": {"temperature": float("nan")}},
                   {"gpu_count": True}, {"decode": {"execute": "anything"}},
                   {"api_key": "synthetic"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError): validate_runtime(value)
        runtime = validate_runtime({"quantization": "none", "decode": {"temperature": 0, "seed": 42}})
        self.assertIsNone(runtime["gpu_model"])
        self.assertEqual(runtime["unavailable_reasons"]["gpu_model"], "not_declared_by_operator")

    def test_cluster_throughput_changes_only_bounded_scheduling_fields(self):
        original = deepcopy(self.recipe["execution"])
        tuned = cluster_execution(original, concurrency=8, model_concurrency=4)
        self.assertEqual(tuned["concurrency"], 8)
        self.assertEqual(tuned["resilience"]["model_concurrency"], 4)
        self.assertEqual(tuned["resilience"]["min_request_interval_seconds"], 0)
        for key in original:
            if key not in {"concurrency", "resilience"}: self.assertEqual(original[key], tuned[key])
        for values in ((0, 1), (65, 1), (2, 3), (True, 1)):
            with self.assertRaises(ValueError): cluster_execution(original, concurrency=values[0], model_concurrency=values[1])

    def test_context_admission_does_not_bypass_cost_reservation(self):
        self.profile["models"]["glm"].update(context_limit_tokens=20000, input_token_ceiling=20000, output_token_ceiling=8192, input_per_million=1)
        self.profile["broad"] = [self.profile["broad"][0]]
        self.recipe["execution"]["budget_usd"] = 0.001
        self.project.configure(self.recipe, self.profile)
        self.project.add_source(parse_document(b"This tokenizer uses BPE.", "text/plain", "fixture.txt"))
        provider = FakeProvider([])
        self.project.collect(provider)
        self.assertFalse(provider.calls)
        self.assertIn("reservation", self.project.status()["stop_reason"])

    def test_cost_forecast_and_engine_use_the_same_complete_prompt_admission(self):
        self.profile["models"]["glm"].update(context_limit_tokens=7500, input_token_ceiling=7500,
            output_token_ceiling=128, input_per_million=1)
        self.profile["broad"] = [self.profile["broad"][0]]
        self.recipe["execution"].update(max_output_tokens=128, recovery_output_tokens=128,
            window_chars=2400, overlap_chars=20)
        text = "🧪 Cafe\u0301 汉字 tokenizer. " * 120
        self.project.configure(self.recipe, self.profile)
        self.project.add_source(parse_document(text.encode(), "text/plain", "fixture.txt"))
        sources = self.project.inventory()["sources"]
        counter = PromptTokenizer("fixture", "v1", lambda prompt: len(prompt.encode()))
        report = estimate(self.recipe, self.profile, sources, tokenizers={"glm": counter},
                          cache_fraction=0, recovery_fraction=0, output_tokens_per_window=128)
        api_report = self.project.estimate(tokenizers={"glm": counter},
            cache_fraction=0, recovery_fraction=0, output_tokens_per_window=128)
        self.assertEqual(api_report["range_usd"], report["range_usd"])
        self.assertEqual(api_report["scenarios"][0]["estimated_calls"], report["scenarios"][0]["estimated_calls"])
        engine = Engine(self.project, FakeProvider([]), tokenizers={"glm": counter})
        roots = engine.prepare()
        jobs = [self.project.store.get("jobs", key) for key in roots]
        self.assertEqual(report["scenarios"][0]["estimated_calls"], len(jobs))
        self.assertTrue(report["scenarios"][0]["fits_context_capacity"])
        self.assertTrue(all(j["token_admission"]["admitted"] for j in jobs))
        self.assertAlmostEqual(report["range_usd"][0], sum(j["token_admission"]["input_tokens"] for j in jobs) / 1000000)

    def test_tokenizer_failure_uses_safe_fallback_and_mismatched_hash_is_rejected(self):
        def failed(_): raise RuntimeError("synthetic unrelated path must not be persisted")
        model = dict(self.profile["models"]["glm"], context_limit_tokens=10000)
        result = token_admission(model, "汉字", 128, tokenizer=PromptTokenizer("fixture", "v1", failed))
        self.assertEqual(result["reason"], "trusted_prompt_tokenizer_failed_conservative_fallback")
        self.assertNotIn("unrelated path", str(result))
        model["runtime"] = {"tokenizer_sha256": "a" * 64}
        with self.assertRaises(ValueError):
            token_admission(model, "text", 128, tokenizer=PromptTokenizer("fixture", "v1", len, tokenizer_sha256="b" * 64))

    def test_truncation_children_are_admitted_before_requests(self):
        from termfinder import Response
        self.profile["models"]["glm"].update(context_limit_tokens=10000, input_token_ceiling=10000,
            output_token_ceiling=512)
        self.profile["broad"] = [self.profile["broad"][0]]
        self.recipe["execution"].update(max_output_tokens=128, recovery_output_tokens=512)
        self.project.configure(self.recipe, self.profile)
        text = "🧪 Cafe\u0301 汉字 tokenizer. " * 100
        self.project.add_source(parse_document(text.encode(), "text/plain", "fixture.txt"))
        class Checked(FakeProvider):
            def complete(inner, request):
                self.assertTrue(token_admission(self.profile["models"]["glm"], request["prompt"], request["max_output_tokens"])["admitted"])
                return super(Checked, inner).complete(request)
        provider = Checked([], [Response('{"candidates": [], "coverage_complete": false}', 200, 50, "length")])
        self.project.collect(provider)
        self.assertGreater(len(provider.calls), 1)
        self.assertEqual(self.project.status()["status"], "complete")

    def test_cluster_throughput_is_operator_setting_without_changing_recipe(self):
        self.project.configure(self.recipe, self.profile)
        before = deepcopy(self.project.recipe)
        self.project.store.setting("cluster_throughput", {"concurrency": 8, "model_concurrency": 4})
        engine = Engine(self.project, FakeProvider([]))
        self.assertEqual(engine.execution["concurrency"], 8)
        self.assertEqual(engine.resilience["model_concurrency"], 4)
        self.assertEqual(self.project.recipe, before)
        self.assertFalse(engine.resilience["automatic_uncertain_retries"])

    def test_cluster_runtime_changes_only_affected_cache_and_resume_reuses_same_artifacts(self):
        self.project.configure(self.recipe, self.profile)
        self.project.add_source(parse_document(b"This tokenizer uses BPE.", "text/plain", "fixture.txt"))
        declared = {"runtime": {"runtime_id": "reviewed-python", "python_sha256": "a" * 64},
                    "model_artifacts": [{"model_alias": alias, "checkpoint_id": alias + "-checkpoint",
                        "sha256": "b" * 64, "quantization": None} for alias in self.profile["models"]],
                    "job_id": "fixture-first", "resources": {"gpus": 1}}
        self.project.store.setting("cluster_execution", declared)
        first = Engine(self.project, FakeProvider([])).prepare()
        declared.update(job_id="fixture-resume", resources={"gpus": 2})
        self.project.store.setting("cluster_execution", declared)
        self.assertEqual(first, Engine(self.project, FakeProvider([])).prepare())
        declared["model_artifacts"][0]["sha256"] = "c" * 64
        self.project.store.setting("cluster_execution", declared)
        changed = Engine(self.project, FakeProvider([])).prepare()
        self.assertNotEqual(first[0], changed[0])
        self.assertEqual(first[1], changed[1])
        declaration = self.project.store.get("jobs", changed[0])["declared_cluster_runtime"]
        self.assertEqual(declaration["checkpoint_sha256"], "c" * 64)
        self.assertNotIn("job_id", declaration)

    def test_owned_server_version_invalidates_cache_but_readiness_and_allocation_metadata_do_not(self):
        self.project.configure(self.recipe, self.profile)
        text = "This tokenizer uses BPE."
        self.project.add_source(parse_document(text.encode(), "text/plain", "fixture.txt"))
        provider = FakeProvider([dict(expression="BPE", language="en", sense="a tokenizer", context=text)])
        declared = {"runtime": {"runtime_id": "reviewed-python", "python_sha256": "a" * 64},
                    "model_artifacts": [{"model_alias": alias, "checkpoint_id": alias + "-checkpoint",
                        "sha256": "b" * 64, "quantization": None} for alias in self.profile["models"]],
                    "resources": {"gpus": 1, "server": {"adapter": "vllm", "model_alias": "glm",
                        "package_version": "0.11.0", "port": 18880}}}
        self.project.store.setting("cluster_execution", declared)
        before_ready = Engine(self.project, provider).prepare()
        declared["server"] = {"adapter": "vllm", "model_alias": "glm", "package_version": "0.11.0",
            "served_model_name": self.profile["models"]["glm"]["model"], "load_format": "safetensors",
            "generation_config": "vllm", "distributed_executor_backend": "mp", "plugin_autoload": "disabled",
            "remote_model_code": "disabled", "ready_at": "fixture-first", "startup_seconds": 0.1,
            "endpoint": "http://127.0.0.1:18880/v1"}
        self.project.store.setting("cluster_execution", declared)
        self.assertEqual(before_ready, Engine(self.project, provider).prepare())
        self.project.collect(provider)
        count = len(provider.calls)
        declared["resources"].update(gpus=2)
        declared["resources"]["server"]["port"] = 18881
        declared["server"].update(ready_at="fixture-resume", startup_seconds=9.5,
            endpoint="http://127.0.0.1:18881/v1")
        self.project.store.setting("cluster_execution", declared)
        self.project.resume(provider)
        self.assertEqual(count, len(provider.calls))
        declared["resources"]["server"]["package_version"] = "0.12.0"
        declared["server"]["package_version"] = "0.12.0"
        self.project.store.setting("cluster_execution", declared)
        changed = Engine(self.project, provider).prepare()
        self.assertNotEqual(before_ready[0], changed[0])
        self.assertEqual(before_ready[1], changed[1])
        self.project.resume(provider)
        self.assertEqual(count + 1, len(provider.calls))
        occurrence = self.project.inventory()["occurrences"][0]
        versions = {p["declared_cluster_runtime"]["owned_serving"]["package_version"]
            for p in occurrence["provenance"] if p["expert_id"] == "glm-general"}
        self.assertEqual(versions, {"0.11.0", "0.12.0"})
        identity = self.project.store.get("jobs", changed[0])["declared_cluster_runtime"]["owned_serving"]
        self.assertNotIn("ready_at", identity)
        self.assertNotIn("endpoint", identity)

    def test_owned_server_receipt_cannot_disagree_with_approved_loader_or_version(self):
        self.project.configure(self.recipe, self.profile)
        declared = {"runtime": {"runtime_id": "reviewed-python", "python_sha256": "a" * 64},
                    "model_artifacts": [{"model_alias": alias, "checkpoint_id": alias + "-checkpoint",
                        "sha256": "b" * 64, "quantization": None} for alias in self.profile["models"]],
                    "resources": {"server": {"adapter": "vllm", "model_alias": "glm", "package_version": "0.11.0"}}}
        for changes in ({"package_version": "0.12.0"}, {"load_format": "auto"}, {"plugin_autoload": "enabled"}):
            declared["server"] = dict(adapter="vllm", model_alias="glm", **changes)
            self.project.store.setting("cluster_execution", declared)
            with self.subTest(changes=changes), self.assertRaises(ValueError): Engine(self.project, FakeProvider([]))


if __name__ == "__main__": unittest.main()
