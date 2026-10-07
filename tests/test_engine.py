"""Fault injection at durable boundaries; all providers and inputs are fake."""
from copy import deepcopy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from termfinder import Project, FakeProvider, Response
from termfinder.config import starter_recipe, load_profile, load_recipe
from termfinder.costs import estimate, token_cost
from termfinder.engine import Engine
from termfinder.grounding import normalize, parse_response
from termfinder.providers import ProviderError, HTTPProvider
from termfinder.sources import parse_document


TEXT = "🧪 Café crews call a pause a moonstep. In this group anchor means holding the checkpoint."


def candidate(expression="moonstep", sense="a pause", context=TEXT, **extra):
    return {"expression":expression,"language":"en","sense":sense,"context":context,
            "start":None,"definition_quote":None,"attributes":{},"translation":None,**extra}


def response(items=(), complete=True, **extra):
    return Response(json.dumps({"candidates":list(items),"coverage_complete":complete},ensure_ascii=False),
                    30,20,"stop","fake-v1",**extra)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Project(Path(self.tmp.name)/"p")
        self.recipe = starter_recipe("neologisms")
        # Preserve the V6.1 policy contract for already-saved recipes. New
        # automatic model retries are exercised separately in test_resilience.
        self.recipe["execution"].pop("resilience", None)
        self.recipe["execution"]["max_retries"] = 1
        self.recipe["execution"]["concurrency"] = 1
        self.project.configure(self.recipe,"fake")
        self.source_id = self.project.add_source(parse_document(TEXT.encode(),"text/plain","fixture.txt",{"community":"Gaming","language":"en"}))

    def fake(self, items):
        return FakeProvider(expectations=[dict(i,expert_ids=None) for i in items])

    def test_grounded_union_keeps_single_model_and_senses(self):
        provider = FakeProvider(expectations=[],responses=[response([candidate("anchor","checkpoint holder")]),
            response([candidate("anchor","last defender"),candidate()])])
        self.project.collect(provider)
        terms = self.project.inventory()["terms"]
        self.assertEqual(len(terms),3)
        self.assertEqual({t["sense"] for t in terms if t["expression"]=="anchor"},{"checkpoint holder","last defender"})
        self.assertIn("moonstep",[t["expression"] for t in terms])
        self.assertTrue(all(t["meaning_status"]=="model_proposed" for t in terms))

    def test_unicode_offsets_original_text_and_conservative_normalization(self):
        provider = self.fake([candidate("Café","a crew label")])
        self.project.collect(provider)
        row = self.project.inventory()["occurrences"][0]
        self.assertEqual(TEXT[row["start"]:row["end"]],"Café")
        self.assertEqual(row["start"],2)  # emoji counts as one code point
        self.assertEqual(normalize("CAFÉ","en"),"café")
        self.assertEqual(normalize("I","tr"),"ı")
        self.assertEqual(normalize("İ","tr"),"i")
        self.assertNotEqual(normalize("cafe","en"),normalize("café","en"))

    def test_exact_occurrence_dedup_preserves_all_provenance(self):
        provider = self.fake([candidate()])
        self.project.collect(provider)
        inventory = self.project.inventory()
        self.assertEqual(len(inventory["terms"]),1)
        self.assertEqual(len(inventory["occurrences"]),1)
        self.assertEqual(len(inventory["occurrences"][0]["provenance"]),2)

    def test_ungrounded_failed_proposal_is_audited_not_inventory(self):
        self.project.collect(FakeProvider([], [response([candidate(context="Invented moonstep context.")]),response([])]))
        inventory = self.project.inventory()
        self.assertFalse(inventory["terms"])
        self.assertIn("context_not_exact",inventory["audit"][0]["reason"])

    def test_bad_offset_repairs_exact_quote_without_deleting_term(self):
        self.project.collect(FakeProvider([], [response([candidate(start=999)]),response([])]))
        inventory = self.project.inventory()
        self.assertEqual(len(inventory["terms"]),1)
        self.assertIn("offset_repaired",inventory["audit"][0]["reason"])

    def test_unknown_meaning_and_definition_epistemics(self):
        self.project.collect(FakeProvider([], [response([candidate(sense=None,definition_quote="a pause")]),response([])]))
        term = self.project.inventory()["terms"][0]
        self.assertIsNone(term["sense"])
        self.assertTrue(term["sense_reason"])
        self.assertFalse(term["source_supported_definition"]["semantic_entailment_verified"])
        self.assertIsNone(term["coinage_date"])

    def test_required_project_attribute_missing_is_audited_with_null_reason(self):
        recipe=deepcopy(self.recipe);recipe["output"]["attributes"]["innovation_type"]["required"]=True
        self.project.configure(recipe,"fake")
        proposal=candidate();proposal.pop("sense")
        self.project.collect(FakeProvider([], [response([proposal]),response([])]))
        inventory=self.project.inventory()
        self.assertEqual(len(inventory["terms"]),1)
        self.assertIn("required_field_missing:sense",inventory["audit"][0]["reason"])
        self.assertIn("required_attribute_unavailable",inventory["audit"][0]["reason"])
        self.assertIsNone(inventory["occurrences"][0]["model_attributes"]["innovation_type"])
        self.assertTrue(inventory["occurrences"][0]["attribute_null_reasons"]["innovation_type"])

    def test_truncation_salvages_complete_parent_and_recovers_smaller_windows(self):
        raw = '{"candidates":[' + json.dumps(candidate(),ensure_ascii=False) + ',{"expression":"an unfinished'
        provider = FakeProvider([], [Response(raw,100,200,"length","fake-v1")]+[response([])]*10)
        self.project.collect(provider)
        inventory = self.project.inventory()
        self.assertEqual(len(inventory["terms"]),1)
        self.assertTrue(any(j["depth"]==1 for j in inventory["jobs"]))
        self.assertEqual(self.project.status()["coverage"]["partial"],0)
        self.assertTrue(any(a["reason"]=="malformed_or_truncated_response" for a in inventory["audit"]))

    def test_unrecoverable_truncation_is_explicit_partial(self):
        recipe=deepcopy(self.recipe);recipe["execution"]["split_depth"]=0
        self.project.configure(recipe,"fake")
        self.project.collect(FakeProvider([], [response([candidate()],complete=False),response([])]))
        self.assertEqual(len(self.project.inventory()["terms"]),1)
        self.assertEqual(self.project.status()["jobs"]["partial"],1)
        self.assertEqual(self.project.status()["status"],"partial")

    def test_nonfinite_response_salvages_prior_objects_without_poisoning_cache(self):
        for numeric in ("NaN", "Infinity", "1e999"):
            project=Project(Path(self.tmp.name)/numeric)
            recipe=deepcopy(self.recipe);recipe["execution"]["split_depth"]=0
            project.configure(recipe,"fake")
            project.add_source(parse_document(TEXT.encode(),"text/plain","fixture.txt",{"community":"Gaming","language":"en"}))
            raw='{"candidates":['+json.dumps(candidate())+',{"expression":"anchor","attributes":{"number":'+numeric+'}}],"coverage_complete":true}'
            provider=FakeProvider([], [Response(raw,30,40,"stop","fake-v1"),response([])])
            project.collect(provider);project.resume(provider)
            self.assertEqual(len(project.inventory()["terms"]),1)
            self.assertEqual(project.status()["jobs"].get("running",0),0)
            self.assertEqual(project.status()["jobs"]["partial"],1)

    def test_concurrency_bound_and_real_profile_cost_reporting_are_explicit(self):
        recipe=deepcopy(self.recipe);recipe["execution"]["concurrency"]=2
        self.project.configure(recipe,"glm-deepseek")
        lock=threading.Lock()
        active=maximum=0
        class Bounded(FakeProvider):
            def complete(self,request):
                nonlocal active,maximum
                with lock:active+=1;maximum=max(maximum,active)
                time.sleep(0.03)
                result=super().complete(request)
                with lock:active-=1
                return result
        provider=Bounded([candidate()]);self.project.collect(provider)
        self.assertLessEqual(maximum,2)
        self.assertGreater(self.project.status()["costs"]["extraction"]["simulated_usd"],0)
        self.assertEqual(self.project.status()["costs"]["extraction"]["estimated_actual_usd"],0)

    def test_resume_no_repeated_successful_calls(self):
        provider = self.fake([candidate()])
        self.project.collect(provider,max_jobs=1)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(self.project.status()["jobs"]["pending"],1)
        reopened=Project(self.project.path)
        reopened.resume(provider)
        self.assertEqual(len(provider.calls),2)
        reopened.resume(provider)
        self.assertEqual(len(provider.calls),2)

    def test_specialists_additive_cache_does_not_repeat_broad(self):
        provider=self.fake([candidate()]);self.project.collect(provider)
        self.assertEqual(len(provider.calls),2)
        recipe=deepcopy(self.recipe);recipe["mode"]="specialists"
        self.project.configure(recipe,"fake");self.project.resume(provider)
        self.assertEqual(len(provider.calls),3)
        self.assertEqual(len(self.project.inventory()["terms"]),1)

    def test_recipe_model_prompt_versions_invalidate_cache(self):
        provider=self.fake([candidate()]);self.project.collect(provider)
        recipe=deepcopy(self.recipe);recipe["version"]="2.0"
        self.project.configure(recipe,"fake");self.project.collect(provider)
        self.assertEqual(len(provider.calls),4)
        profile=load_profile("fake");profile["models"]["glm"]["version"]="revision-2"
        self.project.configure(recipe,profile);self.project.collect(provider)
        self.assertEqual(len(provider.calls),5)
        with patch("termfinder.engine.VERSION","prompt-revision-2"):
            self.project.collect(provider)
        self.assertEqual(len(provider.calls),7)

    def test_call_budget_survives_resume_and_raise_does_not_repeat_success(self):
        recipe=deepcopy(self.recipe);recipe["execution"]["max_calls"]=1
        self.project.configure(recipe,"fake");provider=self.fake([candidate()])
        self.project.collect(provider);self.project.resume(provider)
        self.assertEqual(len(provider.calls),1)
        self.assertIn("budget",self.project.status()["stop_reason"])
        recipe["execution"]["max_calls"]=2
        self.project.configure(recipe,"fake");self.project.resume(provider)
        self.assertEqual(len(provider.calls),2)

    def test_spending_budget_reserves_before_call_and_reports_stage(self):
        profile=load_profile("fake")
        for m in profile["models"].values(): m["input_per_million"]=1
        recipe=deepcopy(self.recipe);recipe["execution"]["budget_usd"]=0.01
        self.project.configure(recipe,profile);provider=self.fake([candidate()])
        self.project.collect(provider)
        self.assertFalse(provider.calls)
        self.assertEqual(self.project.status()["jobs"]["pending"],2)
        self.assertIn("reservation",self.project.status()["stop_reason"])

    def test_uncertain_transport_not_automatically_retried(self):
        provider=FakeProvider([], [ProviderError("synthetic_timeout",uncertain=True)])
        self.project.collect(provider);self.project.resume(provider)
        self.assertEqual(len(provider.calls),1)
        job=next(j for j in self.project.inventory()["jobs"] if j["status"]=="uncertain")
        with self.assertRaises(ValueError):self.project.resolve_uncertain(job["job_id"],retry=True)
        self.project.resolve_uncertain(job["job_id"],retry=True,acknowledge_possible_duplicate_billing=True)
        self.project.resume(provider)
        self.assertEqual(len(provider.calls),3)
        self.assertTrue(any(c["status"]=="uncertain" for c in self.project.inventory()["costs"]))

    def test_unknown_usage_keeps_grounded_discovery_and_stops(self):
        partial=Response(response([candidate()]).text,None,None,"stop","fake-v1")
        provider=FakeProvider([], [partial])
        self.project.collect(provider)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(len(self.project.inventory()["terms"]),1)
        self.assertEqual(self.project.status()["jobs"]["uncertain"],1)

    def test_crash_after_dispatch_retains_unknown_attempt_reserve(self):
        provider=self.fake([candidate()]);engine=Engine(self.project,provider)
        root=engine.prepare()[0];engine.admit(self.project.store.get("jobs",root))
        reopened=Project(self.project.path);reopened.resume(provider)
        self.assertFalse(provider.calls)
        self.assertEqual(reopened.status()["jobs"]["uncertain"],1)
        self.assertEqual(reopened.inventory()["costs"][0]["status"],"uncertain")

    def test_crash_after_response_checkpoint_replays_without_call(self):
        provider=self.fake([candidate()]);engine=Engine(self.project,provider)
        root=engine.prepare()[0];job=self.project.store.get("jobs",root)
        attempt,_=engine.admit(job)
        from dataclasses import asdict
        self.project.store.put("cache",root,{"key":root,"response":asdict(response([candidate()])),"attempt_id":attempt["attempt_id"]})
        attempt.update(status="settled",settled_usd=0)
        self.project.store.put("costs",attempt["attempt_id"],attempt)
        self.project.resume(provider)
        self.assertEqual(len(provider.calls),1) # other broad expert only
        self.assertEqual(len(self.project.inventory()["terms"]),1)
        self.assertTrue(any(p["cached"] for o in self.project.inventory()["occurrences"] for p in o["provenance"]))

    def test_known_rejection_retry_is_bounded_and_cannot_bill_unknown(self):
        provider=FakeProvider([], [ProviderError("http_429",retryable=True),response([candidate()]),response([])])
        self.project.collect(provider)
        ledger=self.project.inventory()["costs"]
        self.assertEqual(len(provider.calls),3)
        self.assertEqual(sum(c["status"]=="rejected" for c in ledger),1)
        self.assertEqual(next(c for c in ledger if c["status"]=="rejected")["settled_usd"],0)

    def test_cancel_preserves_inflight_result_and_pending_work(self):
        project=self.project
        class Cancelling(FakeProvider):
            def complete(self,request):
                project.cancel()
                return super().complete(request)
        provider=Cancelling([candidate()]);self.project.collect(provider)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(len(self.project.inventory()["terms"]),1)
        self.assertEqual(self.project.status()["status"],"cancelled")
        self.project.resume(provider=FakeProvider([candidate()]))
        self.assertEqual(self.project.status()["coverage"]["partial"],0)

    def test_process_lock_blocks_configure_and_collect(self):
        with self.project._lock():
            with self.assertRaises(RuntimeError):self.project.configure(self.recipe,"fake")
            with self.assertRaises(RuntimeError):self.project.collect(self.fake([]))

    def test_explicit_partial_retry_bypasses_incomplete_cache_once(self):
        recipe=deepcopy(self.recipe);recipe["execution"]["split_depth"]=0
        self.project.configure(recipe,"fake")
        provider=FakeProvider([], [response([candidate()],complete=False),response([]),response([candidate()])])
        self.project.collect(provider)
        job=next(j for j in self.project.inventory()["jobs"] if j["status"]=="partial")
        self.project.retry_failed(job["job_id"]);self.project.resume(provider)
        self.assertEqual(len(provider.calls),3)
        self.assertEqual(self.project.status()["coverage"]["partial"],0)
        self.project.resume(provider);self.assertEqual(len(provider.calls),3)

    def test_crash_during_intentional_retry_cannot_replay_old_cache(self):
        recipe=deepcopy(self.recipe);recipe["execution"]["split_depth"]=0
        self.project.configure(recipe,"fake")
        provider=FakeProvider([], [response([],complete=False),response([])])
        self.project.collect(provider)
        job=next(j for j in self.project.inventory()["jobs"] if j["status"]=="partial")
        self.project.retry_failed(job["job_id"])
        engine=Engine(self.project,provider);engine.prepare()
        engine.admit(self.project.store.get("jobs",job["job_id"]))
        self.project.resume(provider)
        self.assertEqual(self.project.store.get("jobs",job["job_id"])["status"],"uncertain")
        self.assertEqual(len(provider.calls),2)

    def test_incremental_source_update_retains_complete_inventory(self):
        provider=self.fake([candidate()]);self.project.collect(provider)
        self.project.add_source(parse_document((TEXT+" Updated.").encode(),"text/plain","fixture.txt",{"community":"Gaming","language":"en"}))
        self.project.collect(provider)
        self.assertEqual(len(self.project.inventory()["sources"]),2)
        self.assertEqual(len(provider.calls),4)

    def test_source_metadata_scope_dates_unknown_and_mixed_language(self):
        self.assertIsNone(self.project.source_exclusion({"language":"mul","community":"Gaming","publication_date":None}))
        recipe=deepcopy(self.recipe);recipe["dates"]={"start":"2020-01-01","end":"2021-01-01","unknown":"exclude"}
        self.project.configure(recipe,"fake");self.project.collect(self.fake([candidate()]))
        self.assertFalse(self.project.inventory()["terms"])
        self.assertEqual(self.project.inventory()["sources"][0]["scope_exclusion"],"publication_date_unavailable")

    def test_reconfigured_source_scope_excludes_old_sources_without_deletion(self):
        self.project.add_source(parse_document(TEXT.encode(),"text/plain","https://example.org/source",{"community":"Gaming","language":"en"}))
        recipe=deepcopy(self.recipe);recipe["source_scope"]={"domains":["other.example"],"local":False}
        self.project.configure(recipe,"fake");provider=self.fake([candidate()]);self.project.collect(provider)
        self.assertFalse(provider.calls)
        self.assertEqual(len(self.project.inventory()["sources"]),2)
        self.assertEqual({s["scope_exclusion"] for s in self.project.inventory()["sources"]},{"local_sources_disabled","source_domain_out_of_scope"})

    def test_successful_proposal_variants_survive_frozen_export_inventory(self):
        recipe=deepcopy(self.recipe);recipe["output"]["translations"]=True
        self.project.configure(recipe,"fake")
        a=candidate(attributes={"innovation_type":"lexical"},translation="Proposed translation A",definition_quote="a pause")
        b=candidate(attributes={"innovation_type":"semantic"},translation="Proposed translation B",definition_quote="call a pause a moonstep")
        self.project.collect(FakeProvider([], [response([a]),response([b])]))
        frozen=self.project.dataset(self.project.snapshot("variants"))
        proposals=[p["proposal"] for p in frozen["occurrences"][0]["provenance"]]
        self.assertEqual({p["translation"] for p in proposals},{a["translation"],b["translation"]})
        self.assertEqual({p["definition_quote"] for p in proposals},{a["definition_quote"],b["definition_quote"]})
        self.assertEqual({p["attributes"]["innovation_type"] for p in proposals},{"lexical","semantic"})


