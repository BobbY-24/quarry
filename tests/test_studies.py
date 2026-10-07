import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder.experiments import _hash
from termfinder.studies import StudyRepository, validate_study
from test_experiments import fixture


def study_fixture(corpus, runs):
    """Complete inert V7 contract shared by integration examples."""
    return {"schema_version": "7.0", "study_id": "synthetic-v7",
            "research_question": "Does additional general extraction recover independently valid observations?",
            "hypothesis": "The right arm improves heldout occurrence recall at equal declared resources.",
            "contribution": "A falsifiable controlled comparison; this synthetic fixture establishes mechanics only.",
            "primary_contrast": {"left": "left", "right": "right", "direction": "right_minus_left",
                                 "rival_explanations": ["Additional inference resources, prompt tuning, or cache exposure explain an apparent gain."]},
            "primary_outcome": {"metric": "recall", "unit": "occurrence", "analysis": "Paired family uncertainty; report precision, cost and review effort separately.",
                                "quality_margin": None, "unavailable_reason": "not_a_noninferiority_claim"},
            "secondary_analyses": ["Report source-term detection and semantic judgments separately."],
            "policy": {"inclusion": "Exact contextual research vocabulary under the declared rubric.",
                       "exclusion": "Exclude ordinary vocabulary, retaining uncertain decisions for adjudication.",
                       "annotation_rubric": {"eligibility": "Qualifies under the inclusion policy.", "contextual_meaning": "Meaning supported by the complete source.",
                                             "definition_support": "Definition is supported by evidence, or unscorable with a reason.",
                                             "translation": "Translation preserves contextual meaning, or unscorable when not applicable."}},
            "corpus": {"corpus_id": corpus["corpus_id"], "corpus_sha256": _hash(corpus), "scope": "frozen_parsed_text",
                       "acquisition_provenance": "Synthetic texts; acquisition and parsing were not evaluated.",
                       "sources": [{"source_id": s["source_id"], "text_sha256": s["text_sha256"], "family_id": s["family_id"], "split": "heldout"} for s in corpus["sources"]]},
            "gold": {"version_id": "synthetic-gold-v1", "sha256": None,
                     "provenance": "Independently authored fixture labels, not a human annotation study.",
                     "unavailable_reasons": {"sha256": "Gold is held externally until predictions lock."}},
            "arms": [{"arm_id": r["run_id"], "system": r["system"], "track": "matched", "configuration": {"fixture": True},
                      "provenance": copy.deepcopy(r["provenance"])} for r in runs],
            "repetitions": 1, "seeds": ["fixture-seed"],
            "run_order": [{"run_id": r["run_id"], "arm_id": r["run_id"], "repetition": 0, "seed": "fixture-seed"} for r in runs],
            "cache": {"regime": "cold", "isolation": "Each arm has a fresh independent database and cache.", "extension_of": None,
                      "unavailable_reason": "not_a_warm_extension"},
            "limits": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 120, "spending_usd": 0, "allocation_hours": 0},
            "stopping_rules": ["Stop at the first resource limit; preserve explicit incomplete outcomes."],
            "planned_exclusions": [], "unavailable_reasons": {"power": "Feasibility fixture; no power calculation or empirical claim."}}


