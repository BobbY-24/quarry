"""Regression cases for request isolation and durable finalization."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import sqlite3
import unittest
from unittest.mock import patch

from termfinder import Project, FakeProvider, Response
from termfinder.config import starter_recipe
from termfinder.engine import Engine
from termfinder.providers import ProviderError
from termfinder.sources import parse_document


def reply(text):
    return Response(json.dumps({"candidates":[{"expression":"moonstep", "language":"en",
        "sense":"a pause", "context":text,"start":None,"attributes":{},
        "definition_quote":None,"translation":None}],"coverage_complete":True}),30,20,"stop","fake-v1")


class ReliabilityEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.project=Project(Path(self.tmp.name)/"study")
        recipe=starter_recipe("neologisms")
        recipe["execution"]["concurrency"]=2
        recipe["execution"]["resilience"]["min_request_interval_seconds"]=0
        recipe["execution"]["resilience"]["model_concurrency"]=2
        self.project.configure(recipe,"fake")
        for n in range(3):
            text=f"Crew {n} calls a pause a moonstep."
            self.project.add_source(parse_document(text.encode(),"text/plain",f"source-{n}.txt",{"language":"en","community":"Gaming"}))

    def test_poisoned_request_does_not_disable_healthy_requests_same_model(self):
        class Poison(FakeProvider):
            def complete(self,request):
                self.calls.append(request)
                if request["expert"]["model"]=="glm" and "Crew 0" in request["text"]:
                    raise ProviderError("http_422",uncertain=False,retryable=False)
                return reply(request["text"])
        provider=Poison([])
        result=self.project.collect(provider)
        glm=[j for j in self.project.store.all("jobs") if j["expert"]["model"]=="glm"]
        self.assertEqual(sum(j["status"]=="done" for j in glm),2)
        self.assertEqual(sum(j["status"]=="failed" for j in glm),1)
        self.assertFalse(any(h["state"]=="disabled" for h in result["model_health"]))
        self.assertEqual(len(provider.calls),6)

    def test_grounding_failure_retains_cache_and_drains_other_success(self):
        class Delayed(FakeProvider):
            def complete(self,request):
                self.calls.append(request)
                time.sleep(.025 if request["expert"]["model"]=="deepseek" else .005)
                return reply(request["text"])
        provider=Delayed([])
        engine=Engine(self.project,provider)
        accept=engine.accept
        failed=[]
        def interrupted(job,response,**kwargs):
            if not failed:
                failed.append(job["job_id"])
                raise RuntimeError("private payload must never enter diagnostics")
            return accept(job,response,**kwargs)
        with patch.object(engine,"accept",side_effect=interrupted):
            result=engine.run()
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["stop_reason"],"local_processing_failure")
        self.assertIsNotNone(self.project.store.get("cache",failed[0]))
        self.assertEqual(self.project.store.get("jobs",failed[0])["status"],"pending")
        self.assertGreater(self.project.store.count("occurrences"),0)
        self.assertFalse(any(j["status"]=="running" for j in self.project.store.all("jobs")))
        calls=len(provider.calls)
        self.project.resume(provider)
        self.assertEqual(self.project.status()["status"],"complete")
        self.assertEqual(len(provider.calls),6)
        self.assertLess(calls,6)

    def test_executor_rejection_is_not_dispatched_or_billed(self):
        provider=FakeProvider([])
        with patch("termfinder.engine.ThreadPoolExecutor.submit",side_effect=RuntimeError("executor closed")):
            result=self.project.collect(provider)
        self.assertEqual(result["status"],"partial")
        self.assertFalse(provider.calls)
        attempts=self.project.store.all("costs")
        self.assertEqual(len(attempts),1)
        self.assertEqual(attempts[0]["status"],"not_sent")
        self.assertEqual(attempts[0]["request_count"],0)
        self.assertEqual(attempts[0]["settled_usd"],0)
        self.assertEqual(self.project.store.get("jobs",attempts[0]["job_id"])["status"],"pending")

    def test_unknown_usage_has_raw_receipt_before_grounding(self):
        provider=FakeProvider([], [Response(reply("Crew 0 calls a pause a moonstep.").text,None,None,"stop","fake-v1")])
        engine=Engine(self.project,provider)
        with patch.object(engine,"accept",side_effect=RuntimeError("grounding failed")):
            result=engine.run(max_jobs=1)
        attempts=self.project.store.all("costs")
        self.assertEqual(attempts[0]["status"],"uncertain")
        self.assertIsNotNone(self.project.store.get("cache",attempts[0]["job_id"]))
        self.assertEqual(result["status"],"partial")

    def test_cached_evidence_replays_while_its_model_circuit_is_disabled(self):
        provider=FakeProvider([])
        provider.complete=lambda request: (provider.calls.append(request) or reply(request["text"]))
        engine=Engine(self.project,provider)
        with patch.object(engine,"accept",side_effect=RuntimeError("synthetic grounding failure")):
            engine.run(max_jobs=1)
        cached=self.project.store.all("cache")[0]
        job=self.project.store.get("jobs",cached["key"])
        engine._disable(job,"synthetic global model failure")
        alias=job["expert"]["model"]
        before=sum(request["expert"]["model"]==alias for request in provider.calls)
        self.project.resume(provider)
        self.assertEqual(sum(request["expert"]["model"]==alias for request in provider.calls),before)
        self.assertEqual(self.project.store.get("jobs",job["job_id"])["status"],"done")
        self.assertTrue(any(provenance["job_id"]==job["job_id"] for occurrence in self.project.store.all("occurrences") for provenance in occurrence["provenance"]))

    def test_shared_quota_reserves_registered_and_utf8_fallback_input_tokens(self):
        from termfinder.quotas import QuotaLimits
        self.project.configure_quota(Path(self.tmp.name)/"token-quota.sqlite3","synthetic-token-account",QuotaLimits())
        engine=Engine(self.project,FakeProvider([]))
        engine.deadline=engine.clock.monotonic()+60
        jobs=[self.project.store.get("jobs",key) for key in engine.prepare()]
        job=jobs[0]
        job["token_admission"]={"admitted":True,"input_tokens":777}
        with patch.object(engine.quota,"try_acquire",wraps=engine.quota.try_acquire) as acquire:
            attempt,reason=engine.admit(job)
            self.assertIsNone(reason)
            self.assertEqual(acquire.call_args.args[3],777+job["max_output_tokens"])
        engine.not_sent(job,attempt,"fixture_never_invoked")
        fallback=jobs[1]
        fallback.pop("token_admission",None)
        with patch.object(engine,"request",return_value={"prompt":"月步🙂"*10}),patch.object(engine.quota,"try_acquire",wraps=engine.quota.try_acquire) as acquire:
            attempt,reason=engine.admit(fallback)
            self.assertIsNone(reason)
            self.assertEqual(acquire.call_args.args[3],len(("月步🙂"*10).encode("utf-8"))+fallback["model"].get("prompt_overhead_tokens",256)+fallback["max_output_tokens"])
        engine.not_sent(fallback,attempt,"fixture_never_invoked")

    def test_disabled_model_relinquishes_queued_head_for_healthy_alias(self):
        from termfinder.quotas import QuotaLimits
        self.project.configure_quota(Path(self.tmp.name)/"quota.sqlite3", "fixture-account",
            QuotaLimits(max_inflight=1, requests_per_window=1000, tokens_per_window=1000000))
        engine=Engine(self.project,FakeProvider([]))
        engine.deadline=engine.clock.monotonic()+60
        jobs=[self.project.store.get("jobs",key) for key in engine.prepare()]
        glm=[job for job in jobs if job["expert"]["model"]=="glm"]
        deepseek=next(job for job in jobs if job["expert"]["model"]=="deepseek")
        held,reason=engine.admit(glm[0])
        self.assertIsNotNone(held)
        self.assertIsNone(reason)
        self.assertEqual(engine.admit(glm[1])[1],"quota_account_inflight_limit")
        self.assertEqual(engine.admit(deepseek)[1],"quota_account_inflight_limit")
        engine.not_sent(glm[0],held,"fixture_never_invoked")
        engine._disable(glm[1],"fixture_model_disabled")
        admitted,reason=engine.admit(deepseek)
        self.assertIsNotNone(admitted,"Disabled model's queued head must not block a healthy alias")
        self.assertIsNone(reason)
        engine.not_sent(deepseek,admitted,"fixture_never_invoked")

    def test_unknown_request_time_reservations_survive_resume(self):
        recipe=deepcopy(self.project.recipe)
        recipe["execution"].update(concurrency=1,timeout_seconds=2,deadline_seconds=3)
        recipe["execution"]["resilience"].update(automatic_uncertain_retries=True,delays_seconds=[0],jitter_fraction=0)
        profile=deepcopy(self.project.profile);profile["broad"]=[e for e in profile["broad"] if e["model"]=="glm"]
        self.project.configure(recipe,profile)
        class Lost(FakeProvider):
            def complete(self,request):
                self.calls.append(request)
                raise ProviderError("accepted_connection_lost",uncertain=True,retryable=True)
        provider=Lost([])
        result=self.project.collect(provider)
        self.assertEqual(result["stop_reason"],"cumulative_request_time_budget_exhausted")
        self.assertEqual(len(provider.calls),2)
        self.assertEqual(sum(a["reserved_seconds"] for a in self.project.store.all("costs")),3)
        self.project.resume(provider)
        self.assertEqual(len(provider.calls),2)

    def test_journal_intent_failure_never_starts_provider(self):
        class Unavailable:
            def reconcile(self,*args,**kwargs):return {}
            def intent(self,*args):raise OSError("shared storage unavailable")
        self.project._dispatch_journal=Unavailable()
        provider=FakeProvider([])
        result=self.project.collect(provider)
        self.assertFalse(provider.calls)
        self.assertEqual(result["status"],"partial")
        self.assertEqual(self.project.store.all("costs")[0]["status"],"not_sent")
        self.assertEqual(self.project.store.all("costs")[0]["request_count"],0)

    def test_terminal_journal_failure_keeps_returned_evidence(self):
        class Unavailable:
            def reconcile(self,*args,**kwargs):return {}
            def intent(self,*args):pass
            def terminal(self,*args):raise OSError("shared storage unavailable")
        self.project._dispatch_journal=Unavailable()
        class Success(FakeProvider):
            def complete(self,request):
                self.calls.append(request);return reply(request["text"])
        result=self.project.collect(Success([]))
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["stop_reason"],"local_accounting_receipt_failure")
        self.assertGreater(self.project.store.count("occurrences"),0)
        self.assertTrue(all(a["status"]=="settled" for a in self.project.store.all("costs")))

    def test_cache_storage_failure_preserves_attempt_without_false_rejection(self):
        provider=FakeProvider([], [reply("Crew 0 calls a pause a moonstep.")])
        original=self.project.store.put
        def disk_full(table,*args,**kwargs):
            if table=="cache":raise sqlite3.OperationalError("synthetic private disk-full payload")
            return original(table,*args,**kwargs)
        with patch.object(self.project.store,"put",side_effect=disk_full):
            result=self.project.collect(provider,max_jobs=1)
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["stop_reason"],"local_storage_failure")
        self.assertEqual(self.project.store.all("costs")[0]["status"],"uncertain")
        self.assertNotIn("private disk-full",json.dumps(self.project.doctor()))

if __name__=="__main__":unittest.main()
