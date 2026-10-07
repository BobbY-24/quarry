"""Offline researcher and allocation measurements. Never launches compute."""
from __future__ import annotations

import csv
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import time

from .exports import canonical_json

VERSION = '7.0'
QUESTIONS = {
    'scope': 'Can source/model text expand the approved study scope?',
    'evidence': 'Does exact occurrence establish contextual semantic correctness?',
    'billing': 'Can an uncertain request prove there was no provider charge?',
}
GT_FIELDS = {
    'allocation_hours': 'hours', 'queue_seconds': 'seconds', 'startup_seconds': 'seconds',
    'inference_seconds': 'seconds', 'input_tokens': 'tokens', 'output_tokens': 'tokens',
    'peak_memory_gib': 'GiB', 'checkpoint_seconds': 'seconds', 'recovery_seconds': 'seconds',
    'allocation_cost_usd': 'USD', 'token_estimate_usd': 'USD', 'infrastructure_cost_usd': 'USD',
}
MEASURE_KINDS = frozenset({'active_time', 'setup_completion', 'intervention',
                           'agent_correction', 'comprehension', 'pause'})


def sha(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and 0 <= value <= 1e12 and math.isfinite(value)


def text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 20000


def measurement(value, unit, basis, reason=None):
    if value is None:
        if not text(reason):
            raise ValueError('Unavailable measurements require a reason')
    elif not number(value):
        raise ValueError('Measurements must be finite nonnegative numbers or null')
    if reason is not None and not text(reason):
        raise ValueError('Measurement reasons must be bounded nonempty text or null')
    if not isinstance(basis, str) or basis not in {'measured', 'operator_reported', 'invoice', 'estimate', 'synthetic', 'unavailable'}:
        raise ValueError('Unknown measurement basis')
    if basis == 'unavailable' and value is not None:
        raise ValueError('Unavailable is not zero')
    return {'value': value, 'unit': unit, 'basis': basis, 'reason': reason}


class ResearcherLog:
    """Append-only task events, independent of extractor predictions and gold.

    Participant IDs must be pseudonyms; consent records stay with the institution.
    Wall-clock values are never billed or inferred as active review time.
    """
    def __init__(self, root, *, clock=None):
        self.root = Path(root)
        self.clock = clock or time.monotonic
        self.path = self.root / 'measurements.jsonl'

    def events(self):
        if not self.path.exists():
            return []
        with self._locked(shared=True):
            return self._events()

    def _events(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 32_000_000:
            raise ValueError('Measurement log size exceeded')
        events, previous = [], None
        for line in self.path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            digest = row.pop('sha256')
            if row.get('previous_sha256') != previous or sha(row) != digest:
                raise ValueError('Measurement history changed')
            row['sha256'] = digest
            events.append(row)
            previous = digest
        return events

    @contextmanager
    def _locked(self, *, shared=False):
        # Exposure validation and append must be one serialized operation;
        # concurrent CLI invocations cannot both reuse an unseen family.
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.root / '.measurements.lock', os.O_CREAT | os.O_RDWR |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _append(self, task_id, kind, data):
        rows = self._events()
        if len(rows) >= 100000 or not text(task_id):
            raise ValueError('Bounded task identity required')
        row = {'schema_version': VERSION, 'event_id': f'event-{len(rows)+1}', 'task_id': task_id,
               'kind': kind, 'data': deepcopy(data), 'previous_sha256': rows[-1]['sha256'] if rows else None}
        row['sha256'] = sha(row)
        raw = canonical_json(row) + '\n'
        if len(raw.encode('utf-8')) + (self.path.stat().st_size if self.path.exists() else 0) > 32_000_000:
            raise ValueError('Measurement log size exceeded')
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return row

    def begin(self, task_id, metadata):
        with self._locked():
            return self._begin(task_id, metadata)

    def _begin(self, task_id, metadata):
        required = {'participant_id', 'condition', 'family_ids', 'harness', 'harness_model', 'experience',
                    'difficulty', 'assistance', 'order', 'prior_exposure', 'consent_reference'}
        if not isinstance(metadata, dict) or set(metadata) != required:
            raise ValueError('Task metadata must disclose harness, experience, assistance, order and consent reference')
        if any(r['task_id'] == task_id for r in self._events()):
            raise ValueError('Duplicate task identity')
        for key in required - {'family_ids', 'order', 'prior_exposure'}:
            if not text(metadata[key]):
                raise ValueError('Task metadata must be explicit')
        families = metadata['family_ids']
        if not isinstance(families, list) or not 1 <= len(families) <= 1000 or any(not text(f) for f in families) or len(set(families)) != len(families):
            raise ValueError('Distinct task families required')
        if type(metadata['order']) is not int or metadata['order'] < 1 or type(metadata['prior_exposure']) is not bool:
            raise ValueError('Invalid task order/exposure')
        if metadata['prior_exposure']:
            raise ValueError('Timing task must use previously unseen families')
        for event in self._events():
            if event['kind'] == 'begin' and event['data']['participant_id'] == metadata['participant_id'] and set(event['data']['family_ids']) & set(families):
                raise ValueError('Participant cannot repeat a source family across timing conditions')
        return self._append(task_id, 'begin', metadata)

    def record(self, task_id, kind, data):
        with self._locked():
            return self._record(task_id, kind, data)

    @staticmethod
    def _validate_data(kind, data):
        if not isinstance(kind, str) or kind not in MEASURE_KINDS:
            raise ValueError('Unknown researcher measure')
        if not isinstance(data, dict):
            raise ValueError('Event data must be an object')
        if kind == 'active_time':
            if set(data) != {'seconds', 'basis', 'reason'} or not number(data['seconds']) or not isinstance(data['basis'], str) or data['basis'] not in {'measured', 'synthetic'} or not text(data['reason']):
                raise ValueError('Active time must disclose measured/synthetic basis and reason')
        elif kind == 'setup_completion':
            if set(data) != {'complete', 'criterion', 'reason'} or type(data['complete']) is not bool or not text(data['criterion']) or not text(data['reason']):
                raise ValueError('Setup completion needs a declared criterion and reason')
        elif kind == 'comprehension':
            if set(data) != {'question_id', 'response', 'correct', 'rubric_version'} or not isinstance(data['question_id'], str) or data['question_id'] not in QUESTIONS or type(data['correct']) is not bool or not text(data['response']) or not text(data['rubric_version']):
                raise ValueError('Comprehension needs the scope/evidence/billing question and human-coded answer')
        elif set(data) - {'reason', 'category', 'details'} or not text(data.get('reason')) or any(not text(value) for value in data.values()):
            raise ValueError('Interventions and pauses require a reason and bounded optional category/details')
        if len(canonical_json(data).encode()) > 100000:
            raise ValueError('Researcher event data exceeds its bound')

    def _record(self, task_id, kind, data):
        rows = [r for r in self._events() if r['task_id'] == task_id]
        if not rows or rows[0]['kind'] != 'begin':
            raise ValueError('Begin the task first')
        if kind == 'correction':
            if not isinstance(data, dict) or set(data) - {'supersedes', 'reason', 'replacement'} or not {'supersedes', 'reason'} <= set(data) or not text(data['reason']):
                raise ValueError('Correction requires supersedes/reason and optional explicit replacement')
            target = next((row for row in rows if row['event_id'] == data['supersedes']), None)
            if target is None or target['kind'] not in MEASURE_KINDS:
                raise ValueError('Correction must refer to an earlier measurement in this task')
            if any(row['kind'] == 'correction' and row['data']['supersedes'] == target['event_id'] for row in rows):
                raise ValueError('Measurement is already superseded; correct the replacement as a new event')
            if 'replacement' in data:
                replacement = data['replacement']
                if not isinstance(replacement, dict) or set(replacement) != {'kind', 'data'} or replacement['kind'] != target['kind']:
                    raise ValueError('Correction replacement must retain the original measurement kind')
                self._validate_data(replacement['kind'], replacement['data'])
        else:
            self._validate_data(kind, data)
        return self._append(task_id, kind, data)

    def summary(self):
        rows = self.events()
        replaced = {r['data'].get('supersedes') for r in rows if r['kind'] == 'correction'}
        tasks = []
        for start in (r for r in rows if r['kind'] == 'begin'):
            live = [r for r in rows if r['task_id'] == start['task_id'] and r['event_id'] not in replaced]
            corrections = [r for r in live if r['kind'] == 'correction']
            effective = [r for r in live if r['kind'] != 'correction']
            effective.extend({**row, 'kind': row['data']['replacement']['kind'],
                              'data': row['data']['replacement']['data']}
                             for row in corrections if 'replacement' in row['data'])
            live = effective
            times = [r['data']['seconds'] for r in live if r['kind'] == 'active_time']
            bases = {r['data']['basis'] for r in live if r['kind'] == 'active_time'}
            by_basis = {basis: [r['data']['seconds'] for r in live
                               if r['kind'] == 'active_time' and r['data']['basis'] == basis]
                        for basis in ('measured', 'synthetic')}
            tasks.append({'task_id': start['task_id'], 'metadata': start['data'],
                          'active_seconds': sum(times) if times and len(bases) == 1 else None,
                          'active_seconds_basis': next(iter(bases)) if len(bases) == 1 else None,
                          'active_seconds_reason': 'mixed_measurement_bases_reported_separately' if len(bases) > 1 else None if times else 'not_measured',
                          'active_seconds_by_basis': {basis: sum(values) if values else None for basis, values in by_basis.items()},
                          'corrections': [{'event_id': row['event_id'], **row['data']} for row in corrections],
                          'correction_count': len(corrections),
                          'invalidated_event_count': sum('replacement' not in row['data'] for row in corrections),
                          'interventions': sum(r['kind'] == 'intervention' for r in live),
                          'agent_correction_loops': sum(r['kind'] == 'agent_correction' for r in live),
                          'setup': [r['data'] for r in live if r['kind'] == 'setup_completion'],
                          'comprehension': [r['data'] for r in live if r['kind'] == 'comprehension']})
        return {'schema_version': VERSION, 'tasks': tasks, 'population_inference': None,
                'population_inference_reason': 'Formative records do not establish population superiority.'}


def prepare_gt_bundle(root, *, study_digest, runtime):
    """Write inert data only. No scheduler commands, downloads or guessed site settings."""
    required = {'checkpoint', 'checkpoint_sha256', 'runtime', 'runtime_version', 'quantization', 'hardware', 'concurrency', 'unavailable_reasons'}
    if not isinstance(runtime, dict) or set(runtime) != required or not isinstance(runtime['unavailable_reasons'], dict):
        raise ValueError('Declare all runtime fields and unavailable reasons')
    if not isinstance(study_digest, str) or len(study_digest) != 64 or any(c not in '0123456789abcdef' for c in study_digest):
        raise ValueError('Frozen study digest required')
    for key in required - {'unavailable_reasons'}:
        value = runtime[key]
        if value is None and not text(runtime['unavailable_reasons'].get(key)):
            raise ValueError('Unknown runtime field needs a reason')
        if value is not None and key == 'concurrency' and (type(value) is not int or value < 1 or value > 256):
            raise ValueError('Finite concurrency required')
        if value is not None and key != 'concurrency' and not text(value):
            raise ValueError('Invalid runtime field')
    if runtime['checkpoint_sha256'] is not None and (len(runtime['checkpoint_sha256']) != 64 or any(c not in '0123456789abcdef' for c in runtime['checkpoint_sha256'])):
        raise ValueError('Checkpoint SHA256 required')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    bundle = {'schema_version': VERSION, 'study_sha256': study_digest, 'runtime': runtime,
              'authorized_to_execute': False, 'controller': 'researcher_existing_agent',
              'site_configuration': None, 'site_configuration_reason': 'Institutional operator must supply reviewed site configuration.',
              'measurements': {k: measurement(None, unit, 'unavailable', 'not_run') for k, unit in GT_FIELDS.items()}}
    (root / 'bundle.json').write_text(canonical_json(bundle) + '\n', encoding='utf-8')
    with (root / 'accounting.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['metric', 'value', 'unit', 'basis', 'reason'])
        writer.writerows([k, '', unit, 'unavailable', 'not_run'] for k, unit in GT_FIELDS.items())
    return bundle


def import_gt_accounting(path):
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError('Accounting file too large')
    rows = {}
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['metric', 'value', 'unit', 'basis', 'reason']:
            raise ValueError('Invalid accounting header')
        for row in reader:
            if set(row) != {'metric', 'value', 'unit', 'basis', 'reason'} or any(value is None for value in row.values()):
                raise ValueError('Accounting rows must match the declared header')
            key = row['metric']
            if key not in GT_FIELDS or key in rows or row['unit'] != GT_FIELDS[key]:
                raise ValueError('Unknown/duplicate metric or incorrect unit')
            value = float(row['value']) if row['value'] else None
            if key in {'input_tokens', 'output_tokens'} and value is not None and (not math.isfinite(value) or not value.is_integer()):
                raise ValueError('Observed token counts must be finite integers')
            rows[key] = measurement(value, row['unit'], row['basis'], row['reason'] or None)
    if set(rows) != set(GT_FIELDS):
        raise ValueError('Every metric needs a measurement or unavailable reason')
    for key in ('allocation_hours', 'queue_seconds', 'startup_seconds', 'inference_seconds', 'peak_memory_gib', 'checkpoint_seconds', 'recovery_seconds'):
        if rows[key]['value'] is not None and rows[key]['basis'] not in {'measured', 'operator_reported', 'synthetic'}:
            raise ValueError('Runtime observations cannot be token estimates')
    if rows['allocation_cost_usd']['value'] is not None and rows['allocation_cost_usd']['basis'] not in {'measured', 'invoice', 'synthetic'}:
        raise ValueError('Allocation cost must be measured or invoiced, separate from token estimates')
    seconds, tokens = rows['inference_seconds']['value'], rows['output_tokens']['value']
    rate = tokens / seconds if tokens is not None and seconds is not None and seconds > 0 else None
    rate_reason = None if rate is not None else 'output_tokens_or_positive_inference_seconds_unavailable'
    if rate is not None and not math.isfinite(rate):
        rate, rate_reason = None, 'derived_throughput_not_finite'
    return {'schema_version': VERSION, 'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'measurements': rows, 'output_tokens_per_second': rate,
            'throughput_reason': rate_reason,
            'throughput_measurement_bases': {'output_tokens': rows['output_tokens']['basis'],
                                            'inference_seconds': rows['inference_seconds']['basis']},
            'total_cost_usd': None, 'total_cost_reason': 'Allocation, token estimates and unknown infrastructure are reported separately; do not sum overlapping bases.'}
