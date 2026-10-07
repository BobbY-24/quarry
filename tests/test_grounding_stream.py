"""Streaming grounding does not expand the context/expression cross product."""
import itertools
import unittest
from unittest.mock import patch

from termfinder.config import starter_recipe
from termfinder import grounding
from termfinder.sources import parse_document


class GroundingStreamTests(unittest.TestCase):
    def fixture(self, text="aaaa", context="aa", start=None):
        source = parse_document(text.encode(), "text/plain", "synthetic.txt",
            {"language": "en", "community": "Gaming"})
        source.update(source_id="src_" + "0" * 24, retrieved_at="2026-10-06T00:00:00Z")
        job = {"start": 0, "end": len(text)}
        proposal = {"expression": "a", "language": "en", "sense": "a synthetic mark",
            "context": context, "start": start, "definition_quote": None,
            "translation": None, "attributes": {}}
        return proposal, source, job, starter_recipe("neologisms"), {}

    def test_stream_returns_before_consuming_match_iterators(self):
        original = grounding._matches
        consumed = []
        def bounded_matches(text, needle):
            for index in original(text, needle):
                consumed.append((needle, index))
                if len(consumed) > 6:
                    raise AssertionError("Grounding eagerly consumed the match cross product")
                yield index
        with patch.object(grounding, "_matches", side_effect=bounded_matches):
            rows, errors = grounding.ground(*self.fixture("a" * 1000), stream=True)
            self.assertEqual(consumed, [])
            first = next(rows)[1]
            self.assertEqual((first["context_start"], first["start"]), (0, 0))
            self.assertEqual(len(consumed), 2)
            following = [occurrence for _, occurrence in itertools.islice(rows, 2)]
        self.assertEqual([(r["context_start"], r["start"]) for r in following], [(0, 1), (1, 1)])
        self.assertFalse(errors)

    def test_order_and_explicit_offset_preference_are_preserved(self):
        rows, errors = grounding.ground(*self.fixture(), stream=True)
        self.assertEqual([(r["context_start"], r["start"]) for _, r in rows],
            [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 3)])
        selected, selected_errors = grounding.ground(*self.fixture(start=2), stream=True)
        self.assertEqual([(r["context_start"], r["start"]) for _, r in selected], [(1, 2), (2, 2)])
        self.assertFalse(errors)
        self.assertFalse(selected_errors)

    def test_invalid_offset_repairs_without_dropping_grounded_occurrences(self):
        rows, errors = grounding.ground(*self.fixture(start=999), stream=True)
        self.assertEqual(len(list(rows)), 6)
        self.assertIn("offset_repaired_by_exact_context", errors)

    def test_unicode_offsets_and_eager_compatibility(self):
        fixture = self.fixture("😀 aa aa")
        eager, errors = grounding.ground(*fixture)
        streamed, stream_errors = grounding.ground(*fixture, stream=True)
        self.assertEqual([(r["start"], r["end"]) for _, r in eager], [(2, 3), (3, 4), (5, 6), (6, 7)])
        self.assertEqual([(t["term_id"], r["occurrence_id"]) for t, r in eager],
            [(t["term_id"], r["occurrence_id"]) for t, r in streamed])
        self.assertEqual(errors, stream_errors)

    def test_missing_context_still_returns_audit_reason(self):
        rows, errors = grounding.ground(*self.fixture(context="absent"), stream=True)
        self.assertEqual(list(rows), [])
        self.assertIn("context_not_exact_in_window", errors)


if __name__ == "__main__":
    unittest.main()
