"""Receipt completion flags belong to their attempt, not an earlier retry."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import FakeProvider, Project, Response
from termfinder.config import starter_recipe, load_profile
from termfinder.engine import Engine
from termfinder.sources import parse_document


class UnknownReceiptRetryTests(unittest.TestCase):
    def test_retry_unknown_receipt_replays_after_prior_partial_was_processed(self):
        with tempfile.TemporaryDirectory() as root:
            project = Project(Path(root) / "study")
            recipe = starter_recipe("neologisms")
            recipe["execution"].update(concurrency=1, split_depth=0)
            recipe["execution"]["resilience"]["min_request_interval_seconds"] = 0
            profile = deepcopy(load_profile("fake"))
            profile["broad"] = [e for e in profile["broad"] if e["model"] == "glm"]
            project.configure(recipe, profile)
            text = "We call a pause moonstep."
            project.add_source(parse_document(text.encode(), "text/plain", "synthetic.txt",
                {"language": "en", "community": "Gaming"}))
            first = Response(json.dumps({"candidates": [], "coverage_complete": False}),
                30, 20, "length", "fixture-v1")
            project.collect(FakeProvider([], [first]))
            job = project.store.all("jobs")[0]
            self.assertEqual(job["status"], "partial")
            self.assertTrue(job["response_processed"])
            project.retry_failed(job["job_id"])
            proposal = {"expression": "moonstep", "language": "en", "sense": "a pause",
                "context": text, "start": None, "definition_quote": None,
                "translation": None, "attributes": {}}
            second = Response(json.dumps({"candidates": [proposal], "coverage_complete": True}),
                None, None, "stop", "fixture-v1")
            engine = Engine(project, FakeProvider([], [second]))
            with patch.object(engine, "accept", side_effect=RuntimeError("Synthetic grounding interruption")):
                engine.run()
            saved = project.store.get("jobs", job["job_id"])
            cache = project.store.get("cache", job["job_id"])
            self.assertEqual(saved["status"], "uncertain")
            self.assertEqual(cache["usage_status"], "unknown")
            self.assertEqual(project.store.count("terms"), 0)
            replay_provider = FakeProvider([])
            project.resume(replay_provider)
            self.assertEqual(replay_provider.calls, [])
            self.assertEqual(project.store.count("terms"), 1)
            restored = project.store.get("jobs", job["job_id"])
            self.assertEqual(restored["status"], "uncertain")
            self.assertTrue(restored["response_processed"])
            self.assertEqual(restored["reason"], "provider_usage_unknown")
            self.assertEqual(project.store.count("costs"), 2)


if __name__ == "__main__":
    unittest.main()
