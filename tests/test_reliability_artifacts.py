"""Frozen generations and response/derived-processing compatibility."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import Project,FakeProvider,Response
from termfinder.config import starter_recipe
from termfinder.sources import parse_document
from termfinder.exports import export_dataset,StagedFiles


class ReliabilityArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.project=Project(Path(self.tmp.name)/"project")
        self.project.configure(starter_recipe("neologisms"),"fake")
        self.text="Café crews call a pause a moonstep."
        self.project.add_source(parse_document(self.text.encode(),"text/plain","fixture.txt",{"community":"Gaming","language":"en"}))
        self.provider=FakeProvider([{"expression":"moonstep","language":"en","sense":"a pause","context":self.text,"attributes":{}}])

    def test_failed_export_does_not_publish_fresh_destination(self):
        self.project.collect(self.provider)
        version=self.project.snapshot("immutable")
        out=Path(self.tmp.name)/"export"
        original=StagedFiles.jsonl
        def disk_full(files,name,rows):
            original(files,name,rows)
            raise OSError(28,"synthetic disk full")
        with patch.object(StagedFiles,"jsonl",disk_full),self.assertRaises(OSError):
            self.project.export(version,out,["jsonl"])
        self.assertFalse(out.exists())
        self.project.export(version,out,["jsonl"])
        before={p.name:p.read_bytes() for p in out.iterdir()}
        self.project.export(version,out,["jsonl"])
        self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir()})

    def test_new_grounding_version_reuses_raw_response_and_preserves_frozen_dataset(self):
        self.project.collect(self.provider)
        version=self.project.snapshot("before-upgrade")
        frozen=self.project.dataset(version)
        calls=len(self.provider.calls)
        with patch("termfinder.engine.PROCESSING_VERSION","grounding-test-revision",create=True):
            self.project.resume(self.provider)
        self.assertEqual(len(self.provider.calls),calls)
        self.assertEqual(self.project.dataset(version),frozen)
        versions={p.get("processing_version") for o in self.project.inventory()["occurrences"] for p in o["provenance"]}
        self.assertIn("grounding-test-revision",versions)

    def test_doctor_reports_durable_safe_failure_after_controller_restart(self):
        with patch("termfinder.engine.ThreadPoolExecutor.submit",side_effect=RuntimeError("synthetic-private-secret-and-path")):
            self.project.collect(self.provider)
        doctor=Project(self.project.path).doctor()
        self.assertEqual(doctor["status"],"partial")
        self.assertTrue(doctor["incidents"])
        self.assertNotIn("synthetic-private-secret-and-path",json.dumps(doctor))
        self.assertNotIn(self.tmp.name,json.dumps(doctor))
        self.assertFalse(doctor["changed_state"])

    def test_quota_wait_does_not_consume_paid_attempt_or_lose_job(self):
        from termfinder.quotas import QuotaCoordinator,QuotaLimits
        quota=QuotaCoordinator(Path(self.tmp.name)/"quota.sqlite","synthetic-account",QuotaLimits(max_inflight=1))
        lease=quota.try_acquire("other-study","other-job","other-attempt",10).lease
        quota.mark_dispatched(lease)
        self.project.configure_quota(quota.path,"synthetic-account",QuotaLimits(max_inflight=1))
        result=self.project.collect(self.provider)
        self.assertFalse(self.provider.calls)
        self.assertEqual(self.project.store.count("costs"),0)
        self.assertEqual(result["jobs"].get("pending"),2)
        quota.release(lease,outcome="settled",actual_tokens=10)
        self.project.resume(self.provider)
        self.assertEqual(self.project.status()["status"],"complete")

if __name__=="__main__":unittest.main()
