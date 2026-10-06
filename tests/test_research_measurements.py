import csv
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path
from termfinder.research_measurements import ResearcherLog, prepare_gt_bundle, import_gt_accounting

class MeasurementTests(unittest.TestCase):
    @staticmethod
    def metadata(**overrides):
        return dict(participant_id='p1', condition='own-agent', family_ids=['f1'],
                    harness='Codex', harness_model='fixture', experience='novice',
                    difficulty='calibrated-task-A', assistance='fixed prompt', order=1,
                    prior_exposure=False, consent_reference='synthetic-no-participant') | overrides

    def test_exposure_and_reversible_corrections(self):
        with tempfile.TemporaryDirectory() as d:
            log = ResearcherLog(d)
            meta = dict(participant_id='p1', condition='own-agent', family_ids=['f1'], harness='Codex', harness_model='fixture', experience='novice', difficulty='calibrated-task-A', assistance='fixed prompt', order=1, prior_exposure=False, consent_reference='synthetic-no-participant')
            log.begin('a', meta)
            e = log.record('a', 'active_time', dict(seconds=5, basis='synthetic', reason='offline fixture'))
            log.record('a', 'correction', dict(supersedes=e['event_id'], reason='exclude mistaken timer segment'))
            log.record('a', 'active_time', dict(seconds=3, basis='synthetic', reason='corrected fixture'))
            self.assertEqual(log.summary()['tasks'][0]['active_seconds'], 3)
            self.assertEqual(log.summary()['tasks'][0]['active_seconds_basis'], 'synthetic')
            self.assertEqual(log.summary()['tasks'][0]['invalidated_event_count'], 1)
            with self.assertRaises(ValueError): log.begin('b', {**meta, 'condition':'direct', 'order':2})
            self.assertEqual(len(log.events()), 4)
            log.path.write_text(log.path.read_text().replace('exclude mistaken', 'altered'))
            with self.assertRaises(ValueError): log.events()

    def test_explicit_correction_replaces_time_without_mutating_original_event(self):
        with tempfile.TemporaryDirectory() as directory:
            log = ResearcherLog(directory)
            log.begin('task', self.metadata())
            event = log.record('task', 'active_time', {'seconds': 8, 'basis': 'measured', 'reason': 'timer segment'})
            correction = log.record('task', 'correction', {
                'supersedes': event['event_id'], 'reason': 'Excluded a five-second interruption',
                'replacement': {'kind': 'active_time', 'data': {'seconds': 3, 'basis': 'measured', 'reason': 'corrected timer segment'}}})
            summary = log.summary()['tasks'][0]
            self.assertEqual(summary['active_seconds'], 3)
            self.assertEqual(summary['active_seconds_basis'], 'measured')
            self.assertEqual(summary['correction_count'], 1)
            self.assertEqual(summary['invalidated_event_count'], 0)
            self.assertEqual(summary['corrections'][0]['event_id'], correction['event_id'])
            self.assertEqual(log.events()[1], event)

    def test_measured_and_synthetic_time_are_never_pooled_into_unlabeled_total(self):
        with tempfile.TemporaryDirectory() as directory:
            log = ResearcherLog(directory)
            log.begin('task', self.metadata())
            log.record('task', 'active_time', {'seconds': 2, 'basis': 'synthetic', 'reason': 'mechanics fixture'})
            log.record('task', 'active_time', {'seconds': 3, 'basis': 'measured', 'reason': 'observed timer segment'})
            summary = log.summary()['tasks'][0]
            self.assertIsNone(summary['active_seconds'])
            self.assertIsNone(summary['active_seconds_basis'])
            self.assertEqual(summary['active_seconds_by_basis'], {'measured': 3, 'synthetic': 2})
            self.assertEqual(summary['active_seconds_reason'], 'mixed_measurement_bases_reported_separately')

    def test_correction_references_and_all_event_schemas_are_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            log = ResearcherLog(directory)
            start = log.begin('task', self.metadata())
            event = log.record('task', 'active_time', {'seconds': 2, 'basis': 'measured', 'reason': 'timer'})
            for kind, data in (
                ('active_time', {'seconds': 2, 'basis': 'measured', 'reason': None}),
                ('active_time', {'seconds': 2, 'basis': [], 'reason': 'timer'}),
                ('active_time', {'seconds': 10**1000, 'basis': 'measured', 'reason': 'unbounded'}),
                ('intervention', {'reason': 'assistance', 'unexpected_field': 'value'}),
                ('setup_completion', {'complete': True, 'criterion': 'fixed criterion', 'reason': ''}),
                ('correction', {'supersedes': start['event_id'], 'reason': 'change exposure'}),
                ('correction', {'supersedes': event['event_id'], 'reason': 'new time', 'seconds': 3}),
                ('correction', {'supersedes': event['event_id'], 'reason': 'wrong kind',
                                'replacement': {'kind': 'intervention', 'data': {'reason': 'replacement'}}}),
            ):
                with self.subTest(kind=kind, data=data), self.assertRaises(ValueError):
                    log.record('task', kind, data)
            correction = log.record('task', 'correction', {'supersedes': event['event_id'], 'reason': 'invalidate mistaken timer'})
            with self.assertRaises(ValueError):
                log.record('task', 'correction', {'supersedes': event['event_id'], 'reason': 'duplicate invalidation'})
            with self.assertRaises(ValueError):
                log.record('task', 'correction', {'supersedes': correction['event_id'], 'reason': 'change history'})
            log.begin('other', self.metadata(participant_id='p2', family_ids=['f2']))
            with self.assertRaises(ValueError):
                log.record('other', 'correction', {'supersedes': event['event_id'], 'reason': 'cross-task correction'})

    def test_concurrent_exposure_checks_and_appends_keep_valid_history(self):
        with tempfile.TemporaryDirectory() as directory:
            def begin(task):
                try:
                    return ResearcherLog(directory).begin(task, self.metadata())
                except ValueError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                attempts = list(pool.map(begin, ('first', 'second')))
            successful = [event for event in attempts if event is not None]
            self.assertEqual(len(successful), 1)
            task = successful[0]['task_id']
            def record(_):
                return ResearcherLog(directory).record(task, 'active_time',
                    {'seconds': 1, 'basis': 'measured', 'reason': 'independent segment'})
            with ThreadPoolExecutor(max_workers=4) as pool:
                records = list(pool.map(record, range(16)))
            log = ResearcherLog(directory)
            self.assertEqual(len(log.events()), 17)
            self.assertEqual(len({record['event_id'] for record in records}), 16)
            self.assertEqual(log.summary()['tasks'][0]['active_seconds'], 16)

    def test_accounting_unknowns_not_free_and_no_site_guess(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'bundle'
            fields = ['checkpoint','checkpoint_sha256','runtime','runtime_version','quantization','hardware','concurrency']
            runtime = {k:None for k in fields} | {'unavailable_reasons':{k:'operator has not supplied' for k in fields}}
            bundle = prepare_gt_bundle(root, study_digest='a'*64, runtime=runtime)
            self.assertFalse(bundle['authorized_to_execute'])
            report = import_gt_accounting(root/'accounting.csv')
            self.assertIsNone(report['total_cost_usd'])
            self.assertIsNone(report['output_tokens_per_second'])
            self.assertIsNone(report['measurements']['allocation_cost_usd']['value'])
            raw = (root/'accounting.csv').read_text().replace('allocation_hours,,hours,unavailable,not_run','allocation_hours,2,hours,estimate,bogus')
            (root/'accounting.csv').write_text(raw)
            with self.assertRaises(ValueError): import_gt_accounting(root/'accounting.csv')

    def test_accounting_rejects_fractional_tokens_extra_cells_and_nonfinite_derived_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'bundle'
            fields = ['checkpoint','checkpoint_sha256','runtime','runtime_version','quantization','hardware','concurrency']
            runtime = {key: None for key in fields} | {'unavailable_reasons': {key: 'not_run' for key in fields}}
            prepare_gt_bundle(root, study_digest='a'*64, runtime=runtime)
            path = root / 'accounting.csv'
            original = path.read_text()
            path.write_text(original.replace('output_tokens,,tokens,unavailable,not_run', 'output_tokens,1.5,tokens,measured,count'))
            with self.assertRaises(ValueError): import_gt_accounting(path)
            path.write_text(original.replace('output_tokens,,tokens,unavailable,not_run', 'output_tokens,,tokens,unavailable,not_run,extra'))
            with self.assertRaises(ValueError): import_gt_accounting(path)
            path.write_text(original.replace('output_tokens,,tokens,unavailable,not_run', 'output_tokens,1000000000000,tokens,measured,count')
                                   .replace('inference_seconds,,seconds,unavailable,not_run', 'inference_seconds,1e-308,seconds,measured,timer'))
            report = import_gt_accounting(path)
            self.assertIsNone(report['output_tokens_per_second'])
            self.assertEqual(report['throughput_reason'], 'derived_throughput_not_finite')
            self.assertEqual(report['throughput_measurement_bases'], {'output_tokens': 'measured', 'inference_seconds': 'measured'})
