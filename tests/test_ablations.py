from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from termfinder.adapters import RecordedBackend, adapter_config, run_adapter
from termfinder.ablations import (execute_ablations, make_ablation_manifest, union_runs, validate_ablation_manifest,
    prepare_quarry_ablations, run_prepared_quarry_ablations)
from test_adapters import corpus_fixture, reply


def component(corpus, run_id, expression="Moonstep", start=0, *, missing=False):
    fixtures = {s["source_id"]: {"calls": [reply(missing=missing)], "proposals": []} for s in corpus["sources"]}
    fixtures["positive"]["proposals"] = [{"observed_text": expression, "language": "en", "interpretation": None,
        "native_start": start, "native_end": start + len(expression), "retained": True}]
    return run_adapter(corpus, adapter_config("langextract"), RecordedBackend(fixtures), run_id=run_id)


class AblationTests(unittest.TestCase):
    def test_manifest_has_single_and_equal_pass_controls(self):
        manifest = make_ablation_manifest(["general-a", "general-b"], ["lexical", "semantic"], passes=3)
        arms = {a["arm_id"]: a for a in manifest["arms"]}
        self.assertEqual(len(arms["single-general-a"]["components"]), 1)
        self.assertEqual(len(arms["single-general-b"]["components"]), 1)
        self.assertEqual(len(arms["specialists"]["components"]), len(arms["general-control-for-specialists"]["components"]))
        self.assertEqual(arms["specialists"]["resource_envelope"], arms["general-control-for-specialists"]["resource_envelope"])
        self.assertEqual(arms["warm-repeated-general-extension"]["cache_regime"], "warm")
        with self.assertRaises(ValueError):
            validate_ablation_manifest(manifest | {"union_policy": "majority_vote"})

    def test_union_keeps_unique_single_model_discoveries_and_all_attribution(self):
        corpus = corpus_fixture()
        a = component(corpus, "a")
        b = component(corpus, "b", "moonstep", 14)
        c = component(corpus, "c")
        combined = union_runs(corpus, [a["run"], b["run"], c["run"]], run_id="union")
        self.assertEqual({p["observed_text"] for p in combined["run"]["predictions"]}, {"Moonstep", "moonstep"})
        self.assertEqual(len(combined["audit"]["attribution"][0]["contributors"]), 2)
        self.assertEqual(combined["audit"]["duplicate_proposals"][0]["union_prediction_id"], "union:0")
        self.assertEqual(len(combined["run"]["source_results"]), 3)

    def test_invalid_proposals_and_unknown_costs_survive_union(self):
        corpus = corpus_fixture()
        a = component(corpus, "a", "imagined", 0, missing=True)
        b = component(corpus, "b")
        union = union_runs(corpus, [a["run"], b["run"]], run_id="union")
        self.assertEqual(len(union["run"]["predictions"]), 2)
        self.assertFalse(union["audit"]["attribution"][0]["exact_grounded"])
        self.assertIsNone(next(c for c in union["run"]["costs"] if c["stage"] == "extraction")["known_usd"])
        broken = deepcopy(b["run"])
        broken["source_results"].pop()
        with self.assertRaises(ValueError):
            union_runs(corpus, [a["run"], broken], run_id="bad")

    def test_execution_namespaces_are_cold_except_explicit_warm_parent(self):
        corpus = corpus_fixture()
        manifest = make_ablation_manifest(["a", "b"], ["lexical"], passes=2)
        contexts = []
        def runner(arm, schedule, context):
            contexts.append(deepcopy(context))
            return component(corpus, context["run_id"])
        output = execute_ablations(corpus, manifest, runner)
        self.assertEqual(len(output["arms"]), len(manifest["arms"]))
        cold = [c for c in contexts if c["cache_regime"] == "cold"]
        self.assertEqual(len(cold), len({c["cache_namespace"] for c in cold}))
        warm = [c for c in contexts if c["cache_regime"] == "warm"]
        self.assertIsNotNone(warm[0]["parent_component_run"])
        self.assertTrue(warm[0]["cache_namespace"].startswith("repeated-general/"))
        self.assertIsNone(warm[-1]["parent_component_run"])

    def test_real_quarry_engine_arms_prepare_then_collect_and_warm_extend(self):
        from termfinder import Project
        from termfinder.config import starter_recipe, load_profile
        from termfinder.sources import parse_document
        with tempfile.TemporaryDirectory() as tmp:
            recipe, profile = starter_recipe("neologisms"), load_profile("fake")
            master = Project(Path(tmp) / "master")
            master.configure(recipe, profile=profile)
            text = "Crews call a pause a moonstep and a reserve a quietstack."
            for i, value in enumerate((text, "Ordinary water.")):
                master.add_source(parse_document(value.encode(), "text/plain", "fixture-" + str(i) + ".txt",
                    {"community": "Gaming", "language": "en", "domain": "synthetic"}))
            documents = master.dataset(master.snapshot("source-only"))["sources"]
            corpus = {"schema_version": "1", "corpus_id": "real-engine-shapes", "data_type": "term", "sources": [
                {k: d[k] for k in ("source_id", "text", "text_sha256", "domain", "language")} | {"family_id": str(i)} for i, d in enumerate(documents)]}
            plan = prepare_quarry_ablations(corpus, documents, Path(tmp) / "arms", recipe=recipe, profile=profile, passes=2)
            for row in plan["arms"]:
                if row["normalized_pre_run"] is not None:
                    self.assertFalse(Project(row["project_path"]).inventory()["jobs"])
                    self.assertIsNotNone(row["normalized_pre_run"]["provenance"]["prompt_sha256"])
            expectations = [{"expression": "moonstep", "language": "en", "sense": "a pause", "context": text},
                {"expression": "quietstack", "language": "en", "sense": "a reserve", "context": text, "expert_ids": ["deepseek-general"]}]
            output = run_prepared_quarry_ablations(corpus, plan, expectations=expectations)
            arms = {p["run"]["run_id"]: p for p in output["arms"]}
            self.assertEqual(len(arms), len(plan["manifest"]["arms"]))
            for packet in output["arms"]:
                self.assertTrue(packet["run"]["predictions"])
                self.assertEqual({s["status"] for s in packet["run"]["source_results"]}, {"complete"})
                self.assertEqual(len(packet["run"]["source_results"]), 2)
            self.assertEqual(len(arms["repeated-general"]["audit"]["actual_dispatches"]), 4)
            self.assertNotIn("quietstack", {p["observed_text"] for p in arms["repeated-general"]["run"]["predictions"]})
            self.assertIn("quietstack", {p["observed_text"] for p in arms["broad-mixed-union"]["run"]["predictions"]})
            self.assertIn("quietstack", {p["observed_text"] for p in arms["single-deepseek-general"]["run"]["predictions"]})
            warm = arms["warm-repeated-general-extension"]
            self.assertEqual(len(warm["audit"]["actual_dispatches"]), 2)
            self.assertEqual(warm["audit"]["cost_scope"], "cumulative_parent_and_extension")
            self.assertTrue(warm["audit"]["before_warm_snapshot_id"])
            mutated = deepcopy(plan)
            mutated["arms"][0]["recipe"]["research_question"] = "unfrozen change"
            with self.assertRaisesRegex(ValueError, "plan changed"):
                run_prepared_quarry_ablations(corpus, mutated, expectations=expectations)
            saved = Project(plan["arms"][0]["project_path"])
            changed = deepcopy(saved.recipe)
            changed["research_question"] = "edited after freeze"
            saved.configure(changed, profile=saved.profile)
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                run_prepared_quarry_ablations(corpus, plan, expectations=expectations)


if __name__ == "__main__":
    unittest.main()
