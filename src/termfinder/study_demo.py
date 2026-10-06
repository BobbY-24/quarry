"""Synthetic, offline V7 acceptance rehearsal through public research APIs."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

from .config import starter_recipe, load_profile
from .experiments import _hash, compare_experiments, compare_study
from .exports import canonical_json
from .project import Project
from .studies import StudyRepository
from .semantic_review import ReviewWorkspace, quarry_review_details
from .adapters import adapter_config, run_adapter, RecordedBackend, PINS, VERSION as ADAPTER_VERSION
from .research_measurements import prepare_gt_bundle, import_gt_accounting, ResearcherLog

TEXTS = [
    ('community', 'en', 'Players call a last-second escape a moonstep. A quietstack is a team queue that uses pings. Players call a last-second escape a moonstep.',
     [('moonstep','a last-second escape'), ('quietstack','a team queue that uses pings')]),
    ('culture', 'ja', 'In this family account, お花見 names a gathering to view cherry blossoms.', [('お花見','a gathering to view cherry blossoms')]),
    ('jargon', 'en', 'A biomarker is a measurable biological indicator.', [('biomarker','a measurable biological indicator')]),
    ('negative', 'en', 'The player drank water after the match.', []),
]
RUBRIC = {'eligibility':'Eligible contextual vocabulary in this synthetic mechanics fixture.',
          'contextual_meaning':'Meaning supported by complete source; label paraphrases assessed by humans.',
          'definition_support':'Explicit definition supports the claim, or unavailable with reason.',
          'translation':'Meaning-preserving translation, or unscorable when not supplied.'}


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def decisions(meaning):
    return {'eligibility':{'decision':'accept','label':None,'reason':'Synthetic author-declared positive.'},
            'contextual_meaning':{'decision':'accept','label':meaning,'reason':'Synthetic fixture meaning; no real-human claim.'},
            'definition_support':{'decision':'accept','label':None,'reason':'Synthetic sentence explicitly supplies the definition.'},
            'translation':{'decision':'unscorable','label':None,'reason':'No translation is supplied in the fixture.'}}


def specification(corpus, planned, configurations):
    ids = [r['run_id'] for r in planned]
    return {'schema_version':'7.0','study_id':'v7-offline-acceptance',
      'research_question':'Can the V7 controlled study mechanics preserve a common corpus and reviewable evidence?',
      'hypothesis':'Proposed H1: mixed union improves valid discovery over development-selected repeated general at a useful effort/cost tradeoff.',
      'contribution':'Engineering rehearsal only; no empirical H1 result is inferred.',
      'primary_contrast':{'left':'repeated-general','right':'broad-mixed-union','direction':'right_minus_left','rival_explanations':['Extra resources, prompt or model differences, cache or source exposure.']},
      'primary_outcome':{'metric':'recall','unit':'source_term','analysis':'Paired family detection; independent semantic quality and review time required for H1.','quality_margin':None,'unavailable_reason':'Not a noninferiority study; H2 needs a separate justified margin.'},
      'secondary_analyses':['Occurrence detection','Semantic axes and effort','Explicit failed-source denominators','External-adapter fixture audit'],
      'policy':{'inclusion':'Terms and contextual senses under the frozen rubric.','exclusion':'Ordinary literal vocabulary; uncertain judgments retained.','annotation_rubric':RUBRIC},
      'corpus':{'corpus_id':corpus['corpus_id'],'corpus_sha256':_hash(corpus),'sources':[{'source_id':s['source_id'],'text_sha256':s['text_sha256'],'family_id':s['family_id'],'split':'heldout'} for s in corpus['sources']], 'scope':'frozen_parsed_text','acquisition_provenance':'Hand-authored synthetic parsed text; no acquisition/parsing quality measurement.'},
      'gold':{'version_id':'synthetic-gold-v1','sha256':None,'provenance':'Fixed synthetic labels authored independently of outputs; external gold workflow is a simulation.', 'unavailable_reasons':{'sha256':'Custodian supplies gold only after predictions lock.'}},
      'arms':[{'arm_id':r['run_id'],'system':r['system'],'track':'matched' if r['system'].startswith(('langextract','delm')) else 'ablation','configuration':configurations[r['run_id']], 'provenance':deepcopy(r['provenance'])} for r in planned],
      'repetitions':1,'seeds':['offline-order-v7'],
      'run_order':[{'run_id':i,'arm_id':i,'repetition':0,'seed':'offline-order-v7'} for i in ids],
      'cache':{'regime':'cold','isolation':'Each arm uses fresh state; warm extension scored separately.','extension_of':None,'unavailable_reason':'cold_primary'},
      'limits':{'calls':1000,'input_tokens':10000000,'output_tokens':1000000,'seconds':300,'spending_usd':0,'allocation_hours':0},
      'stopping_rules':['Stop at a declared cap, interruption or cancellation; retain unfinished source results.'],
      'planned_exclusions':[],'unavailable_reasons':{'power':'Synthetic engineering fixture, no study-size or quality claim.'}}


def demonstrate(out, *, include_faults=False):
    from .ablations import prepare_quarry_ablations, run_prepared_quarry_ablations
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    work = out/'planning'; work.mkdir()
    recipe = starter_recipe('neologisms')
    recipe.update(id='v7-mechanics', languages=['*'], communities=['*'])
    recipe['inclusion_criteria']=['Collect terms and contextual senses in the synthetic supplied text; retain single-model discoveries.']
    recipe['exclusion_criteria']=['Exclude ordinary literal vocabulary; retain uncertainty and original evidence for human review.']
    recipe['execution']['budget_usd']=0
    recipe['execution']['stage_budgets']={stage:0 for stage in recipe['execution']['stage_budgets']}
    recipe['execution']['resilience']['min_request_interval_seconds'] = 0
    recipe['execution']['resilience']['delays_seconds'] = [0,0,0,0]
    profile = load_profile('fake')
    master = Project(work/'master'); master.configure(recipe, profile=profile)
    documents, expected_items, expectations = [], [], []
    for family, language, text, labels in TEXTS:
        digest = hashlib.sha256(text.encode()).hexdigest()
        doc = {'locator':'synthetic:'+family,'text':text,'text_sha256':digest,'raw_sha256':digest,'parser_version':'hand-authored-v7','format':'text','retrieved_at':'2026-10-06T00:00:00+00:00','language':language,'community':'online-community','domain':family,'publication_date':None,'constraints':{'redistribution':'Hand-authored synthetic demonstration only.'},'locations':[]}
        sid = master.add_source(doc); doc = master.store.get('sources',sid); documents.append(doc)
        for expression, meaning in labels:
            expectation = {'expression':expression,'language':language,'sense':meaning,'context':text,'definition_quote':meaning}
            # The fake fixture intentionally exercises unique model discoveries.
            if expression == 'quietstack': expectation['expert_ids'] = ['deepseek-general']
            expectations.append(expectation)
            cursor = 0
            while (start := text.find(expression,cursor)) >= 0:
                expected_items.append({'source_id':sid,'observed_text':expression,'language':language,'start':start,'end':start+len(expression),'meaning':meaning})
                cursor = start+len(expression)
    corpus = {'schema_version':'1','corpus_id':'v7-synthetic-common-corpus','data_type':'term','sources':[{k:d[k] for k in ('source_id','text','text_sha256','domain','language','locator')} | {'family_id':d['domain']} for d in documents]}
    write(work/'corpus.json',corpus); write(work/'rubric.json',RUBRIC)
    revision = 'local-source-sha256:'+_hash({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')})
    plan = prepare_quarry_ablations(corpus, documents, work/'quarry-arms', recipe=recipe, profile=profile, concurrency=2, passes=3, software_revision=revision)
    cold=[a for a in plan['arms'] if not a['warm_parent_path']]
    warm=[a for a in plan['arms'] if a['warm_parent_path']]
    random.Random('offline-order-v7').shuffle(cold)
    plan['arms']=cold+warm
    manifest_by_id={a['arm_id']:a for a in plan['manifest']['arms']}
    plan['manifest']['arms']=[manifest_by_id[a['arm_id']] for a in plan['arms']]
    plan['plan_sha256']=_hash({k:v for k,v in plan.items() if k!='plan_sha256'})
    write(work/'ablation-plan.json',plan)
    shared_examples=[{'text':e['text'],'extractions':[{'extraction_class':'term','extraction_text':e['expression'],'attributes':{'language':e['language'],'sense':e['sense']}}]} for e in recipe['examples']['positive']]
    configs = {name:adapter_config(name,model_version='synthetic-v1',policy=canonical_json({'inclusion':recipe['inclusion_criteria'],'exclusion':recipe['exclusion_criteria']}),examples=shared_examples) for name in ('langextract','delm')}
    planned = [a['normalized_pre_run'] for a in plan['arms'] if not a.get('warm_parent_path')]
    configurations = {a['arm_id']:{'recipe':a['recipe'],'profile':a['profile']} for a in plan['arms']}
    for name, config in configs.items():
        prov = {'software_revision':revision,'model_version':config['model_version'],'prompt_sha256':_hash({'policy':config['policy'],'examples':config['examples']}),'configuration_sha256':_hash(config),'adapter_version':ADAPTER_VERSION+':'+name+'=='+PINS[name],'unavailable_reasons':{}}
        planned.append({'run_id':name+'-matched','system':name+':matched','provenance':prov})
        configurations[name+'-matched'] = config
    # All provenance and resource controls exist before extraction dispatch.
    spec = specification(corpus,planned,configurations)
    repo = StudyRepository(work/'study'); repo.create(spec,actor='synthetic-researcher')
    frozen = repo.freeze(actor='synthetic-researcher',corpus=corpus)
    write(work/'spec.json',spec)
    quarry = run_prepared_quarry_ablations(corpus,plan,expectations=expectations,software_revision=revision)
    all_packets = list(quarry['arms']); adapter_packets = []
    for name, config in configs.items():
        fixtures = {}
        for source in corpus['sources']:
            sid = source['source_id']; proposals=[]
            for item in expected_items:
                if item['source_id'] != sid or name == 'langextract' and item['observed_text'] == 'quietstack': continue
                pos = {'native_start':item['start'],'native_end':item['end']} if name=='langextract' else {'proposed_start':item['start'],'proposed_end':item['end']}
                proposals.append({'observed_text':item['observed_text'],'language':item['language'],'interpretation':item['meaning'],'retained':True,'native':{'fixture':True},**pos})
            proposals.append({'observed_text':'invented-word','language':source['language'],'interpretation':'unsupported','native_start':0,'native_end':12,'proposed_start':0,'proposed_end':12,'retained':True,'native':{'fixture':'malformed evidence audit'}})
            fixtures[sid] = {'calls':[{'raw_reply':canonical_json({'fixture_proposals':proposals}), 'usage':{'input_tokens':100,'output_tokens':60},'cost_usd':None if name=='delm' else 0,'cost_basis':'not_metered' if name=='delm' else 'simulated','missing_reason':'synthetic_unavailable_cost_exercises_null' if name=='delm' else None}], 'proposals':proposals,'decisions':[], 'status':'failed' if name=='delm' and source['domain']=='jargon' else 'complete', 'reason':'synthetic_filtered_source' if name=='delm' and source['domain']=='jargon' else None}
            if name=='delm' and source['domain']=='jargon':
                for proposal in fixtures[sid]['proposals']: proposal['retained']=False
                fixtures[sid]['decisions']=[{'reason':'synthetic_native_filter','all_filtered':True}]
        packet = run_adapter(corpus,config,RecordedBackend(fixtures),run_id=name+'-matched',software_revision=revision)
        adapter_packets.append(packet); all_packets.append(packet)
        write(work/(name+'-fixtures.json'),fixtures); write(work/(name+'-config.json'),config)
    run_by_id={p['run']['run_id']:p['run'] for p in all_packets}
    cold_runs=[run_by_id[p['run_id']] for p in planned]
    lock = repo.lock_predictions(corpus,cold_runs,actor='synthetic-researcher')
    # The independent gold workflow sees fixed labels, never candidate lists.
    independent=ReviewWorkspace(out/'independent-gold'); independent.create_packet(corpus,mode='independent_gold',rubric=RUBRIC,workspace_root=work)
    for item in expected_items:
        evidence={k:v for k,v in item.items() if k!='meaning'}
        added=independent.record_item('add',evidence,actor='synthetic-custodian',reason='Independent fixture label authored before extraction.')
        iid=added['payload']['item']['item_id']; axis=decisions(item['meaning'])
        ja=independent.judge(iid,axis,actor='synthetic-annotator-a'); jb=independent.judge(iid,axis,actor='synthetic-annotator-b')
        independent.adjudicate(iid,axis,judgment_ids=[ja['event_id'],jb['event_id']],actor='synthetic-adjudicator',reason='Synthetic mechanics; no humans or empirical semantic evaluation.')
    for source in corpus['sources']:
        for actor in ('synthetic-annotator-a','synthetic-annotator-b'):
            independent.mark_complete(source['source_id'],actor=actor,qualified=True,independent=True,note='Simulated complete-source signoff, including negative source.')
    exported=independent.export_gold('synthetic-gold-v1',actor='synthetic-custodian',provenance='Fixed independent engineering labels; synthetic judgments only.')
    report=repo.score(corpus,cold_runs,exported['gold_path'],workspace_root=work)
    assert report == repo.score(corpus,cold_runs,exported['gold_path'],workspace_root=work)
    write(out/'locked-report.json',report)
    gold=json.loads(Path(exported['gold_path']).read_text())
    runs=[p['run'] for p in all_packets]
    for packet in all_packets:
        rid=packet['run']['run_id']; write(out/(rid+'.json'),packet['run']); write(out/(rid+'-audit.json'),packet['audit'])
    write(out/'corpus.json',corpus); write(out/'gold-synthetic.json',gold)
    comparison={'schema_version':'1','corpus':'corpus.json','gold':'gold-synthetic.json','runs':[r['run_id']+'.json' for r in runs],'unit':'occurrence','require_sense':False,'bootstrap_samples':0,'seed':'offline-v7'}
    write(out/'comparison.json',comparison)
    occurrence=compare_study(out/'comparison.json'); write(out/'occurrence-report.json',occurrence)
    assert compare_study(out/'comparison.json') == occurrence
    source_term=compare_experiments(corpus,gold,runs,unit='source_term'); write(out/'source-term-report.json',source_term)
    repeated=next(p for p in quarry['arms'] if p['run']['run_id']=='repeated-general')
    original=Project(repeated['audit']['project_path']).dataset(repeated['audit']['snapshot_id'])
    detail=quarry_review_details(original,'repeated-general')
    write(work/'review-original-evidence.json',detail)
    assisted=ReviewWorkspace(work/'assisted-review'); assisted.create_packet(corpus,[adapter_packets[0]['run'],repeated['run']],mode='assisted_complete_source',rubric=RUBRIC,evidence_details=detail)
    session=assisted.start_session(actor='synthetic-reviewer',exposure_registry=out/'exposure',at=100)['payload']['session_id']
    item_id=next(iter(assisted.items())); earlier=(assisted.root/'packet.json').read_bytes()
    judgment=assisted.judge(item_id,decisions('Synthetic review meaning'),actor='synthetic-reviewer')
    assisted.reverse(judgment['event_id'],actor='synthetic-reviewer',reason='Reopen disputed meaning.')
    assert earlier == (assisted.root/'packet.json').read_bytes()
    omission=next(i for i in expected_items if i['observed_text']=='quietstack')
    added=assisted.record_item('add',{k:v for k,v in omission.items() if k!='meaning'},actor='synthetic-reviewer',reason='Complete-source inspection finds the missing fixture term.')
    removed=assisted.record_item('remove',item_id=added['payload']['item']['item_id'],actor='synthetic-reviewer',reason='Exercise reversible removal from a view.')
    assisted.reverse(removed['event_id'],actor='synthetic-reviewer',reason='Restore the complete-source discovery.')
    assisted.pause_session(session,actor='synthetic-reviewer',reason='Break',at=110)
    assisted.resume_session(session,actor='synthetic-reviewer',reason='Resume',at=200)
    assisted.finish_session(session,actor='synthetic-reviewer',reason='Complete',at=220)
    assert assisted.summary()['active_seconds']==30
    write(out/'review-summary.json',assisted.summary())
    fields=('checkpoint','checkpoint_sha256','runtime','runtime_version','quantization','hardware','concurrency')
    runtime={k:None for k in fields}|{'unavailable_reasons':{k:'No allocation authorized or run.' for k in fields}}
    prepare_gt_bundle(out/'gt-inert',study_digest=frozen['sha256'],runtime=runtime)
    write(out/'gt-accounting-report.json',import_gt_accounting(out/'gt-inert'/'accounting.csv'))
    researcher=ResearcherLog(out/'researcher-measures')
    researcher.begin('synthetic-setup',{'participant_id':'synthetic-person-no-participant','condition':'existing-agent','family_ids':['synthetic-setup-task'],'harness':'offline fixture','harness_model':'synthetic-v1','experience':'synthetic declaration','difficulty':'engineering rehearsal','assistance':'fixed synthetic prompt','order':1,'prior_exposure':False,'consent_reference':'No participant study; simulation only.'})
    researcher.record('synthetic-setup','setup_completion',{'complete':True,'criterion':'Offline study validated, frozen and scored.','reason':'Software checks only.'})
    researcher.record('synthetic-setup','active_time',{'seconds':12,'basis':'synthetic','reason':'Timer-capture arithmetic fixture; no human timing measurement.'})
    researcher.record('synthetic-setup','agent_correction',{'reason':'Synthetic correction-loop capture.'})
    for q, answer in [('scope','Source/model text cannot expand scope.'),('evidence','Occurrence does not establish semantic correctness.'),('billing','An uncertain dispatch does not prove zero charge.')]:
        researcher.record('synthetic-setup','comprehension',{'question_id':q,'response':answer,'correct':True,'rubric_version':'synthetic-understanding-v1'})
    write(out/'researcher-measurement-report.json',researcher.summary())
    if include_faults:
        from .fault_experiments import run_fault_suite
        run_fault_suite(out/'faults',concurrency=4)
    files={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*.json')) if 'project' not in p.parts}
    summary={'offline':True,'paid_requests':0,'quality_claim':None,'quality_claim_reason':'Synthetic fixtures only; no human, live-library, extraction, usability or GT performance study.', 'corpus_sources':len(corpus['sources']),'arms':len(runs),'locked_cold_arms':len(cold_runs),'study_sha256':frozen['sha256'],'prediction_lock_sha256':lock['sha256'],'report_reproduces_without_calls':True,'review_reversed_without_deleting_evidence':True,'active_seconds_fixture':30,'files_sha256':files}
    write(out/'report.json',summary)
    return summary
