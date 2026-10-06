import hashlib
import unittest

from termfinder.evaluation import evaluate, source_splits, validate_gold


def fixture():
    text = "😀 猫語 then jargon and 猫語."
    source = {"source_id": "s1", "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "domain": "culture", "language": "ja", "locator": "local:fixture"}
    dataset = {"version_id": "v1", "sources": [source], "terms": [{"term_id": "t1", "expression": "猫語", "language": "ja", "sense": "first sense"}, {"term_id": "t2", "expression": "jargon", "language": "en", "sense": "technical language"}], "occurrences": [{"term_id": "t1", "source_id": "s1", "expression": "猫語", "language": "ja", "start": 2, "end": 4}, {"term_id": "t2", "source_id": "s1", "expression": "jargon", "language": "en", "start": 10, "end": 16}]}
    gold = [{"source_id": "s1", "text_sha256": source["text_sha256"], "complete": True, "terms": [{"expression": "猫語", "language": "ja", "sense": "first sense", "occurrences": [{"start": 2, "end": 4}, {"start": 21, "end": 23}]}]}]
    return dataset, gold


class EvaluationTests(unittest.TestCase):
    def test_occurrence_metrics_and_visible_false_negatives(self):
        dataset, gold = fixture()
        result = evaluate(dataset, gold, heldout_source_ids=["s1"])
        self.assertEqual(result["overall"]["true_positives"], 1)
        self.assertEqual(result["overall"]["false_positives"], 1)
        self.assertEqual(result["overall"]["false_negatives"], 1)
        self.assertEqual(result["overall"]["recall"], .5)
        self.assertEqual(result["by_language"]["ja"]["recall"], .5)
        self.assertEqual(result["by_domain"]["culture"]["false_negatives"], 1)
        self.assertEqual(result["false_negatives"][0]["start"], 21)
        self.assertIn("猫語", result["false_negatives"][0]["context"])
        # Source-term recall differs explicitly from occurrence recall.
        terms = evaluate(dataset, gold, unit="source_term")
        self.assertEqual(terms["overall"]["recall"], 1)

    def test_sense_matching_optional_and_preserves_distinct_senses(self):
        dataset, gold = fixture()
        gold[0]["terms"][0]["sense"] = "human revised sense"
        self.assertEqual(evaluate(dataset, gold)["overall"]["true_positives"], 1)
        self.assertEqual(evaluate(dataset, gold, require_sense=True)["overall"]["true_positives"], 0)
        gold[0]["terms"][0].pop("sense")
        with self.assertRaises(ValueError):
            evaluate(dataset, gold, require_sense=True)

    def test_reject_candidate_only_incomplete_stale_unicode_gold(self):
        for mutation in (lambda g: g[0].update(complete=False), lambda g: g[0].update(text_sha256="old"), lambda g: g[0]["terms"][0]["occurrences"][0].update(start=3), lambda g: g.append(g[0])):
            dataset, gold = fixture()
            mutation(gold)
            with self.assertRaises(ValueError):
                validate_gold(gold, dataset["sources"])
        dataset, gold = fixture()
        with self.assertRaises(ValueError):
            evaluate(dataset, gold, heldout_source_ids=["s1", "s2"])

    def test_complete_negative_sources_and_grouped_no_leakage_splits(self):
        dataset, gold = fixture()
        gold[0]["terms"] = []
        result = evaluate(dataset, gold)
        self.assertIsNone(result["overall"]["recall"])
        self.assertEqual(result["overall"]["false_positives"], 2)
        sources = [{"source_id": f"s{i}", "publication_id": f"p{i//3}"} for i in range(30)]
        splits = source_splits(sources, seed="example", group_field="publication_id")
        reverse = source_splits(list(reversed(sources)), seed="example", group_field="publication_id")
        self.assertEqual(splits, reverse)
        seen = {}
        for label, ids in splits["splits"].items():
            for source_id in ids:
                group = sources[int(source_id[1:])]["publication_id"]
                self.assertEqual(seen.setdefault(group, label), label)


if __name__ == "__main__":
    unittest.main()
