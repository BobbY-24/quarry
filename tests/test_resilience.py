"""Offline outage and scale contracts; no network, credentials or real waits."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from email.message import Message
from urllib.error import HTTPError, URLError
import ssl
import subprocess

from termfinder import Project, FakeProvider, Response
from termfinder.config import starter_recipe, load_recipe
from termfinder.engine import Engine
from termfinder.providers import ProviderError, HTTPProvider
from termfinder.resilience import DEFAULT_RESILIENCE, retry_delay, parse_retry_after
from termfinder.sources import parse_document


class Clock:
    def __init__(self):
        self.value = 1_800_000_000.0
        self.on_sleep = None
    def time(self): return self.value
    def monotonic(self): return self.value
    def sleep(self, delay):
        self.value += max(0.001, delay)
        if self.on_sleep: self.on_sleep()


class Flaky(FakeProvider):
    def __init__(self, clock, fail=5, error=None):
        super().__init__([], [])
        self.clock, self.fail, self.events = clock, fail, []
        self.error = error or ProviderError("transport_outcome_unknown", uncertain=True, retryable=True)
    def complete(self, request):
        self.calls.append(request["job_id"])
        alias = request["expert"]["model"]
        self.events.append((alias, self.clock.time(), request["job_id"]))
        if alias == "glm" and self.fail:
            self.fail -= 1
            raise self.error
        text = request["text"]
        proposals = [{"expression":"moonstep", "language":"en", "sense":"a pause",
                      "context":text, "start":None, "attributes":{}, "definition_quote":None,
                      "translation":None}] if "moonstep" in text else []
        return Response(json.dumps({"candidates":proposals,"coverage_complete":True}), 20, 10, "stop", "offline-v2")


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name)/"study")
        self.recipe = starter_recipe("neologisms")
        self.recipe["execution"].update(concurrency=2, max_retries=4,
            resilience=deepcopy(DEFAULT_RESILIENCE))
        self.recipe["execution"]["resilience"].update(jitter_fraction=0, min_request_interval_seconds=0)
        self.project.configure(self.recipe, "fake")
        self.clock = Clock()

    def source(self, number=0):
        return self.project.add_source(parse_document(
            f"Source {number} calls a pause moonstep.".encode(), "text/plain", f"fixture-{number}.txt",
            {"language":"en", "community":"Gaming", "constraints":{"content_origin":"synthetic_fixture"}}))

    def run_engine(self, provider, **kwargs):
        return Engine(self.project, provider, clock=self.clock, random=lambda:0).run(**kwargs)

    def test_backoff_jitter_retry_after_and_invalid_headers(self):
        self.assertEqual([retry_delay(DEFAULT_RESILIENCE, n, random=lambda:0) for n in range(1,5)], [30,120,240,480])
        self.assertEqual(retry_delay(DEFAULT_RESILIENCE, 1, retry_after=600, random=lambda:0), 600)
        self.assertGreaterEqual(retry_delay(DEFAULT_RESILIENCE, 1, random=lambda:1), 30)
        self.assertLessEqual(retry_delay(DEFAULT_RESILIENCE, 1, random=lambda:1), 36)
        self.assertEqual(parse_retry_after("120", now=0), 120)
        self.assertEqual(parse_retry_after("Thu, 01 Jan 1970 00:02:00 GMT", now=0), 120)
        for invalid in (None, "nonsense", "nan", "-2", "inf"):
            self.assertIsNone(parse_retry_after(invalid, now=0))

    def test_five_attempts_disable_only_failed_model_and_preserve_union(self):
        for n in range(6): self.source(n)
        provider = Flaky(self.clock)
        result = self.run_engine(provider)
        counts = Counter(alias for alias, _, _ in provider.events)
        self.assertEqual(counts["glm"], 5)
        self.assertEqual(counts["deepseek"], 6)
        timestamps = [at for alias, at, _ in provider.events if alias == "glm"]
        self.assertEqual([round(b-a) for a,b in zip(timestamps,timestamps[1:])], [30,120,240,480])
        self.assertEqual(len(self.project.inventory()["records"]), 1)
        self.assertTrue(result["degraded"])
        self.assertEqual(result["healthy_models"], ["deepseek"])
        self.assertEqual(sum(c["status"] == "uncertain" for c in self.project.inventory()["costs"]), 5)
        self.assertLess(next(at for alias,at,_ in provider.events if alias == "deepseek"), timestamps[-1])
        self.assertFalse(result["coverage"]["partial"] == 0)

    def test_successful_probe_reopens_model_and_resume_does_not_repeat_success(self):
        for n in range(3): self.source(n)
        provider = Flaky(self.clock, fail=2)
        first = self.run_engine(provider)
        self.assertFalse(first["degraded"])
        self.assertEqual(first["coverage"]["partial"], 0)
        count = len(provider.calls)
        self.run_engine(provider)
        self.assertEqual(len(provider.calls), count)
        self.assertEqual(sum(c["status"] == "uncertain" for c in self.project.inventory()["costs"]), 2)

    def test_disabled_circuit_persists_across_reopen_until_explicit_reset(self):
        self.source()
        provider = Flaky(self.clock)
        self.run_engine(provider)
        count = len(provider.calls)
        self.project = Project(self.project.path)
        self.run_engine(provider)
        self.assertEqual(len(provider.calls), count)
        self.project.reset_model("glm")
        self.run_engine(provider)
        self.assertGreater(len(provider.calls), count)
        self.assertEqual(self.project.status()["coverage"]["partial"], 0)

    def test_cancel_during_cooldown_is_prompt_and_resume_preserves_schedule(self):
        self.source()
        provider = Flaky(self.clock, fail=1)
        self.clock.on_sleep = self.project.cancel
        self.run_engine(provider)
        glm_times = [at for alias,at,_ in provider.events if alias == "glm"]
        self.assertEqual(len(glm_times), 1)
        self.clock.on_sleep = None
        self.project.store.setting("cancel_requested", False)
        self.project = Project(self.project.path)
        self.run_engine(provider)
        glm_times = [at for alias,at,_ in provider.events if alias == "glm"]
        self.assertGreaterEqual(glm_times[1] - glm_times[0], 30)

    def test_permanent_credential_failure_is_not_retried(self):
        for n in range(4): self.source(n)
        provider = Flaky(self.clock, fail=100, error=ProviderError("http_401"))
        result = self.run_engine(provider)
        self.assertEqual(sum(alias == "glm" for alias,_,_ in provider.events), 1)
        self.assertEqual(sum(alias == "deepseek" for alias,_,_ in provider.events), 4)
        self.assertTrue(result["degraded"])
        self.project.reset_model("glm");provider.fail=0
        self.run_engine(provider)
        self.assertEqual(self.project.status()["coverage"]["partial"],0)

    def test_request_budget_is_preserved_across_automatic_retry_and_resume(self):
        self.source()
        recipe = deepcopy(self.recipe)
        recipe["execution"]["max_calls"] = 2
        self.project.configure(recipe, "fake")
        provider = Flaky(self.clock)
        self.run_engine(provider)
        self.run_engine(provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(self.project.status()["stop_reason"], "request_budget_exhausted")

    def test_schema_allows_large_finite_run_and_rejects_unbounded_policy(self):
        recipe = deepcopy(self.recipe)
        recipe["execution"].update(max_calls=1_000_000, deadline_seconds=604800, timeout_seconds=180)
        self.assertEqual(load_recipe(recipe)["execution"]["max_calls"], 1_000_000)
        for key,value in (("max_calls",float("inf")),("deadline_seconds",0), ("max_retries",100)):
            invalid=deepcopy(recipe); invalid["execution"][key]=value
            with self.assertRaises(ValueError): load_recipe(invalid)

    def test_both_models_unavailable_finish_partial_without_spin(self):
        self.source()
        provider=FakeProvider([],responses=[ProviderError("http_503",retryable=True,uncertain=True) for _ in range(10)])
        result=self.run_engine(provider)
        self.assertEqual(len(provider.calls),10)
        self.assertEqual(result["healthy_models"],[])
        self.assertEqual(result["stop_reason"],"model_degraded_after_retry_exhaustion")
        self.assertEqual(result["coverage"]["complete"],0)

    def test_retry_budget_stops_retrying_model_without_stopping_healthy_work(self):
        for n in range(6): self.source(n)
        recipe=deepcopy(self.recipe);recipe["execution"]["resilience"]["max_retry_calls"]=1
        self.project.configure(recipe,"fake")
        provider=Flaky(self.clock)
        result=self.run_engine(provider)
        self.assertEqual(Counter(a for a,_,_ in provider.events),{"glm":2,"deepseek":6})
        self.assertTrue(any(h["reason"] == "aggregate_retry_budget_exhausted" for h in result["model_health"]))

    def test_budget_holds_all_unknown_reserves_and_never_retries_after_cap(self):
        self.source()
        from termfinder.costs import reserve_cost
        recipe=deepcopy(self.recipe)
        profile=deepcopy(self.project.profile)
        for model in profile["models"].values(): model.update(input_per_million=1,output_per_million=1)
        reserve=sum(reserve_cost(m,recipe["execution"]["max_output_tokens"]) for m in profile["models"].values())
        recipe["execution"]["budget_usd"]=reserve
        self.project.configure(recipe,profile)
        provider=Flaky(self.clock)
        self.run_engine(provider)
        unknown=[c for c in self.project.store.all("costs") if c["status"] == "uncertain"]
        self.assertTrue(unknown)
        self.assertTrue(all("settled_usd" not in c for c in unknown))
        self.assertEqual(self.project.status()["stop_reason"],"spending_budget_reservation_exhausted")
        calls=len(provider.calls);self.run_engine(provider);self.assertEqual(len(provider.calls),calls)

    def test_interrupted_dispatch_is_recovered_as_unknown_not_free(self):
        self.source()
        provider=Flaky(self.clock,fail=0)
        engine=Engine(self.project,provider,clock=self.clock,random=lambda:0)
        root=engine.prepare()[0];job=self.project.store.get("jobs",root)
        attempt,_=engine.admit(job)
        self.project=Project(self.project.path)
        self.run_engine(provider)
        recovered=self.project.store.get("costs",attempt["attempt_id"])
        self.assertEqual(recovered["status"],"uncertain")
        self.assertNotIn("settled_usd",recovered)
        self.assertEqual(self.project.status()["coverage"]["partial"],0)

    def test_cached_probe_reopens_without_another_request(self):
        from dataclasses import asdict
        self.source()
        provider=Flaky(self.clock,fail=1)
        engine=Engine(self.project,provider,clock=self.clock,random=lambda:0)
        roots=engine.prepare()
        root=next(k for k in roots if self.project.store.get("jobs",k)["expert"]["model"] == "glm")
        job=self.project.store.get("jobs",root);attempt,_=engine.admit(job)
        engine.failure(job,attempt,provider.error)
        request=engine.request(job);provider.fail=0
        response=provider.complete(request)
        self.project.store.put("cache",root,{"key":root,"response":asdict(response)})
        before=len(provider.calls)
        self.run_engine(provider)
        self.assertEqual(len(provider.calls),before+1) # healthy other model only
        self.assertEqual(self.project.status()["coverage"]["partial"],0)

    def test_mode_switch_during_cooldown_cannot_leave_orphaned_probe(self):
        self.source()
        provider=Flaky(self.clock,fail=1)
        self.clock.on_sleep=self.project.cancel
        self.run_engine(provider)
        self.clock.on_sleep=None;self.project.store.setting("cancel_requested",False)
        recipe=deepcopy(self.recipe);recipe["mode"]="specialists"
        self.project.configure(recipe,"fake")
        self.run_engine(provider)
        self.assertEqual(self.project.status()["coverage"]["partial"],0)

    def test_payload_too_large_splits_window_without_disabling_model(self):
        self.source(10000000)
        provider=FakeProvider([],responses=[ProviderError("http_413")])
        result=self.run_engine(provider)
        self.assertFalse(result["degraded"])
        self.assertEqual(result["coverage"]["partial"],0)
        self.assertTrue(any(j["reason"] == "payload_too_large_split_recovery" for j in self.project.store.all("jobs")))

    def test_browser_pages_and_excerpts_are_bounded_and_annotations_remain_reversible(self):
        for n in range(80): self.source(n)
        self.run_engine(Flaky(self.clock,fail=0))
        record=self.project.inventory()["records"][0]
        annotation=self.project.annotate(record["record_id"],"approved","human test")
        page=self.project.page_inventory(record_id=record["record_id"],limit=20,evidence_offset=20)
        self.assertEqual(len(page["occurrences"]),20)
        self.assertEqual(page["page"]["evidence_total"],80)
        self.assertTrue(all("text" not in s and "blocks" not in s for s in page["sources"]))
        for e in page["occurrences"]:
            span=e["inspection_excerpt"]
            self.assertEqual(span["text"][e["start"]-span["start"]:e["end"]-span["start"]],"moonstep")
        self.project.undo_annotation(annotation)
        self.assertEqual(self.project.page_inventory()["records"][0]["review_status"],"unreviewed")
        with self.assertRaises(ValueError): self.project.page_inventory(limit=101)
        empty=self.project.page_inventory(query="no-matching-record",record_id=record["record_id"])
        self.assertEqual(empty["records"],[])
        self.assertEqual(empty["selected_record"]["record_id"],record["record_id"])

    def test_large_run_upgrade_retains_money_scope_and_settled_cache(self):
        self.source();provider=Flaky(self.clock,fail=0)
        self.run_engine(provider);before=len(provider.calls)
        old=deepcopy(self.project.recipe)
        old["execution"].pop("resilience");old["execution"].update(max_calls=100,deadline_seconds=60)
        self.project.configure(old,"fake");self.project.configure_large_run()
        self.assertEqual(self.project.recipe["execution"]["budget_usd"],old["execution"]["budget_usd"])
        self.assertEqual(self.project.recipe["source_scope"],old["source_scope"])
        self.run_engine(provider);self.assertEqual(len(provider.calls),before)

    def test_transport_timeout_and_retry_after_are_safe_and_no_sdk_retry_occurs(self):
        from termfinder.config import load_profile
        profile=load_profile("glm-deepseek")
        credential=profile["providers"][profile["models"]["glm"]["provider"]]["credential_env"]
        request={"expert":{"model":"glm"},"prompt":"synthetic source only","timeout_seconds":1,"max_output_tokens":10}
        with patch.dict("os.environ",{credential:"synthetic-test-placeholder"},clear=True), patch("termfinder.providers.subprocess.run",side_effect=subprocess.TimeoutExpired("worker",1)) as call:
            with self.assertRaises(ProviderError) as raised: HTTPProvider(profile).complete(request)
            self.assertTrue(raised.exception.uncertain and raised.exception.retryable)
            self.assertEqual(call.call_count,1)
        headers=Message();headers["Retry-After"]="120"
        for failure,reason,retry in [(HTTPError("https://synthetic.invalid",429,"",headers,None),"http_429",True),
                                    (URLError(ssl.SSLCertVerificationError("test")),"tls_identity_verification_failed",False)]:
            with patch.dict("os.environ",{credential:"synthetic-test-placeholder"},clear=True), patch("termfinder.providers.build_opener") as build:
                build.return_value.open.side_effect=failure
                with self.assertRaises(ProviderError) as raised: HTTPProvider(profile,_direct=True).complete(request)
                self.assertEqual(raised.exception.reason,reason);self.assertEqual(raised.exception.retryable,retry)
                if retry:self.assertEqual(raised.exception.retry_after_seconds,120)
        for invalid in ("120",float("nan"),float("inf"),-1):
            self.assertIsNone(ProviderError("test",retry_after_seconds=invalid).retry_after_seconds)

    def test_server_delay_above_finite_policy_disables_without_early_retry(self):
        self.source()
        provider=Flaky(self.clock,fail=100,error=ProviderError("http_429",retryable=True,retry_after_seconds=9999999))
        result=self.run_engine(provider)
        self.assertEqual(Counter(a for a,_,_ in provider.events),{"glm":1,"deepseek":1})
        self.assertEqual(next(h for h in result["model_health"] if h["model_alias"] == "glm")["reason"],"server_retry_after_exceeds_policy")

    def test_single_model_failure_never_claims_successful_fallback(self):
        self.source();self.project.configure(self.recipe,"gemini")
        provider=FakeProvider([],responses=[ProviderError("transport_outcome_unknown",retryable=True,uncertain=True) for _ in range(5)])
        result=self.run_engine(provider)
        self.assertEqual(len(provider.calls),5)
        self.assertEqual(result["healthy_models"],[])
        self.assertEqual(result["status"],"partial")

    def test_low_disk_prevents_dispatch_and_consistent_backup_contains_saved_state(self):
        self.source();provider=Flaky(self.clock,fail=0)
        with patch("termfinder.engine.shutil.disk_usage",return_value=type("Usage",(),{"free":0})()):
            result=self.run_engine(provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(result["stop_reason"],"local_disk_reserve_exhausted")
        self.run_engine(provider)
        version=self.project.snapshot("backup-test")
        backup=Path(self.temp.name)/"restored"/"project.sqlite3"
        self.project.store.backup(backup)
        restored=Project(backup.parent)
        self.assertEqual(restored.dataset(version),self.project.dataset(version))
        self.assertEqual(restored.status()["counts"],self.project.status()["counts"])
        with self.assertRaises(FileExistsError): self.project.store.backup(backup)

    def test_aliases_with_identical_model_configurations_cannot_dispatch_each_others_jobs(self):
        for n in range(3): self.source(n)
        profile=deepcopy(self.project.profile)
        profile["models"]["deepseek"]=deepcopy(profile["models"]["glm"])
        self.project.configure(self.recipe,profile)
        provider=Flaky(self.clock)
        result=self.run_engine(provider)
        self.assertEqual(Counter(a for a,_,_ in provider.events),{"glm":5,"deepseek":3})
        self.assertEqual(result["healthy_models"],["deepseek"])


if __name__ == "__main__": unittest.main()