class StudyTests(unittest.TestCase):
    def test_complete_manifest_and_family_integrity(self):
        corpus, _, runs = fixture()
        spec = study_fixture(corpus, runs)
        self.assertEqual(validate_study(spec, corpus), spec)
        mutations = [lambda s: s["corpus"]["sources"].pop(),
                     lambda s: s["corpus"].update(corpus_sha256="a" * 64),
                     lambda s: s["corpus"]["sources"][0].update(text_sha256="b" * 64),
                     lambda s: s["corpus"]["sources"][0].update(family_id="invented"),
                     lambda s: s["run_order"][0].update(seed="changed")]
        for mutate in mutations:
            changed = copy.deepcopy(spec); mutate(changed)
            with self.assertRaises(ValueError):
                validate_study(changed, corpus)
        same_family = copy.deepcopy(spec)
        same_family["corpus"]["sources"][1].update(family_id=same_family["corpus"]["sources"][0]["family_id"], split="development")
        with self.assertRaisesRegex(ValueError, "families cannot cross"):
            validate_study(same_family)
        duplicate = copy.deepcopy(spec)
        duplicate["corpus"]["sources"][1].update(text_sha256=duplicate["corpus"]["sources"][0]["text_sha256"], split="development")
        with self.assertRaisesRegex(ValueError, "Identical source"):
            validate_study(duplicate)

    def test_finite_limits_and_null_reasons_and_full_run_plan(self):
        corpus, _, runs = fixture()
        spec = study_fixture(corpus, runs)
        for key in spec["limits"]:
            for bad in (None, float("inf"), -1, True):
                changed = copy.deepcopy(spec); changed["limits"][key] = bad
                with self.assertRaises(ValueError):
                    validate_study(changed)
        for mutate in (lambda s: s["gold"]["unavailable_reasons"].clear(),
                       lambda s: s["primary_outcome"].update(unavailable_reason=None),
                       lambda s: s["arms"][0]["provenance"].update(model_version=None),
                       lambda s: s["run_order"].pop(),
                       lambda s: s["run_order"][1].update(arm_id="left"),
                       lambda s: s["cache"].update(regime="warm_extension")):
            changed = copy.deepcopy(spec); mutate(changed)
            with self.assertRaises(ValueError):
                validate_study(changed)
        changed = copy.deepcopy(spec)
        changed["repetitions"] = 11
        changed["seeds"] = [f"seed-{i}" for i in range(11)]
        with self.assertRaisesRegex(ValueError, "at most 20"):
            validate_study(changed)

    def test_draft_freeze_amend_history_never_overwrites(self):
        corpus, _, runs = fixture()
        with tempfile.TemporaryDirectory() as d:
            repo = StudyRepository(Path(d) / "study")
            spec = study_fixture(corpus, runs)
            draft = repo.create(spec, actor="researcher")
            with self.assertRaisesRegex(ValueError, "Freeze"):
                repo.lock_predictions(corpus, runs, actor="researcher")
            frozen = repo.freeze(actor="researcher", corpus=corpus)
            originals = [p.read_bytes() for p in sorted((repo.root / "revisions").glob("*.json"))]
            amended = copy.deepcopy(spec); amended["hypothesis"] = "Amended hypothesis, explicitly exploratory."
            repo.amend(amended, actor="researcher", reason="Pilot feasibility revised the hypothesis before a new run.")
            self.assertEqual([r["state"] for r in repo.history()], ["draft", "frozen", "amended"])
            self.assertEqual(originals, [p.read_bytes() for p in sorted((repo.root / "revisions").glob("*.json"))[:2]])
            self.assertEqual(repo.history()[1]["previous_sha256"], draft["sha256"])
            self.assertNotEqual(frozen["sha256"], repo.current()["sha256"])
            repo.freeze(actor="researcher", corpus=corpus)
            with self.assertRaises(ValueError):
                repo.freeze(actor="researcher", corpus=corpus)
            path = repo.root / "revisions" / "000001.json"
            tampered = json.loads(path.read_text()); tampered["spec"]["hypothesis"] = "silently edited"
            path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "history hash"):
                repo.history()

    def test_lock_before_external_gold_and_frozen_prediction_identity(self):
        corpus, gold, runs = fixture()
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "planning"; workspace.mkdir()
            repo = StudyRepository(workspace / "study")
            repo.create(study_fixture(corpus, runs), actor="researcher"); repo.freeze(actor="researcher", corpus=corpus)
            external = Path(d) / "independent-gold.json"; external.write_text(json.dumps(gold))
            with self.assertRaises(FileNotFoundError):
                repo.score(corpus, runs, external, workspace_root=workspace)
            lock = repo.lock_predictions(corpus, runs, actor="researcher")
            self.assertEqual(lock["gold_access"], "not_read_by_locking_api")
            with patch("termfinder.providers.HTTPProvider.complete", side_effect=AssertionError("No providers")):
                first = repo.score(corpus, runs, external, workspace_root=workspace)
                self.assertEqual(first, repo.score(corpus, runs, external, workspace_root=workspace))
            self.assertEqual(first["runs"][0]["detection"]["overall"]["false_negatives"], 2)
            self.assertAlmostEqual(first["primary_contrast_results"][0]["delta"], 2 / 3)
            self.assertIsNone(first["study"]["gold_version"])
            self.assertEqual(first["study"]["gold_version_status"], "declared_unattested")
            changed = copy.deepcopy(runs); changed[0]["predictions"].clear()
            with self.assertRaisesRegex(ValueError, "changed after"):
                repo.score(corpus, changed, external, workspace_root=workspace)
            internal = workspace / "gold.json"; internal.write_text(json.dumps(gold))
            with self.assertRaisesRegex(ValueError, "outside"):
                repo.score(corpus, runs, internal, workspace_root=workspace)
            with self.assertRaises(FileExistsError):
                repo.lock_predictions(corpus, runs, actor="researcher")

    def test_heldout_denominators_and_original_failed_sources(self):
        corpus, gold, runs = fixture()
        spec = study_fixture(corpus, runs)
        spec["corpus"]["sources"][0]["split"] = "development"
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "plan"; workspace.mkdir()
            repo = StudyRepository(workspace / "study")
            repo.create(spec, actor="r"); repo.freeze(actor="r", corpus=corpus)
            repo.lock_predictions(corpus, runs, actor="r")
            path = Path(d) / "gold.json"; path.write_text(json.dumps(gold[1:]))
            report = repo.score(corpus, runs, path, workspace_root=workspace)
            self.assertEqual(report["runs"][0]["detection"]["overall"]["false_negatives"], 1)
            self.assertEqual(report["runs"][0]["coverage"]["source_count"], 2)
            path.write_text(json.dumps(gold))
            with self.assertRaisesRegex(ValueError, "every heldout"):
                repo.score(corpus, runs, path, workspace_root=workspace)

    def test_spec_is_inert_and_run_provenance_order_source_population_locked(self):
        corpus, _, runs = fixture()
        with tempfile.TemporaryDirectory() as d:
            repo = StudyRepository(Path(d) / "study")
            spec = study_fixture(corpus, runs)
            spec["arms"][0]["configuration"] = {"command": "touch SHOULD_NEVER_EXECUTE", "authorization": "pay"}
            repo.create(spec, actor="r"); repo.freeze(actor="r", corpus=corpus)
            for change in (lambda rs: rs.reverse(), lambda rs: rs[0]["provenance"].update(model_version="moving-model"),
                           lambda rs: rs[0]["source_results"].pop(), lambda rs: rs[0]["costs"].pop(),
                           lambda rs: rs[0]["predictions"].append("unstructured generated output")):
                altered = copy.deepcopy(runs); change(altered)
                with self.assertRaises(ValueError):
                    repo.lock_predictions(corpus, altered, actor="r")
            self.assertFalse((Path(d) / "SHOULD_NEVER_EXECUTE").exists())

    def test_invalid_grounding_is_locked_audited_and_not_repaired(self):
        corpus, gold, runs = fixture()
        runs[0]["predictions"].append({**runs[0]["predictions"][0], "prediction_id": "invalid-original", "observed_text": "generated wording"})
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "plan"; workspace.mkdir()
            repo = StudyRepository(workspace / "study")
            repo.create(study_fixture(corpus, runs), actor="r"); repo.freeze(actor="r", corpus=corpus)
            repo.lock_predictions(corpus, runs, actor="r")
            path = Path(d) / "gold.json"; path.write_text(json.dumps(gold))
            report = repo.score(corpus, runs, path, workspace_root=workspace)
            audit = report["runs"][0]["raw_proposals"]
            self.assertEqual(audit["invalid"], 1)
            self.assertEqual(audit["invalid_queue"][0]["proposal"]["observed_text"], "generated wording")

    def test_primary_contrast_direction_is_independent_of_randomized_run_order(self):
        corpus, gold, runs = fixture()
        spec = study_fixture(corpus, runs)
        spec["run_order"].reverse()
        spec["primary_contrast"]["direction"] = "left_minus_right"
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "plan"; workspace.mkdir()
            repo = StudyRepository(workspace / "study")
            repo.create(spec, actor="r"); repo.freeze(actor="r", corpus=corpus)
            repo.lock_predictions(corpus, list(reversed(runs)), actor="r")
            path = Path(d) / "gold.json"; path.write_text(json.dumps(gold))
            report = repo.score(corpus, list(reversed(runs)), path, workspace_root=workspace)
            primary = report["primary_contrast_results"][0]
            self.assertEqual(primary["left_run_id"], "left")
            self.assertAlmostEqual(primary["delta"], -2 / 3)
            self.assertEqual(primary["interval_reason"], "not_requested")

    def test_external_gold_manifest_binds_content_version_and_explicit_provenance(self):
        corpus, gold, runs = fixture()
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "plan"; workspace.mkdir()
            external = Path(d) / "external-gold"; external.mkdir()
            repo = StudyRepository(workspace / "study")
            repo.create(study_fixture(corpus, runs), actor="r"); repo.freeze(actor="r", corpus=corpus)
            repo.lock_predictions(corpus, runs, actor="r")
            gold_path = external / "gold.json"; gold_path.write_text(json.dumps(gold))
            manifest_path = external / "manifest.json"
            manifest = {"version_id": "synthetic-gold-v1", "gold_sha256": _hash(gold), "provenance": "Independently held synthetic fixture."}
            manifest_path.write_text(json.dumps(manifest))
            report = repo.score(corpus, runs, gold_path, workspace_root=workspace)
            self.assertEqual(report["study"]["gold_version"], "synthetic-gold-v1")
            self.assertEqual(report["study"]["gold_version_status"], "manifest_content_matched_custody_unattested")
            for change in ({"version_id": "wrong-version"}, {"gold_sha256": "a" * 64}, {"provenance": ""}):
                changed = {**manifest, **change}; manifest_path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "manifest version/hash/provenance"):
                    repo.score(corpus, runs, gold_path, workspace_root=workspace)


if __name__ == "__main__":
    unittest.main()
