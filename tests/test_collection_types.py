"""Typed collections keep exact source spans separate from generated readings.

All material is synthetic. Explicit fake responses test deterministic contracts,
not extraction accuracy. No credential environment or network is required.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from termfinder import FakeProvider, Project, Response
from termfinder.config import DATA_TYPES, load_profile, load_recipe, starter_recipe
from termfinder.evaluation import evaluate, validate_gold
from termfinder.exports import annotation_sources, dataset_record_view, export_dataset
from termfinder.grounding import ground, normalize
from termfinder.prompts import VERSION, build_prompt, manifest
from termfinder.sources import parse_document
from termfinder.store import ident


TEXT = "😀 Café. I think bilingual signage improves access. Keep the original wording."
SPAN = "I think bilingual signage improves access."


def proposal(expression=SPAN, sense="A speaker supports bilingual signs.", **overrides):
    return {"expression": expression, "language": "en", "sense": sense, "context": TEXT,
            "start": None, "definition_quote": None, "translation": None,
            "attributes": {}, **overrides}


def response(items=(), complete=True):
    return Response(json.dumps({"candidates": list(items), "coverage_complete": complete}, ensure_ascii=False),
                    50, 50, "stop", "synthetic-typed-v1")


class CollectionTypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Project(Path(self.tmp.name) / "project")
        self.recipe = starter_recipe("neologisms")
        self.recipe["execution"]["concurrency"] = 1
        self.recipe["id"] = "synthetic-typed-collection"
        self.project.configure(self.recipe, "fake")
        self.source_id = self.project.add_source(parse_document(TEXT.encode(), "text/plain", "synthetic.txt",
                                                              {"language": "en", "community": "Gaming"}))

    def configure(self, data_type):
        self.recipe["data_type"] = data_type
        self.project.configure(self.recipe, "fake")

    def collect(self, items, complete=True):
        provider = FakeProvider([], [response(items, complete), response([])])
        self.project.collect(provider)
        return provider

    def records(self):
        return dataset_record_view(self.project.inventory())

    def saved(self):
        return self.project.dataset(self.project.snapshot("synthetic typed evidence"))

    def gold(self, data_type, expression=SPAN, *, sense="A speaker supports bilingual signs."):
        source = self.project.store.get("sources", self.source_id)
        start = source["text"].index(expression)
        return [{"source_id": self.source_id, "text_sha256": source["text_sha256"],
                 "complete": True, "data_type": data_type,
                 "terms" if data_type == "term" else "records": [{"record_type": data_type,
                     "observed_text": expression, "interpretation": sense, "language": "en",
                     "start": start, "end": start + len(expression)}]}]

    def test_optional_type_preserves_legacy_recipe_and_strict_validation(self):
        legacy = starter_recipe("neologisms")
        self.assertNotIn("data_type", load_recipe(legacy))
        for data_type in DATA_TYPES:
            recipe = deepcopy(legacy)
            recipe["data_type"] = data_type
            self.assertEqual(load_recipe(recipe)["data_type"], data_type)
        for bad in ("table", "generated_idea", None, ["term"]):
            recipe = deepcopy(legacy)
            recipe["data_type"] = bad
            with self.assertRaises(ValueError):
                load_recipe(recipe)

    def test_type_policies_explicitly_separate_observed_and_generated(self):
        expert = load_profile("fake")["broad"][0]
        for data_type in DATA_TYPES:
            self.recipe["data_type"] = data_type
            prompt = build_prompt(self.recipe, expert, TEXT)
            self.assertIn('"data_type":"' + data_type + '"', prompt)
            self.assertIn("exact verbatim source span", prompt)
            self.assertIn("never a generated summary", prompt)
        self.assertEqual(manifest()["version"], VERSION)
        self.assertEqual(set(manifest()["data_type_policies"]), DATA_TYPES)

    def test_nonterm_observed_span_generated_interpretation_and_unicode_offsets(self):
        for data_type in ("idea", "opinion", "sentence"):
            with self.subTest(data_type=data_type):
                self.configure(data_type)
                self.collect([proposal()])
                record = next(r for r in self.records() if r["record_type"] == data_type)
                self.assertEqual(record["observed_text"], SPAN)
                self.assertEqual(record["interpretation"], "A speaker supports bilingual signs.")
                self.assertEqual(record["interpretation_origin"], "model_generated")
                self.assertEqual(record["text_origin"], "observed_source")
                self.assertNotIn("coinage_date", record)
                occurrence = next(o for o in self.project.inventory()["occurrences"] if o["record_id"] == record["record_id"])
                source = self.project.store.get("sources", occurrence["source_id"])
                self.assertEqual(source["text"][occurrence["start"]:occurrence["end"]], record["observed_text"])
                self.assertEqual(occurrence["start"], TEXT.index(SPAN))
                self.assertFalse(occurrence["meaning_verified"])
                self.assertEqual(occurrence["provenance"][0]["record_type"], data_type)

    def test_generated_paraphrase_does_not_become_observed_record(self):
        self.configure("idea")
        self.collect([proposal(expression="Bilingual signs make communication equitable.")])
        self.assertFalse(self.records())
        self.assertIn("expression_absent_from_context", self.project.inventory()["audit"][0]["reason"])

    def test_invented_context_does_not_ground_an_opinion(self):
        self.configure("opinion")
        self.collect([proposal(context="A person says: " + SPAN)])
        self.assertFalse(self.records())
        self.assertIn("context_not_exact_in_window", self.project.inventory()["audit"][0]["reason"])

    def test_response_cannot_reclassify_collection_type(self):
        self.configure("opinion")
        self.collect([proposal(record_type="term")])
        self.assertEqual(self.records()[0]["record_type"], "opinion")
        self.assertIn("unknown_proposal_fields", self.project.inventory()["audit"][0]["reason"])

    def test_term_identity_stays_compatible_and_types_do_not_merge(self):
        item = proposal(expression="bilingual signage", sense="Signs in multiple languages.")
        source = self.project.store.get("sources", self.source_id)
        job = {"start": 0, "end": len(TEXT)}
        legacy, _ = ground(item, source, job, self.recipe, {})
        expected = ident("term", [normalize(item["expression"], "en"), "en", "Gaming", item["sense"]])
        self.assertEqual(legacy[0][0]["term_id"], expected)
        identities = {legacy[0][0]["term_id"]}
        for data_type in ("idea", "opinion", "sentence"):
            recipe = dict(self.recipe, data_type=data_type)
            rows, _ = ground(item, source, job, recipe, {})
            identities.add(rows[0][0]["term_id"])
        self.assertEqual(len(identities), 4)

    def test_same_opinion_in_different_sources_retains_distinct_record_ids(self):
        self.configure("opinion")
        other_id = self.project.add_source(parse_document(TEXT.encode(), "text/plain", "different-speaker.txt",
                                                        {"language": "en", "community": "Gaming"}))
        provider = FakeProvider([proposal()])
        self.project.collect(provider)
        records = self.records()
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["record_id"] for record in records}), 2)
        self.assertEqual({row["source_id"] for row in self.project.inventory()["occurrences"]}, {self.source_id, other_id})

    def test_distinct_interpretations_survive_same_exact_span(self):
        self.configure("opinion")
        self.project.collect(FakeProvider([], [response([proposal()]), response([proposal(sense="A policy recommendation.")])]))
        self.assertEqual(len(self.records()), 2)
        self.assertEqual({row["observed_text"] for row in self.records()}, {SPAN})

    def test_interruption_resume_cache_annotation_undo_for_nonterms(self):
        self.configure("sentence")
        provider = FakeProvider([proposal()])
        self.project.collect(provider, max_jobs=1)
        self.assertEqual(len(provider.calls), 1)
        reopened = Project(self.project.path)
        reopened.resume(provider)
        reopened.resume(provider)
        self.assertEqual(len(provider.calls), 2)
        record_id = dataset_record_view(reopened.inventory())[0]["record_id"]
        annotation_id = reopened.annotate(record_id, "approved", "Synthetic review.")
        self.assertEqual(dataset_record_view(reopened.inventory())[0]["review_status"], "approved")
        reopened.undo_annotation(annotation_id)
        self.assertEqual(dataset_record_view(reopened.inventory())[0]["review_status"], "unreviewed")

    def test_type_change_invalidates_calls_but_resuming_same_type_does_not(self):
        provider = FakeProvider([proposal()])
        self.configure("idea")
        self.project.collect(provider)
        self.project.resume(provider)
        self.assertEqual(len(provider.calls), 2)
        self.configure("opinion")
        self.project.collect(provider)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual({row["record_type"] for row in self.records()}, {"idea", "opinion"})

    def test_budget_stop_keeps_nonterm_pending(self):
        self.configure("idea")
        profile = load_profile("fake")
        for model in profile["models"].values():
            model["input_per_million"] = 1
        self.recipe["execution"]["budget_usd"] = 0
        self.project.configure(self.recipe, profile)
        provider = FakeProvider([proposal()])
        status = self.project.collect(provider)
        self.assertFalse(provider.calls)
        self.assertEqual(status["jobs"]["pending"], 2)
        self.assertIn("reservation", status["stop_reason"])

    def test_frozen_generic_exports_reproducible_and_lexical_terms_only(self):
        self.configure("opinion")
        self.collect([proposal()])
        saved = self.saved()
        first, second = Path(self.tmp.name) / "first", Path(self.tmp.name) / "second"
        before = json.dumps(saved, sort_keys=True)
        export_dataset(saved, first, ["csv", "jsonl", "parquet", "annotation"])
        export_dataset(saved, second, ["annotation", "parquet", "jsonl", "csv"])
        for path in first.iterdir():
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes(), path.name)
        self.assertEqual((first / "terms.jsonl").read_text(), "")
        self.assertEqual((first / "approved_terms.jsonl").read_text(), "")
        record = json.loads((first / "records.jsonl").read_text())
        evidence = json.loads((first / "evidence.jsonl").read_text())
        self.assertEqual(record["record_id"], evidence["record_id"])
        self.assertEqual(record["observed_text"], evidence["observed_text"])
        self.assertEqual(record["record_type"], "opinion")
        self.assertEqual(before, json.dumps(saved, sort_keys=True))

    def test_typed_blind_packets_exact_span_evaluation_and_false_negatives(self):
        self.configure("opinion")
        self.collect([proposal()])
        saved = self.saved()
        packet = annotation_sources(saved)[0]
        self.assertEqual(packet["data_type"], "opinion")
        self.assertEqual(packet["records"], [])
        self.assertNotIn("terms", packet)
        gold = self.gold("opinion")
        result = evaluate(saved, gold, heldout_source_ids=[self.source_id])
        self.assertEqual(result["data_type"], "opinion")
        self.assertEqual(result["overall"]["recall"], 1)
        self.assertIn("factual truth", result["limitations"])
        other = "Keep the original wording."
        source = self.project.store.get("sources", self.source_id)
        gold[0]["records"].append({"record_type": "opinion", "observed_text": other,
                                    "language": "en", "start": TEXT.index(other), "end": len(TEXT)})
        result = evaluate(saved, gold)
        self.assertEqual(result["overall"]["false_negatives"], 1)
        self.assertEqual(result["false_negatives"][0]["observed_text"], other)
        with self.assertRaises(ValueError):
            evaluate(saved, gold, unit="source_term")
        for mutation in (lambda g: g[0].update(data_type="idea"),
                         lambda g: g[0]["records"][0].update(record_type="term"),
                         lambda g: g[0]["records"][0].update(expression="A conflicting observed span."),
                         lambda g: g[0]["records"][0].update(sense="A conflicting human interpretation."),
                         lambda g: g[0]["records"][0].update(observed_text="A generated summary.")):
            invalid = deepcopy(self.gold("opinion"))
            mutation(invalid)
            with self.assertRaises(ValueError):
                evaluate(saved, invalid)
        self.assertEqual(validate_gold(self.gold("opinion"), [source])[0]["record_type"], "opinion")

    def test_generated_interpretation_matching_is_opt_in(self):
        self.configure("idea")
        self.collect([proposal()])
        saved = self.saved()
        gold = self.gold("idea", sense="A human reading with a different rubric label.")
        self.assertEqual(evaluate(saved, gold)["overall"]["true_positives"], 1)
        self.assertEqual(evaluate(saved, gold, require_sense=True)["overall"]["true_positives"], 0)


if __name__ == "__main__":
    unittest.main()
