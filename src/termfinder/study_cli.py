"""Offline V7 researcher controls; never selects or constructs a paid transport."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .experiments import _decode, _read_input, compare_study
from .exports import canonical_json


def load(path):
    return _decode(_read_input(Path(path)))


def write(value, out=None):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding='utf-8')
    else:
        print(raw, end='')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    def command(name, help):
        q = sub.add_parser(name, help=help)
        q.add_argument('--out', type=Path)
        return q
    def repository(q): q.add_argument('--repository', type=Path, required=True)
    def actor(q): q.add_argument('--actor', required=True)
    def corpus(q): q.add_argument('--corpus', type=Path, required=True)
    def runs(q): q.add_argument('--runs', type=Path, nargs='+', required=True)
    q = command('demo', 'Run a synthetic study across actual Quarry and shaped external adapters')
    q.add_argument('--include-faults', action='store_true')
    q = command('faults', 'Run request-keyed failures on real Quarry state, offline')
    q.add_argument('--concurrency', type=int, default=4)
    q = command('compare', 'Re-score frozen saved files without model calls')
    q.add_argument('study', type=Path)
    q = command('validate-spec', 'Validate a V7 draft contract')
    q.add_argument('--spec', type=Path, required=True); corpus(q)
    for name in ('spec-create', 'spec-amend'):
        q = command(name, 'Append a draft or amendment to a study repository')
        repository(q); actor(q); q.add_argument('--spec', type=Path, required=True)
        if name == 'spec-amend': q.add_argument('--reason', required=True)
    q = command('spec-freeze', 'Freeze the current validated revision; does not authorize calls')
    repository(q); actor(q); corpus(q)
    q = command('spec-history', 'Read immutable study history')
    repository(q)
    q = command('predictions-lock', 'Lock frozen runs before reading external gold')
    repository(q); actor(q); corpus(q); runs(q)
    q = command('score', 'Score locked runs against separately held complete-source gold')
    repository(q); corpus(q); runs(q)
    q.add_argument('--gold', type=Path, required=True); q.add_argument('--workspace', type=Path, required=True)
    q.add_argument('--bootstrap-samples', type=int, default=0)
    q = command('adapter-replay', 'Replay synthetic library-shaped outputs with call metering')
    corpus(q); q.add_argument('--config', type=Path, required=True); q.add_argument('--fixtures', type=Path, required=True)
    q.add_argument('--run-id', required=True); q.add_argument('--software-revision', required=True)
    q = command('review-create', 'Create full-source blinded or independent review packet')
    q.add_argument('--review', type=Path, required=True); corpus(q)
    q.add_argument('--runs', type=Path, nargs='+'); q.add_argument('--rubric', type=Path, required=True)
    q.add_argument('--mode', choices=['candidate_review','assisted_complete_source','independent_gold'], required=True)
    q.add_argument('--workspace', type=Path)
    q.add_argument('--details', type=Path, help='Separate original context/definition/translation/location attachments')
    for name in ('review-show', 'review-summary'):
        q = command(name, 'Read reviewer packet or review/time summary')
        q.add_argument('--review', type=Path, required=True)
    for name in ('review-judge', 'review-adjudicate'):
        q = command(name, 'Append separate human semantic decisions')
        q.add_argument('--review', type=Path, required=True); actor(q)
        q.add_argument('--item-id', required=True); q.add_argument('--axes', type=Path, required=True)
        if name == 'review-judge':
            q.add_argument('--note', default=''); q.add_argument('--supersedes')
        else:
            q.add_argument('--judgment-ids', nargs='+', required=True); q.add_argument('--reason', required=True)
    q = command('review-reverse', 'Reverse a decision without deleting original evidence')
    q.add_argument('--review', type=Path, required=True); actor(q)
    q.add_argument('--event-id', required=True); q.add_argument('--reason', required=True)
    q = command('review-item', 'Add an omission, correct a span, or remove a view item')
    q.add_argument('--review', type=Path, required=True); actor(q)
    q.add_argument('--action', choices=['add','correct','remove'], required=True)
    q.add_argument('--item', type=Path); q.add_argument('--item-id'); q.add_argument('--reason', required=True)
    q = command('review-complete', 'Attest independent qualified complete-source annotation')
    q.add_argument('--review', type=Path, required=True); actor(q)
    q.add_argument('--source-id', required=True); q.add_argument('--qualified', action='store_true')
    q.add_argument('--independent', action='store_true'); q.add_argument('--note', required=True)
    q = command('review-gold', 'Export a new immutable independent adjudicated gold version')
    q.add_argument('--review', type=Path, required=True); actor(q)
    q.add_argument('--version', required=True); q.add_argument('--provenance', required=True)
    q = command('review-timer', 'Start, pause, resume, finish or correct active review timing')
    q.add_argument('--review', type=Path, required=True); actor(q)
    q.add_argument('--action', choices=['start','pause','resume','finish','correct'], required=True)
    q.add_argument('--registry', type=Path); q.add_argument('--session-id'); q.add_argument('--reason', default='operator timing action')
    q.add_argument('--active-seconds', type=float); q.add_argument('--prior-exposure', action='store_true')
    q = command('measure-begin', 'Register a pseudonymous task and recorded exposure controls')
    q.add_argument('--log', type=Path, required=True); q.add_argument('--task-id', required=True)
    q.add_argument('--metadata', type=Path, required=True)
    q = command('measure-record', 'Append setup, active time, interventions or understanding')
    q.add_argument('--log', type=Path, required=True); q.add_argument('--task-id', required=True)
    q.add_argument('--kind', required=True); q.add_argument('--data', type=Path, required=True)
    q = command('measure-summary', 'Summarize recorded researcher measurements')
    q.add_argument('--log', type=Path, required=True)
    q = command('gt-prepare', 'Prepare inert GT data and accounting template; never submits')
    q.add_argument('--study-digest', required=True); q.add_argument('--runtime', type=Path, required=True)
    q = command('gt-accounting', 'Import accounting with explicit unavailable values and bases')
    q.add_argument('csv', type=Path)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        c = args.command
        if c in {'demo','faults','gt-prepare'} and args.out is None:
            raise ValueError('This command requires a fresh --out directory')
        if c == 'demo':
            from .study_demo import demonstrate
            value = demonstrate(args.out, include_faults=args.include_faults)
            write(value); return 0
        if c == 'faults':
            from .fault_experiments import run_fault_suite
            value = run_fault_suite(args.out, concurrency=args.concurrency)
            write(value); return 0
        if c == 'compare': value = compare_study(args.study)
        elif c == 'validate-spec':
            from .studies import validate_study
            value = validate_study(load(args.spec), load(args.corpus))
        elif c.startswith('spec-') or c in {'predictions-lock','score'}:
            from .studies import StudyRepository
            repo = StudyRepository(args.repository)
            if c == 'spec-create': value = repo.create(load(args.spec), actor=args.actor)
            elif c == 'spec-amend': value = repo.amend(load(args.spec), actor=args.actor, reason=args.reason)
            elif c == 'spec-freeze': value = repo.freeze(actor=args.actor, corpus=load(args.corpus))
            elif c == 'spec-history': value = repo.history()
            elif c == 'predictions-lock': value = repo.lock_predictions(load(args.corpus), [load(p) for p in args.runs], actor=args.actor)
            else: value = repo.score(load(args.corpus), [load(p) for p in args.runs], args.gold, workspace_root=args.workspace, bootstrap_samples=args.bootstrap_samples)
        elif c == 'adapter-replay':
            from .adapters import run_adapter, RecordedBackend
            value = run_adapter(load(args.corpus), load(args.config), RecordedBackend(load(args.fixtures)), run_id=args.run_id, software_revision=args.software_revision)
        elif c.startswith('review-'):
            from .semantic_review import ReviewWorkspace
            review = ReviewWorkspace(args.review)
            if c == 'review-create': value = review.create_packet(load(args.corpus), [load(p) for p in args.runs] if args.runs else None, mode=args.mode, rubric=load(args.rubric), workspace_root=args.workspace, evidence_details=load(args.details) if args.details else None)
            elif c == 'review-show': value = review.packet()
            elif c == 'review-summary': value = review.summary()
            elif c == 'review-judge': value = review.judge(args.item_id, load(args.axes), actor=args.actor, note=args.note, supersedes=args.supersedes)
            elif c == 'review-adjudicate': value = review.adjudicate(args.item_id, load(args.axes), judgment_ids=args.judgment_ids, actor=args.actor, reason=args.reason)
            elif c == 'review-reverse': value = review.reverse(args.event_id, actor=args.actor, reason=args.reason)
            elif c == 'review-item': value = review.record_item(args.action, load(args.item) if args.item else None, item_id=args.item_id, actor=args.actor, reason=args.reason)
            elif c == 'review-complete': value = review.mark_complete(args.source_id, actor=args.actor, qualified=args.qualified, independent=args.independent, note=args.note)
            elif c == 'review-gold': value = review.export_gold(args.version, actor=args.actor, provenance=args.provenance)
            elif args.action == 'start':
                if not args.registry: raise ValueError('A shared --registry is required for exposure controls')
                value = review.start_session(actor=args.actor, exposure_registry=args.registry, prior_exposure=args.prior_exposure)
            elif args.action == 'correct': value = review.correct_time(args.session_id, active_seconds=args.active_seconds, actor=args.actor, reason=args.reason)
            else: value = getattr(review, args.action + '_session')(args.session_id, actor=args.actor, reason=args.reason)
        elif c.startswith('measure-'):
            from .research_measurements import ResearcherLog
            log = ResearcherLog(args.log)
            if c == 'measure-begin': value = log.begin(args.task_id, load(args.metadata))
            elif c == 'measure-record': value = log.record(args.task_id, args.kind, load(args.data))
            else: value = log.summary()
        elif c == 'gt-prepare':
            from .research_measurements import prepare_gt_bundle
            value = prepare_gt_bundle(args.out, study_digest=args.study_digest, runtime=load(args.runtime))
            write(value); return 0
        elif c == 'gt-accounting':
            from .research_measurements import import_gt_accounting
            value = import_gt_accounting(args.csv)
        else: raise ValueError('Unknown command')
        write(value, args.out)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('quarry-study: ' + str(error), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
