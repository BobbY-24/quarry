import hashlib
import csv
import json
import tempfile
import unittest
from unittest.mock import patch
import os
from pathlib import Path

from termfinder.exports import annotation_sources, canonical_json, export_dataset


def dataset():
    text = "Here is 猫語, an expression."
    return {"schema_version": "1", "version_id": "v-fixture", "name": "heldout", "created_at": "2026-10-05T00:00:00Z", "recipe": {"version": 1}, "profile": {"name": "fake"}, "prompts": {"broad": "fixture"}, "terms": [{"term_id": "t1", "expression": "猫語", "language": "ja", "sense": "cat-language", "review_status": "approved", "attributes": {"register": "playful"}, "coinage_date": None, "coinage_date_reason": "unavailable"}, {"term_id": "t2", "expression": "expression", "language": "en", "sense": "word", "review_status": "rejected"}], "occurrences": [{"occurrence_id": "o1", "term_id": "t1", "source_id": "s1", "start": 8, "end": 10, "context": text}], "sources": [{"source_id": "s1", "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "locator": "local:fixture", "blocks": [{"kind": "paragraph", "start": 0, "end": len(text)}], "constraints": ["fixture only"]}], "runs": [], "jobs": [], "audit": [], "annotations": [], "relations": [], "discovery": [], "costs": [{"stage": "extraction", "amount_usd": 0.0}], "coverage": {"complete": True}, "failures": [], "constraints": ["fixture only"]}


class ExportTests(unittest.TestCase):
    def test_interrupted_publish_leaves_no_manifest_and_same_snapshot_can_resume(self):
        saved=dataset()
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/"interrupted"
            real_link=os.link
            count=0
            def interrupted(source,target):
                nonlocal count
                count+=1
                if count==3: raise OSError("synthetic disk interruption")
                return real_link(source,target)
            with patch("termfinder.exports.os.link",side_effect=interrupted):
                with self.assertRaises(OSError): export_dataset(saved,out,["jsonl"])
            self.assertFalse((out/"manifest.json").exists())
            self.assertFalse(any(p.name.startswith(".termfinder-export-") for p in out.iterdir()))
            manifest=export_dataset(saved,out,["jsonl"])["manifest"]
            self.assertTrue((out/"manifest.json").is_file())
            for name,metadata in manifest["files"].items():
                self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),metadata["sha256"])

    def test_reproducible_frozen_exports_and_hashes(self):
        saved = dataset()
        before = canonical_json(saved)
        with tempfile.TemporaryDirectory() as root:
            first, second = Path(root) / "first", Path(root) / "second"
            manifest = export_dataset(saved, first, ["csv", "jsonl", "annotation"])["manifest"]
            export_dataset(saved, second, ["annotation", "jsonl", "csv"])
            for path in first.iterdir():
                self.assertEqual(path.read_bytes(), (second / path.name).read_bytes(), path.name)
            for name, meta in manifest["files"].items():
                self.assertEqual(hashlib.sha256((first / name).read_bytes()).hexdigest(), meta["sha256"])
            rows = [json.loads(row) for row in (first / "terms.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 2)  # Rejected records never disappear.
            self.assertEqual(len((first / "approved_terms.jsonl").read_text().splitlines()), 1)
            self.assertEqual(before, canonical_json(saved))
            # Same snapshot into same folder is harmless, a changed one is refused.
            export_dataset(saved, first, ["csv", "jsonl", "annotation"])
            changed = dataset()
            changed["terms"][0]["expression"] = "different"
            with self.assertRaises(FileExistsError):
                export_dataset(changed, first, ["csv", "jsonl", "annotation"])

    def test_full_source_gold_template_not_candidate_review(self):
        packet = annotation_sources(dataset())[0]
        self.assertEqual(packet["terms"], [])
        self.assertFalse(packet["complete"])
        self.assertEqual(packet["source_id"], "s1")
        self.assertEqual(packet["text"], dataset()["sources"][0]["text"])
        self.assertIn("ALL", packet["instructions"])

    def test_parquet_retains_types_nested_attributes_and_empty_tables(self):
        try:
            import pyarrow.parquet as parquet
        except ImportError:
            self.skipTest("Pinned pyarrow not installed in minimal environment")
        with tempfile.TemporaryDirectory() as root:
            export_dataset(dataset(), Path(root), ["parquet"])
            rows = parquet.read_table(Path(root) / "terms.parquet").to_pylist()
            schemas = json.loads((Path(root) / "schema.json").read_text())
            encodings = schemas["tables"]["terms"]["parquet_columns"]
            decoded = [{key: json.loads(value) if value is not None and encodings[key]["encoding"] == "canonical_json" else value for key, value in row.items()} for row in rows]
            approved = next(row for row in decoded if row["term_id"] == "t1")
            self.assertEqual(approved["attributes"], {"register": "playful"})
            self.assertIsNone(approved["coinage_date"])
            self.assertEqual(parquet.read_table(Path(root) / "jobs.parquet").num_rows, 0)
            occurrence = parquet.read_table(Path(root) / "occurrences.parquet").to_pylist()[0]
            self.assertEqual(occurrence["start"], 8)
            self.assertIs(type(occurrence["start"]), int)
            self.assertEqual(schemas["tables"]["terms"]["parquet_columns"]["attributes"]["encoding"], "canonical_json")

    def test_parquet_heterogeneous_and_large_integer_values_lossless(self):
        try:
            import pyarrow.parquet as parquet
        except ImportError:
            self.skipTest("Pinned pyarrow not installed in minimal environment")
        saved = dataset()
        saved["terms"][0]["heterogeneous"] = "label"
        saved["terms"][1]["heterogeneous"] = 4
        saved["terms"][0]["large_integer"] = 2**100
        with tempfile.TemporaryDirectory() as root:
            export_dataset(saved, Path(root), ["parquet"])
            schema = json.loads((Path(root) / "schema.json").read_text())["tables"]["terms"]["parquet_columns"]
            rows = parquet.read_table(Path(root) / "terms.parquet").to_pylist()
            self.assertEqual(schema["heterogeneous"]["encoding"], "canonical_json")
            row = next(row for row in rows if row["term_id"] == "t1")
            self.assertEqual(json.loads(row["large_integer"]), 2**100)
            self.assertEqual(json.loads(row["heterogeneous"]), "label")

    def test_snapshot_and_format_validation(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                export_dataset({}, Path(root), ["jsonl"])
            with self.assertRaises(ValueError):
                export_dataset(dataset(), Path(root), ["unknown"])

    def test_symlink_target_never_read_or_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "unrelated.txt"
            target.write_text("unrelated private data", encoding="utf-8")
            out = Path(root) / "out"
            out.mkdir()
            (out / "terms.jsonl").symlink_to(target)
            with self.assertRaises(ValueError):
                export_dataset(dataset(), out, ["jsonl"])
            self.assertEqual(target.read_text(), "unrelated private data")

    def test_csv_formula_cells_are_safe_exact_jsonl_retained(self):
        saved = dataset()
        saved["terms"][0]["expression"] = "  =HYPERLINK(\"https://untrusted.example\")"
        saved["terms"][0]["sense"] = "\t@danger"
        with tempfile.TemporaryDirectory() as root:
            export_dataset(saved, Path(root), ["csv", "jsonl"])
            with (Path(root) / "terms.csv").open(newline="", encoding="utf-8") as handle:
                row = next(row for row in csv.DictReader(handle) if row["term_id"] == "t1")
            self.assertTrue(row["expression"].startswith("'"))
            self.assertTrue(row["sense"].startswith("'"))
            self.assertEqual(set(json.loads(row["__csv_escaped_columns"])), {"expression", "sense"})
            for column in json.loads(row["__csv_escaped_columns"]):
                row[column] = row[column][1:]
            self.assertEqual(row["expression"], saved["terms"][0]["expression"])
            original = next(json.loads(line) for line in (Path(root) / "terms.jsonl").read_text().splitlines() if json.loads(line)["term_id"] == "t1")
            self.assertEqual(original["expression"], saved["terms"][0]["expression"])


if __name__ == "__main__":
    unittest.main()
