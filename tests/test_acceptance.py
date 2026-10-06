"""End-to-end offline researcher workflows across all starters and modes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class AcceptanceTests(unittest.TestCase):
    def test_complete_researcher_workflows(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "offline_demo.py"
        spec = importlib.util.spec_from_file_location("offline_demo", example)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            report = module.demonstrate(Path(tmp) / "acceptance", formats=["csv", "jsonl", "annotation"])
            self.assertEqual(len(report["projects"]), 6)
            self.assertEqual(report["paid_requests"], 0)
            self.assertEqual(len(report["checks"]), 11)
            self.assertTrue(all(row["terms"] and row["failures"] for row in report["projects"]))
            self.assertTrue(any(row["synthetic_evaluation"]["false_negatives"] > 0 for row in report["projects"]),
                            "Complete-source evaluation must surface omissions outside generated candidates.")
            saved = json.loads((Path(tmp) / "acceptance" / "acceptance_report.json").read_text())
            self.assertEqual(saved["checks"], report["checks"])


if __name__ == "__main__":
    unittest.main()
