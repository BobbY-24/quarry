"""Pending reviews remain inspectable, while admission still requires readiness."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from termfinder import Project
from termfinder.workflow import approve_review, check_review, current_review, prepare_review, run_review


class PendingReviewTests(unittest.TestCase):
    def test_pending_review_can_be_read_without_becoming_approvable(self):
        with tempfile.TemporaryDirectory(prefix="v6-readiness-") as tmp:
            root = Path(tmp).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            source = corpus / "fictional.md"
            source.write_text("The fictional community calls its dance moonstep.", encoding="utf-8")
            project = Project(root / "study")
            setup = project.prepare_agent_setup({"research_question": "Which new expressions appear?",
                "local_roots": [str(corpus)], "domains": ["example.org"],
                "model_profile": "fake", "budget_usd": 0, "max_sources": 2})
            bundle = deepcopy(setup["starter_bundle"])
            bundle["unresolved_questions"] = []
            metadata = {"language": "en", "community": "research-corpus", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "fictional_undated_fixture",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                    "permitted_use": "offline_verification", "redistribution": "synthetic_only"}}
            bundle["sources"] = [{"source_key": key, "kind": kind, "locator": locator,
                "metadata": deepcopy(metadata), "why_selected": "Declared synthetic test input",
                "origin": "researcher_supplied", "search_refs": [], "family_id": key}
                for key, kind, locator in (("local", "local", str(source)),
                                           ("pending", "url", "https://example.org/fictional"))]
            validation = project.validate_agent_bundle(bundle)
            self.assertTrue(validation["valid"], validation)
            review = prepare_review(project, bundle, fetch_remote=False)
            self.assertFalse(review["ready"])
            self.assertIsNotNone(review["review_id"])
            self.assertEqual(len(review["pending_sources"]), 1)
            read = current_review(project)
            self.assertFalse(read["stale"])
            self.assertFalse(read["approved"])
            self.assertFalse(read["approval_verified"])
            self.assertEqual(project.store.count("jobs"), 0)
            for operation in (approve_review, check_review, run_review):
                with self.assertRaisesRegex(ValueError, "pending sources"):
                    operation(project, review["review_id"])
            self.assertEqual(project.store.count("jobs"), 0)
            # Readability must not weaken fingerprint checks for changed policy.
            changed = project.recipe
            changed["research_question"] += " Changed"
            project.store.setting("recipe", changed)
            self.assertTrue(current_review(project)["stale"])


if __name__ == "__main__":
    unittest.main()
