import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder.experiments import compare_experiments, compare_study, quarry_run
from termfinder.config import STAGES
from termfinder.cli import main


def fixture():
    sources = []
    for sid, text, family in (("s1", "😀 猫語 then 猫語", "family-a"), ("s2", "technical jargon", "family-b"), ("s3", "ordinary words", "family-c")):
        sources.append({"source_id": sid, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "domain": "culture" if sid == "s1" else "technical", "language": "ja" if sid == "s1" else "en", "family_id": family})
    corpus = {"schema_version": "1", "corpus_id": "tiny", "data_type": "term", "sources": sources}
    gold = [{"source_id": s["source_id"], "text_sha256": s["text_sha256"], "complete": True, "terms": []} for s in sources]
    gold[0]["terms"] = [{"expression": "猫語", "language": "ja", "sense": "label", "occurrences": [{"start": 2, "end": 4}, {"start": 10, "end": 12}]}]
    gold[1]["terms"] = [{"expression": "jargon", "language": "en", "sense": "label", "occurrences": [{"start": 10, "end": 16}]}]
    left = {"schema_version": "1", "run_id": "left", "system": "test-fixture", "data_type": "term", "proposal_population": "raw_proposals",
            "provenance": {"software_revision": "test-v1", "model_version": "fake-v1", "prompt_sha256": "a" * 64,
                           "configuration_sha256": "b" * 64, "adapter_version": "1", "unavailable_reasons": {}},
            "source_results": [{"source_id": s["source_id"], "text_sha256": s["text_sha256"], "status": "failed" if s["source_id"] == "s2" else "complete", "reason": "parse_failure" if s["source_id"] == "s2" else None} for s in sources],
            "predictions": [{"prediction_id": "p1", "source_id": "s1", "observed_text": "猫語", "language": "ja", "start": 2, "end": 4, "interpretation": "label"}],
            "costs": [{"stage": stage, "known_usd": 0.0, "uncertain_reserved_usd": 0.0, "basis": "simulated", "missing_reason": None} for stage in STAGES]}
    right = copy.deepcopy(left)
    right["run_id"] = "right"
    right["source_results"][1].update(status="complete", reason=None)
    right["predictions"] += [{"prediction_id": "p2", "source_id": "s1", "observed_text": "猫語", "language": "ja", "start": 10, "end": 12, "interpretation": "label"},
                             {"prediction_id": "p3", "source_id": "s2", "observed_text": "jargon", "language": "en", "start": 10, "end": 16, "interpretation": "label"}]
    return corpus, gold, [left, right]


