"""Real synthetic database produced by the independent old 6.6 engine."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from termfinder import Project,FakeProvider

FIXTURE=Path(__file__).parent/"fixtures/legacy-6.6"


class ReleaseCompatibilityTests(unittest.TestCase):
    def test_unpatched_sqlite_stops_before_project_file_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/"project"
            with patch("termfinder.store.sqlite3.sqlite_version_info",(3,51,2)),self.assertRaises(ValueError):
                Project(target)
            self.assertFalse((target/"project.sqlite3").exists())

    def test_real_old_project_opens_reprocesses_without_inference_and_reexports_frozen_bytes(self):
        receipt=json.loads((FIXTURE/"receipt.json").read_text())
        self.assertEqual(hashlib.sha256((FIXTURE/"project.sqlite3").read_bytes()).hexdigest(),receipt["database_sha256"])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"project";root.mkdir()
            shutil.copyfile(FIXTURE/"project.sqlite3",root/"project.sqlite3")
            project=Project(root)
            self.assertEqual(project.store.count("terms"),3)
            provider=FakeProvider([{"expression":"moonstep","language":"en","sense":"a pause","context":"🧪 Café crews call a pause a moonstep. The anchor holds the checkpoint.","attributes":{}},
                {"expression":"anchor","language":"en","sense":"checkpoint holder","context":"🧪 Café crews call a pause a moonstep. The anchor holds the checkpoint.","attributes":{}},
                {"expression":"anchor","language":"en","sense":"last defender","context":"🧪 Café crews call a pause a moonstep. The anchor holds the checkpoint.","attributes":{}}])
            project.resume(provider)
            self.assertFalse(provider.calls)
            self.assertEqual(project.store.count("terms"),3)
            self.assertEqual(project.store.count("occurrences"),3)
            out=Path(temporary)/"export"
            project.export(receipt["version_id"],out,["jsonl"])
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
            self.assertEqual(hashes,receipt["jsonl_export_sha256"])

if __name__=="__main__":unittest.main()