class ContractTests(unittest.TestCase):
    def test_starters_profiles_and_strict_schema(self):
        for name in ("neologisms","cultural","jargon"):
            self.assertEqual(load_recipe(starter_recipe(name))["id"],name)
        for name in ("fake","glm-deepseek","gemini"):self.assertEqual(load_profile(name)["id"],name)
        for modification in ({"mode":"judge"},{"schema_version":2},{"unexpected":True}):
            recipe=starter_recipe("neologisms");recipe.update(modification)
            with self.assertRaises(ValueError):load_recipe(recipe)
        recipe=starter_recipe("neologisms");recipe["execution"]["budget_usd"]=float("nan")
        with self.assertRaises(ValueError):load_recipe(recipe)

    def test_cost_ranges_differ_for_lengths_scripts_mode_cache(self):
        recipe=starter_recipe("cultural");profile=load_profile("glm-deepseek")
        broad=estimate(recipe,profile,links=10)
        self.assertLess(broad["range_usd"][0],broad["range_usd"][1])
        recipe["mode"]="specialists";specialists=estimate(recipe,profile,links=10)
        self.assertGreater(specialists["range_usd"][1],broad["range_usd"][1])
        cached=estimate(recipe,profile,links=10,cache_fraction=1)
        self.assertEqual(cached["range_usd"],[0,0])
        dense=estimate(recipe,profile,links=10,chars_per_token=1)
        self.assertGreater(dense["range_usd"][1],specialists["range_usd"][1])
        self.assertAlmostEqual(token_cost(profile["models"]["glm"],1000000,1000000),0.65)

    def test_transport_wall_timeout_and_single_service_environment(self):
        from termfinder.process_transport import TransportFailure
        profile=load_profile("glm-deepseek")
        request={"expert":{"model":"glm"},"timeout_seconds":1,"prompt":"fixture prompt","max_output_tokens":128}
        with patch.dict("os.environ",{"FIREWORKS_API_KEY":"synthetic-service-key","UNRELATED_SECRET":"do-not-inherit"}), \
             patch("termfinder.providers.bounded_exchange",side_effect=TransportFailure("request_wall_timeout_outcome_unknown",started=True,retryable=True)) as run:
            with self.assertRaises(ProviderError) as error:HTTPProvider(profile).complete(request)
            self.assertTrue(error.exception.uncertain)
            env=run.call_args.kwargs["env"]
            self.assertNotIn("UNRELATED_SECRET",env)
            self.assertNotIn("synthetic-service-key",str(run.call_args.args))

    def test_transport_receives_window_only_not_complete_source(self):
        from dataclasses import asdict
        from termfinder.process_transport import TransportResult
        profile=load_profile("glm-deepseek")
        request={"expert":{"model":"glm"},"timeout_seconds":1,"prompt":"多语言 fixture window", "max_output_tokens":128,
                 "source":{"text":"大"*21_000_000}}
        with patch.dict("os.environ",{"FIREWORKS_API_KEY":"synthetic-service-key"}), \
             patch("termfinder.providers.bounded_exchange",return_value=TransportResult(json.dumps({"response":asdict(response([]))}).encode(),0)) as run:
            HTTPProvider(profile).complete(request)
            data=json.loads(run.call_args.args[1])
            self.assertEqual(data["request"]["prompt"],request["prompt"])
            self.assertNotIn("source",data["request"])
            self.assertLess(len(run.call_args.args[1]),10000)



if __name__=="__main__":unittest.main()
