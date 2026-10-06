import copy
import json
from pathlib import Path
import tempfile
import unittest

from termfinder.semantic_review import ReviewWorkspace, quarry_review_details
from termfinder.experiments import quarry_run
from test_experiments import fixture
from test_studies import study_fixture


def axes(eligibility="accept", meaning="accept"):
    return {"eligibility": {"decision": eligibility, "label": None, "reason": "Declared policy assessed against full source."},
            "contextual_meaning": {"decision": meaning, "label": "Human contextual meaning" if meaning == "accept" else None,
                                   "reason": "Whole-source context assessed by human."},
            "definition_support": {"decision": "unscorable", "label": None, "reason": "No definition supplied."},
            "translation": {"decision": "unscorable", "label": None, "reason": "Translation not applicable."}}


class SemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.corpus, self.gold, self.runs = fixture()
        self.rubric = study_fixture(self.corpus, self.runs)["policy"]["annotation_rubric"]

    def tearDown(self):
        self.temp.cleanup()

    def review(self, name="review", mode="assisted_complete_source"):
        review = ReviewWorkspace(self.root / name)
        review.create_packet(self.corpus, self.runs, mode=mode, rubric=self.rubric)
        return review

    def independent(self, name="independent"):
        review = ReviewWorkspace(self.root / name)
        review.create_packet(self.corpus, mode="independent_gold", rubric=self.rubric, workspace_root=self.root / "planning")
        return review

    def test_blinded_packet_full_sources_union_and_invalid_evidence_retained(self):
        self.runs[0]["system"] = "SYSTEM_SECRET_LABEL"
        self.runs[0]["run_id"] = "ORIGIN_PRIVATE_RUN"
        self.runs[0]["predictions"].append({**self.runs[0]["predictions"][0], "prediction_id": "invalid", "observed_text": "invented"})
        review = self.review()
        packet = review.packet()
        self.assertEqual(packet["sources"][0]["text"], self.corpus["sources"][0]["text"])
        self.assertEqual(len(packet["candidates"]), 4)
        self.assertEqual(sum(c["grounding"] == "invalid_original_proposal" for c in packet["candidates"]), 1)
        self.assertNotIn("SYSTEM_SECRET_LABEL", json.dumps(packet))
        self.assertNotIn("ORIGIN_PRIVATE_RUN", json.dumps(packet))
        merged = next(c for c in packet["candidates"] if c["evidence"]["source_id"] == "s1" and c["evidence"]["start"] == 2 and c["grounding"] == "exact")
        self.assertEqual(len(merged["model_suggestions"]), 2)
        self.assertEqual({s["origin"] for s in merged["model_suggestions"]}, {"model"})
        self.assertEqual(review.history(), [])
        with self.assertRaisesRegex(ValueError, "independent"):
            review.export_gold("v1", actor="a", provenance="Candidate review cannot measure omissions.")

    def test_human_versions_disputes_reversal_and_original_suggestions(self):
        review = self.review()
        item = next(iter(review.items()))
        before = (review.root / "packet.json").read_bytes()
        first = review.judge(item, axes(eligibility="uncertain"), actor="reviewer-a")
        with self.assertRaisesRegex(ValueError, "supersede"):
            review.judge(item, axes(), actor="reviewer-a")
        second = review.judge(item, axes(eligibility="disputed"), actor="reviewer-a", supersedes=first["event_id"])
        other = review.judge(item, axes(), actor="reviewer-b")
        resolution = review.adjudicate(item, axes(), actor="adjudicator", judgment_ids=[second["event_id"], other["event_id"]], reason="Full source resolved the dispute.")
        with self.assertRaisesRegex(ValueError, "latest"):
            review.adjudicate(item, axes(), actor="adjudicator", judgment_ids=[first["event_id"], other["event_id"]], reason="Wrong stale label.")
        review.reverse(resolution["event_id"], actor="adjudicator", reason="Reopen for source-context correction.")
        self.assertEqual(before, (review.root / "packet.json").read_bytes())
        self.assertEqual(len(review.history()), 5)
        self.assertEqual(review.summary()["reversals"], 1)

    def test_add_correct_remove_reverse_and_stale_judgments(self):
        review = self.review()
        new = review.record_item("add", {"source_id": "s3", "observed_text": "ordinary", "language": "en", "start": 0, "end": 8},
                                 actor="human", reason="Complete-source inspection discovered omitted item.")
        iid = new["payload"]["item"]["item_id"]
        old = review.judge(iid, axes(), actor="a")
        correction = review.record_item("correct", {"source_id": "s3", "observed_text": "words", "language": "en", "start": 9, "end": 14},
                                       item_id=iid, actor="human", reason="Correct observed expression.")
        other = review.judge(iid, axes(), actor="b")
        with self.assertRaisesRegex(ValueError, "stale-evidence"):
            review.adjudicate(iid, axes(), actor="c", judgment_ids=[old["event_id"], other["event_id"]], reason="Old span would be stale.")
        remove = review.record_item("remove", item_id=iid, actor="human", reason="Remove view item.")
        self.assertNotIn(iid, review.items())
        review.reverse(remove["event_id"], actor="human", reason="Restore removed evidence.")
        self.assertEqual(review.items()[iid]["observed_text"], "words")
        review.reverse(correction["event_id"], actor="human", reason="Restore previous span.")
        self.assertEqual(review.items()[iid]["observed_text"], "ordinary")
        with self.assertRaisesRegex(ValueError, "exact"):
            review.record_item("add", {"source_id": "s3", "observed_text": "made up", "language": "en", "start": 0, "end": 8}, actor="human", reason="Wrong wording.")

    def test_active_time_pauses_corrections_and_exposure_constraints(self):
        review = self.review()
        start = review.start_session(actor="human", exposure_registry=self.root / "exposure", at=100)
        sid = start["payload"]["session_id"]
        self.assertIsNone(review.summary()["active_seconds"])
        review.pause_session(sid, actor="human", at=110, reason="Break.")
        review.resume_session(sid, actor="human", at=200, reason="Resume complete-source annotation.")
        with self.assertRaises(ValueError):
            review.finish_session(sid, actor="human", at=199, reason="Backward clock.")
        review.finish_session(sid, actor="human", at=225, reason="Done.")
        self.assertEqual(review.summary()["active_seconds"], 35)
        review.correct_time(sid, active_seconds=32, actor="coordinator", reason="Three seconds were an interruption.")
        summary = review.summary()
        self.assertEqual(summary["active_seconds"], 32)
        self.assertEqual(summary["sessions"][0]["active_seconds"], 35)
        repeated = self.review("second-condition")
        with self.assertRaisesRegex(ValueError, "already seen"):
            repeated.start_session(actor="human", exposure_registry=self.root / "exposure", at=300)
        with self.assertRaisesRegex(ValueError, "Previously exposed"):
            repeated.start_session(actor="different-human", exposure_registry=self.root / "exposure", prior_exposure=True)
        repeated.start_session(actor="new-human", exposure_registry=self.root / "exposure", at=300)

    def test_independent_complete_source_gold_immutable_versions_and_negative_sources(self):
        review = self.independent()
        self.assertEqual(review.packet()["candidates"], [])
        addition = review.record_item("add", {"source_id": "s1", "observed_text": "猫語", "language": "ja", "start": 2, "end": 4},
                                     actor="qualified-a", reason="Independent source annotation.")
        iid = addition["payload"]["item"]["item_id"]
        a = review.judge(iid, axes(), actor="qualified-a")
        b = review.judge(iid, axes(meaning="uncertain"), actor="qualified-b")
        resolution = review.adjudicate(iid, axes(), judgment_ids=[a["event_id"], b["event_id"]], actor="qualified-c", reason="Source context supports the meaning.")
        with self.assertRaisesRegex(ValueError, "Every source"):
            review.export_gold("v1", actor="coordinator", provenance="Synthetic qualified-human fixture.")
        for sid in ("s1", "s2", "s3"):
            for actor in ("qualified-a", "qualified-b"):
                review.mark_complete(sid, actor=actor, qualified=True, independent=True, note="Inspected entire frozen source independently.")
        exported = review.export_gold("v1", actor="coordinator", provenance="Synthetic qualified-human fixture.")
        original = Path(exported["gold_path"]).read_bytes()
        gold = json.loads(original)
        self.assertEqual(len(gold), 3)
        self.assertEqual(gold[1]["terms"], [])
        self.assertTrue(all(p["complete"] for p in gold))
        with self.assertRaisesRegex(ValueError, "immutable"):
            review.export_gold("v1", actor="coordinator", provenance="Cannot replace earlier version.")
        review.reverse(resolution["event_id"], actor="qualified-c", reason="New ambiguity requires reconsideration.")
        with self.assertRaisesRegex(ValueError, "adjudication"):
            review.export_gold("v2", actor="coordinator", provenance="Reopened case.")
        self.assertEqual(Path(exported["gold_path"]).read_bytes(), original)

    def test_independent_gold_is_external_and_never_candidate_seeded(self):
        review = ReviewWorkspace(self.root / "planning" / "gold")
        with self.assertRaisesRegex(ValueError, "outside"):
            review.create_packet(self.corpus, mode="independent_gold", rubric=self.rubric, workspace_root=self.root / "planning")
        with self.assertRaisesRegex(ValueError, "candidate list"):
            ReviewWorkspace(self.root / "external").create_packet(self.corpus, self.runs, mode="independent_gold", rubric=self.rubric, workspace_root=self.root / "planning")
        independent = self.independent()
        with self.assertRaisesRegex(ValueError, "qualified"):
            independent.mark_complete("s1", actor="a", qualified=False, independent=True, note="Unqualified.")

    def test_untimed_work_cannot_create_artificial_savings(self):
        review = self.review()
        item = next(iter(review.items()))
        review.judge(item, axes(), actor="prior-reader")
        with self.assertRaisesRegex(ValueError, "already worked"):
            review.start_session(actor="prior-reader", exposure_registry=self.root / "exposure", at=100)
        started = review.start_session(actor="timed-human", exposure_registry=self.root / "exposure", at=100)
        sid = started["payload"]["session_id"]
        measured = review.judge(item, axes(), actor="timed-human")
        self.assertEqual(measured["timing"]["session_id"], sid)
        review.pause_session(sid, actor="timed-human", at=110, reason="Break.")
        untimed = review.judge(item, axes(eligibility="uncertain"), actor="timed-human", supersedes=measured["event_id"])
        self.assertIsNone(untimed["timing"]["session_id"])
        review.finish_session(sid, actor="timed-human", at=120, reason="Finish while paused.")
        summary = review.summary()
        self.assertIsNone(summary["active_seconds"])
        self.assertEqual(summary["active_seconds_reason"], "unmeasured_review_actions")
        self.assertEqual(summary["known_active_subtotal_seconds"], 10)
        self.assertEqual(len(summary["unmeasured_review_action_ids"]), 2)

    def test_modified_packet_or_history_is_detected(self):
        review = self.review()
        item = next(iter(review.items()))
        review.judge(item, axes(), actor="a")
        path = review.root / "events" / "000001.json"
        original = path.read_bytes()
        changed = json.loads(original); changed["payload"]["axes"]["eligibility"]["decision"] = "reject"
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "history hash"):
            review.history()
        path.write_bytes(original)
        packet_path = review.root / "packet.json"
        changed = json.loads(packet_path.read_text()); changed["sources"][0]["text"] = "tampered"
        packet_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "packet was modified"):
            review.packet()

    def test_inventory_changes_invalidate_complete_source_signoffs(self):
        review = self.independent()
        for sid in ("s1", "s2", "s3"):
            for actor in ("a", "b"):
                review.mark_complete(sid, actor=actor, qualified=True, independent=True, note="Inspected complete negative fixture.")
        first = review.export_gold("negative-v1", actor="c", provenance="Synthetic negative fixture.")
        original = Path(first["gold_path"]).read_bytes()
        review.record_item("add", {"source_id": "s1", "observed_text": "猫語", "language": "ja", "start": 2, "end": 4}, actor="a", reason="Found a missed observation.")
        with self.assertRaisesRegex(ValueError, "current independent"):
            review.export_gold("corrected-v2", actor="c", provenance="Requires reinspection and signoff.")
        self.assertEqual(Path(first["gold_path"]).read_bytes(), original)

    def test_original_context_definition_translation_and_page_details_preserved(self):
        snapshot = {"sources": self.corpus["sources"], "recipe": {"data_type": "term"},
                    "terms": [{"term_id": "original-term", "expression": "猫語", "language": "ja", "sense": "Proposed label"}],
                    "occurrences": [{"term_id": "original-term", "occurrence_id": "original-occurrence", "source_id": "s1", "expression": "猫語",
                                     "language": "ja", "start": 2, "end": 4, "context": "😀 猫語 then 猫語", "context_start": 0, "context_end": 12,
                                     "definition_quote": "猫語 then 猫語", "definition_quote_reason": None,
                                     "translation": {"text": "cat language", "origin": "model_generated", "reason": None},
                                     "source_locations": [{"kind": "paragraph", "start": 0, "end": 12, "page": 3, "heading": None,
                                                           "location": {"page": 3, "line": 4}}],
                                     "provenance": [{"model": "DO_NOT_EXPOSE_MODEL"}]}]}
        normalized = quarry_run(snapshot, run_id="quarry-saved", software_revision="fixture")
        details = quarry_review_details(snapshot, "quarry-saved")
        review = ReviewWorkspace(self.root / "detailed-review")
        packet = review.create_packet(self.corpus, [normalized], mode="assisted_complete_source", rubric=self.rubric, evidence_details=details)
        original = packet["candidates"][0]["model_suggestions"][0]["original_evidence"]
        self.assertEqual(original["context"], snapshot["occurrences"][0]["context"])
        self.assertEqual(original["definition_quote"], snapshot["occurrences"][0]["definition_quote"])
        self.assertEqual(original["translation"]["text"], "cat language")
        self.assertEqual(original["source_locations"][0]["page"], 3)
        self.assertFalse(original["human_verified"])
        self.assertEqual(original["origin_labels"]["translation"], "model_suggestion_not_human_verified")
        self.assertNotIn("DO_NOT_EXPOSE_MODEL", json.dumps(packet))
        self.assertNotIn("quarry-saved", json.dumps(packet))
        self.assertEqual(review.history(), [])

    def test_semantic_summary_keeps_current_disagreements_and_stale_resolution_explicit(self):
        review = self.review()
        iid = next(iter(review.items()))
        first = review.judge(iid, axes(), actor="a")
        second = review.judge(iid, axes(eligibility="uncertain"), actor="b")
        summary = review.semantic_summary()
        self.assertEqual(summary["judged_items"], 1)
        self.assertEqual(summary["unjudged_items"], 2)
        self.assertEqual(summary["current_human_judgment_counts_by_axis"]["eligibility"]["accept"], 1)
        self.assertEqual(summary["current_human_judgment_counts_by_axis"]["eligibility"]["uncertain"], 1)
        row = next(r for r in summary["items"] if r["item_id"] == iid)
        self.assertEqual(row["decision_disagreement_axes"], ["eligibility"])
        self.assertIsNone(row["adjudicated_axes"])
        resolution = review.adjudicate(iid, axes(), judgment_ids=[first["event_id"], second["event_id"]], actor="c", reason="Resolve full-source policy application.")
        self.assertEqual(review.semantic_summary()["adjudicated_item_counts_by_axis"]["eligibility"]["accept"], 1)
        review.judge(iid, axes(eligibility="disputed"), actor="b", supersedes=second["event_id"])
        self.assertEqual(review.semantic_summary()["adjudicated_items"], 0)
        self.assertIsNone(review.semantic_summary()["quality_rate"])


if __name__ == "__main__":
    unittest.main()
