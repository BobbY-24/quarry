import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from termfinder.study_cli import main

class V7CLITests(unittest.TestCase):
    def test_inert_gt_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            keys=('checkpoint','checkpoint_sha256','runtime','runtime_version','quantization','hardware','concurrency')
            runtime={k:None for k in keys}|{'unavailable_reasons':{k:'not provided' for k in keys}}
            path=root/'runtime.json'; path.write_text(json.dumps(runtime))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['gt-prepare','--out',str(root/'bundle'),'--runtime',str(path),'--study-digest','a'*64]),0)
            report=root/'accounting.json'
            self.assertEqual(main(['gt-accounting',str(root/'bundle'/'accounting.csv'),'--out',str(report)]),0)
            self.assertIsNone(json.loads(report.read_text())['total_cost_usd'])

    def test_demo_and_cli_recompute(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'demo'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['demo','--out',str(root)]),0)
            recomputed=root/'recomputed.json'
            self.assertEqual(main(['compare',str(root/'comparison.json'),'--out',str(recomputed)]),0)
            self.assertEqual(json.loads(recomputed.read_text()),json.loads((root/'occurrence-report.json').read_text()))
            summary=json.loads((root/'report.json').read_text())
            self.assertEqual(summary['paid_requests'],0)
            self.assertTrue(summary['review_reversed_without_deleting_evidence'])
            reports=json.loads(recomputed.read_text())['runs']
            self.assertTrue(any(r['raw_proposals']['invalid'] for r in reports))
            delm=next(r for r in reports if r['run_id']=='delm-matched')
            self.assertGreater(delm['detection']['overall']['false_negatives'],0)
            self.assertFalse(delm['costs']['complete'])