class ExperimentTests(unittest.TestCase):
    def test_failed_and_negative_sources_stay_in_the_denominator(self):
        corpus, gold, runs = fixture()
        report = compare_experiments(corpus, gold, runs)
        left, right = report["runs"]
        self.assertEqual(left["detection"]["overall"]["true_positives"], 1)
        self.assertEqual(left["detection"]["overall"]["false_negatives"], 2)
        self.assertEqual(left["detection"]["overall"]["recall"], 1 / 3)
        self.assertEqual(left["by_source"][1]["status"], "failed")
        self.assertEqual(left["by_source"][1]["false_negatives"], 1)
        self.assertEqual(left["by_source"][2]["false_negatives"], 0)
        self.assertIsNone(left["by_source"][2]["recall"])
        self.assertEqual(left["coverage"]["source_count"], 3)
        self.assertEqual(right["detection"]["overall"]["recall"], 1)
        self.assertEqual(report["pairs"][0]["unique_gold_recoveries"], {"left": 0, "right": 2})
        runs[0]["predictions"].append({"prediction_id": "negative-source-fp", "source_id": "s3", "observed_text": "ordinary",
                                       "language": "en", "start": 0, "end": 8, "interpretation": None})
        report = compare_experiments(corpus, gold, runs)
        self.assertEqual(report["runs"][0]["by_source"][2]["false_positives"], 1)
        self.assertEqual(report["runs"][0]["detection"]["overall"]["precision"], .5)
        corpus, gold, runs = fixture()
        result = compare_experiments(corpus, gold, runs, unit="source_term")
        self.assertEqual(result["runs"][0]["detection"]["overall"]["recall"], .5)

    def test_invalid_proposals_audited_and_duplicates_cannot_inflate_recall(self):
        corpus, gold, runs = fixture()
        duplicate = {**runs[0]["predictions"][0], "prediction_id": "duplicate"}
        invalid = {**duplicate, "prediction_id": "invented", "observed_text": "hallucinated"}
        runs[0]["predictions"] += [duplicate, invalid]
        report = compare_experiments(corpus, gold, runs)["runs"][0]
        self.assertEqual(report["raw_proposals"]["submitted"], 3)
        self.assertEqual(report["raw_proposals"]["duplicate_grounded_observations"], 1)
        self.assertEqual(report["raw_proposals"]["invalid"], 1)
        self.assertEqual(report["raw_proposals"]["invalid_queue"][0]["proposal"], invalid)
        self.assertEqual(report["detection"]["overall"]["true_positives"], 1)

    def test_unicode_bytes_and_sense_claims_not_silently_repaired(self):
        corpus, gold, runs = fixture()
        runs[0]["predictions"][0].update(start=5, end=7)
        result = compare_experiments(corpus, gold, runs)
        self.assertEqual(result["runs"][0]["raw_proposals"]["invalid"], 1)
        self.assertEqual(result["runs"][0]["detection"]["overall"]["false_negatives"], 3)
        corpus, gold, runs = fixture()
        runs[0]["predictions"][0]["interpretation"] = "different paraphrase"
        self.assertEqual(compare_experiments(corpus, gold, runs)["runs"][0]["detection"]["overall"]["true_positives"], 1)
        self.assertEqual(compare_experiments(corpus, gold, runs, require_sense=True)["runs"][0]["detection"]["overall"]["true_positives"], 0)
        runs[0]["predictions"][0]["interpretation"] = {"unstructured": "meaning"}
        result = compare_experiments(corpus, gold, runs)["runs"][0]
        self.assertEqual(result["detection"]["overall"]["true_positives"], 1)
        self.assertEqual(result["raw_proposals"]["attribute_issues"], 1)
        self.assertEqual(result["raw_proposals"]["exact_grounding_rate"], 1)
        self.assertEqual(result["raw_proposals"]["invalid"], 0)

    def test_manifest_hash_status_identity_and_money_validation(self):
        mutations = [lambda c, g, r: r[0]["source_results"].pop(),
                     lambda c, g, r: r[0]["source_results"][0].update(text_sha256="stale"),
                     lambda c, g, r: c["sources"][0].update(text="edited source"),
                     lambda c, g, r: g.pop(),
                     lambda c, g, r: r[0]["source_results"][1].update(reason=None),
                     lambda c, g, r: r[0]["predictions"].append(r[0]["predictions"][0]),
                     lambda c, g, r: r[0]["costs"].pop(),
                     lambda c, g, r: r[0]["costs"][0].update(known_usd=float("nan")),
                     lambda c, g, r: r[0]["provenance"].update(software_revision=None)]
        for mutate in mutations:
            corpus, gold, runs = fixture()
            mutate(corpus, gold, runs)
            with self.assertRaises(ValueError):
                compare_experiments(corpus, gold, runs)
        corpus, gold, runs = fixture()
        for row in runs[0]["costs"]:
            row["known_usd"] = 1e308
        with self.assertRaisesRegex(ValueError, "Aggregated cost"):
            compare_experiments(corpus, gold, runs)
        corpus, gold, runs = fixture()
        with self.assertRaisesRegex(ValueError, "Comparison unit"):
            compare_experiments(corpus, gold, runs, unit=[])
        gold[0]["terms"][0]["sense"] = {"ambiguous": "label"}
        with self.assertRaisesRegex(ValueError, "Gold interpretation"):
            compare_experiments(corpus, gold, runs, require_sense=True)

    def test_unknown_cost_is_not_free_and_uncertainty_is_visible(self):
        corpus, gold, runs = fixture()
        runs[0]["costs"][2].update(known_usd=None, uncertain_reserved_usd=.4, basis="not_metered", missing_reason="lost_response")
        costs = compare_experiments(corpus, gold, runs)["runs"][0]["costs"]
        self.assertFalse(costs["complete"])
        self.assertEqual(costs["known_subtotal_usd"], 0)
        self.assertEqual(costs["uncertain_reserved_subtotal_usd"], .4)
        self.assertEqual(costs["incomplete_stages"], ["extraction"])

    def test_bootstrap_is_reproducible_and_resamples_families(self):
        corpus, gold, runs = fixture()
        # Every family has a gold positive here; avoid undefined negative-only resamples.
        corpus["sources"] = corpus["sources"][:2]
        gold = gold[:2]
        for run in runs:
            run["source_results"] = run["source_results"][:2]
        first = compare_experiments(corpus, gold, runs, bootstrap_samples=200, seed="paired")
        second = compare_experiments(corpus, gold, runs, bootstrap_samples=200, seed="paired")
        self.assertEqual(first, second)
        ci = first["pairs"][0]["uncertainty"]
        self.assertEqual(ci["family_count"], 2)
        self.assertEqual(ci["effective_replicates"]["recall"], 200)
        self.assertIsNotNone(ci["intervals_95"]["recall"])
        corpus["sources"][1]["family_id"] = "family-a"
        ci = compare_experiments(corpus, gold, runs, bootstrap_samples=20)["pairs"][0]["uncertainty"]
        self.assertEqual(ci["null_reason"], "fewer_than_two_families")
        self.assertIsNone(ci["intervals_95"]["recall"])
        corpus, gold, runs = fixture()
        ci = compare_experiments(corpus, gold, runs, bootstrap_samples=1000, seed="negative-resamples")["pairs"][0]["uncertainty"]
        self.assertLess(ci["effective_replicates"]["recall"], 1000)
        self.assertIsNone(ci["intervals_95"]["recall"])
        self.assertEqual(ci["null_reason"], "undefined_metric_replicates")

    def test_local_study_roundtrip_and_no_project_or_model_side_effect(self):
        corpus, gold, runs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("corpus.json", corpus), ("gold.json", gold), ("left.json", runs[0]), ("right.json", runs[1])):
                (root / name).write_text(json.dumps(value, ensure_ascii=False))
            study = {"schema_version": "1", "corpus": "corpus.json", "gold": "gold.json", "runs": ["left.json", "right.json"]}
            path = root / "study.json"
            path.write_text(json.dumps(study))
            direct = compare_study(path)
            out = root / "report.json"
            with patch("termfinder.providers.HTTPProvider.complete", side_effect=AssertionError("No model calls")), patch("termfinder.project.Project.__init__", side_effect=AssertionError("No project creation")), patch("builtins.print"):
                self.assertEqual(main(["compare-experiments", str(path), "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text()), direct)
            self.assertEqual(direct["input_files_sha256"]["left.json"], hashlib.sha256((root / "left.json").read_bytes()).hexdigest())
            study["corpus"] = "../escape.json"
            path.write_text(json.dumps(study))
            with self.assertRaises(ValueError):
                compare_study(path)

    def test_quarry_snapshot_bridge_retains_partial_evidence_and_unknown_reserves(self):
        corpus, gold, runs = fixture()
        snapshot = {"sources": corpus["sources"], "recipe": {"data_type": "term"}, "profile": {"models": {"m": {"version": "fake"}}},
                    "terms": [{"term_id": "t", "expression": "猫語", "language": "ja", "sense": "label"}],
                    "occurrences": [{"term_id": "t", "occurrence_id": "o", "source_id": "s1", "expression": "猫語", "language": "ja", "start": 2, "end": 4}],
                    "jobs": [{"source_id": "s1", "status": "done"}, {"source_id": "s1", "status": "failed"}, {"source_id": "s2", "status": "uncertain"}],
                    "costs": [{"stage": "extraction", "billing_kind": "estimated", "settled_usd": None, "reserved_usd": .7}]}
        normalized = quarry_run(snapshot, run_id="normalized", software_revision="test")
        self.assertEqual([r["status"] for r in normalized["source_results"]], ["partial", "uncertain", "pending"])
        self.assertEqual(normalized["predictions"][0]["observed_text"], "猫語")
        result = compare_experiments(corpus, gold, [normalized, runs[1]])
        self.assertEqual(result["runs"][0]["costs"]["uncertain_reserved_subtotal_usd"], .7)
        self.assertIsNone(result["runs"][0]["raw_proposals"]["exact_grounding_rate"])
        self.assertEqual(result["runs"][0]["raw_proposals"]["exact_grounding_rate_reason"], "raw_proposals_not_supplied")
        self.assertIn("infrastructure", result["runs"][0]["costs"]["incomplete_stages"])
        snapshot["jobs"] = [{"source_id": "s1", "status": "done"}]
        snapshot["runs"] = [{"created_at": "2026-01-01", "recipe": snapshot["recipe"], "profile": snapshot["profile"], "planning_complete": False}]
        normalized = quarry_run(snapshot, run_id="limited-plan")
        self.assertEqual(normalized["source_results"][0]["status"], "partial")
        self.assertIn("planning_coverage_unproven", normalized["source_results"][0]["reason"])

    def test_reject_oversized_run_list_before_loading_and_bound_bootstrap_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.json"
            path.write_text(json.dumps({"schema_version": "1", "corpus": "missing", "gold": "missing", "runs": ["missing"] * 21}))
            with self.assertRaisesRegex(ValueError, "run list"):
                compare_study(path)
        corpus, gold, runs = fixture()
        many = [{**copy.deepcopy(runs[0]), "run_id": f"arm-{i}"} for i in range(20)]
        with self.assertRaisesRegex(ValueError, "Aggregate bootstrap"):
            compare_experiments(corpus, gold, many, bootstrap_samples=10000)


if __name__ == "__main__":
    unittest.main()
