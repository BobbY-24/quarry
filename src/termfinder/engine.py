"""Bounded persistent jobs, conservative reservations and grounded union."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict
from collections import OrderedDict
import time
import uuid
import shutil
import sqlite3
import sys
import threading

from .config import experts, STAGES
from .costs import reserve_cost, token_cost, window_ranges
from .grounding import ground, parse_response
from .prompts import build_prompt, VERSION
from .prompts import manifest as prompt_manifest
from .providers import ProviderError, Response
from .store import digest, ident, now
from .resilience import retry_delay, cluster_execution
from .runtime import PromptTokenizer, runtime_manifest, validate_runtime
from .token_windows import token_admission, planned_windows

PROCESSING_VERSION = "grounding-2"
EXECUTION_VERSION = "recovery-2"
MAX_PLANNED_JOBS = 100000
SHUTDOWN_GRACE_SECONDS = 30
QUEUE_WAIT_SECONDS = 5
QUOTA_RECEIPT_VERSION = "quota-receipt-1"


class IndexedJobs:
    def __init__(self,store,run_id):self.store,self.run_id=store,run_id
    def __contains__(self,key):return self.store.run_contains(self.run_id,key)
    def update(self,keys):self.store.register_jobs(self.run_id,keys)


class IndexedRoots:
    def __init__(self,store,run_id):self.store,self.run_id=store,run_id
    def __len__(self):return self.store.run_root_count(self.run_id)
    def __iter__(self):
        for job in self.store.iter_run_jobs(self.run_id,root=True):yield job["job_id"]


def policy_hash(recipe):
    return digest({k:v for k,v in recipe.items() if k not in {
        "mode", "model_profile", "specialist_lenses", "discovery", "execution", "exports"}})


class SourceCache:
    """Bound source-text residency; the durable database remains authoritative."""
    def __init__(self, store, limit=4, characters=16000000):
        self.store, self.limit, self.cache = store, limit, OrderedDict()
        self.characters = characters
    def __getitem__(self, key):
        if key not in self.cache:
            value = self.store.get("sources", key)
            if value is None: raise KeyError(key)
            self.cache[key] = value
        self.cache.move_to_end(key)
        while len(self.cache) > self.limit: self.cache.popitem(last=False)
        while len(self.cache) > 1 and sum(len(s["text"]) for s in self.cache.values()) > self.characters:
            self.cache.popitem(last=False)
        return self.cache[key]
    def values(self):
        return self.store.iter_rows("sources",batch_size=1)


class Engine:
    def __init__(self, project, provider, *, clock=None, random=None, tokenizers=None):
        self.project, self.store = project, project.store
        self.recipe, self.profile, self.provider = project.recipe, project.profile, provider
        tuning = self.store.read_setting("cluster_throughput")
        self.execution = (cluster_execution(self.recipe["execution"], **tuning)
                          if tuning else self.recipe["execution"])
        self.tokenizers = dict(tokenizers or {})
        if set(self.tokenizers) - set(self.profile["models"]) or any(
                not isinstance(t, PromptTokenizer) for t in self.tokenizers.values()):
            raise ValueError("register trusted prompt tokenizers by configured model alias")
        self.resilience = self.execution.get("resilience")
        self.clock, self.random = clock or time, random
        self.policy = policy_hash(self.recipe)
        self.provider_identity = getattr(provider, "cache_identity", None) or (
            "paid-transport-v1" if getattr(provider, "paid", False) else "offline-fixture-v1")
        self.budget_scope = "live" if getattr(provider, "paid", False) else "simulation:" + self.provider_identity
        self.run_id = "run_" + uuid.uuid4().hex
        self.expert_map = {e["id"]: e for e in experts(self.recipe, self.profile)}
        self.source_map = SourceCache(self.store)
        cluster = self.store.read_setting("cluster_execution")
        self.cluster_runtimes = {}
        if cluster:
            if not isinstance(cluster, dict) or not isinstance(cluster.get("runtime"), dict) or not isinstance(cluster.get("model_artifacts"), list):
                raise ValueError("Invalid trusted cluster runtime declaration")
            # Bind artifact/runtime identities only: resuming on a new job or
            # changing GPU counts must not invalidate completed extraction.
            for alias in self.profile["models"]:
                artifacts = [a for a in cluster["model_artifacts"] if isinstance(a, dict) and a.get("model_alias") == alias]
                if len(artifacts) != 1:
                    raise ValueError("Cluster runtime must declare each model alias once")
                artifact = artifacts[0]
                normalized = validate_runtime({"checkpoint_sha256": artifact.get("sha256"),
                    "model_revision": artifact.get("checkpoint_id"), "quantization": artifact.get("quantization"),
                    "runtime_name": cluster["runtime"].get("runtime_id")})
                if not normalized["checkpoint_sha256"] or not normalized["model_revision"] or not normalized["runtime_name"]:
                    raise ValueError("Cluster runtime artifact identity is incomplete")
                configured_hash = self.profile["models"][alias].get("runtime", {}).get("checkpoint_sha256")
                if configured_hash and configured_hash != normalized["checkpoint_sha256"]:
                    raise ValueError("Cluster checkpoint declaration differs from the model profile")
                python_hash = cluster["runtime"].get("python_sha256")
                if not isinstance(python_hash, str) or len(python_hash) != 64 or any(c not in "0123456789abcdef" for c in python_hash):
                    raise ValueError("Cluster runtime requires the reviewed Python artifact hash")
                self.cluster_runtimes[alias] = {"origin": "operator_declared", "model_alias": alias,
                    "checkpoint_sha256": normalized["checkpoint_sha256"], "model_revision": normalized["model_revision"],
                    "quantization": normalized["quantization"], "quantization_reason": None if normalized["quantization"] else "not_declared_by_operator",
                    "runtime_id": normalized["runtime_name"], "python_sha256": python_hash,
                    "attestation": "operator_declaration_not_remote_endpoint_attestation"}
                server = cluster.get("server")
                resources = cluster.get("resources")
                declared_server = resources.get("server") if isinstance(resources, dict) else None
                if server is not None and not isinstance(server, dict) or declared_server is not None and not isinstance(declared_server, dict):
                    raise ValueError("Invalid trusted serving runtime declaration")
                # Keep the identity stable before and after readiness. Owned
                # serving's fixed policies are declared before launch; the
                # receipt confirms them without incorporating ports, timing,
                # allocation IDs or GPU counts into response-cache keys.
                selected = declared_server or server
                if selected and selected.get("model_alias") == alias:
                    from .serving import VERSION_PATTERN
                    package_version = selected.get("package_version")
                    if (selected.get("adapter") != "vllm" or not isinstance(package_version, str)
                            or len(package_version) > 64 or not VERSION_PATTERN.fullmatch(package_version)):
                        raise ValueError("Invalid trusted vLLM package identity")
                    serving_identity = {"adapter": "vllm", "package_version": package_version,
                        "served_model_name": self.profile["models"][alias]["model"],
                        "load_format": "safetensors", "generation_config": "vllm",
                        "distributed_executor_backend": "mp", "plugin_autoload": "disabled",
                        "remote_model_code": "disabled"}
                    if server is not None:
                        if server.get("model_alias", alias) != alias or any(
                                name in server and server[name] != expected
                                for name, expected in serving_identity.items()):
                            raise ValueError("Serving receipt differs from the trusted runtime declaration")
                    self.cluster_runtimes[alias]["owned_serving"] = serving_identity
        self.model_keys = {alias: ident("model", {"alias":alias,"model":model,
            "provider":self.profile["providers"][model["provider"]],
            "policy":self.policy, "scope":self.budget_scope,
            **({"declared_cluster_runtime": self.cluster_runtimes[alias]} if alias in self.cluster_runtimes else {})})
            for alias,model in self.profile["models"].items()}
        self.health = self.store.read_setting("model_circuits") or {}
        self.ledger = None
        self.journal = getattr(project,"_dispatch_journal",None)
        self.quota = getattr(project,"_quota_coordinator",None)
        self.quota_leases = {}
        self.quota_waiters = set()
        self.quota_wait_jobs={}
        self.queue_wait_deadline=None
        self.cancel_event = threading.Event()
        self.storage_failed = False

    def incident(self, category, *, job=None, attempt=None):
        # Fixed categories and identifiers only; never exception text/payloads.
        row={"incident_id":"incident_"+uuid.uuid4().hex,"run_id":self.run_id,
             "category":category,"scope":"local","created_at":now(),
             "job_id":job.get("job_id") if job else None,
             "attempt_id":attempt.get("attempt_id") if attempt else None,
             "status":"unresolved","recovery_action":"inspect_and_resume_cached_work"}
        try:self.store.put("incidents",row["incident_id"],row)
        except (OSError,sqlite3.Error,RuntimeError):
            self.storage_failed=True
            print("Quarry incident not saved; inspect last durable attempts after storage or diagnostic-capacity recovery.",file=sys.stderr)

    def job(self, source, expert, start, end, *, depth=0, parent=None):
        model = self.profile["models"][expert["model"]]
        output = self.execution["recovery_output_tokens"] if depth else self.execution["max_output_tokens"]
        if output > model["output_token_ceiling"]:
            raise ValueError("configured output limit exceeds model ceiling")
        text = source["text"][start:end]
        prompt = build_prompt(self.recipe, expert, text, source)
        signature = {"source_text_sha256": source["text_sha256"], "source_id": source["source_id"],
            "parser_version": source["parser_version"], "policy": self.policy, "prompt_version": VERSION,
            "prompt_sha256": digest(prompt), "expert": expert, "model": model,
            "provider": self.profile["providers"][model["provider"]], "transport": self.provider_identity,
            "start": start, "end": end, "max_output_tokens": output}
        admission = None
        if "context_limit_tokens" in model or expert["model"] in self.tokenizers:
            admission = token_admission(model, prompt, output,
                                       tokenizer=self.tokenizers.get(expert["model"]))
            signature["token_admission"] = admission
        cluster_runtime = self.cluster_runtimes.get(expert["model"])
        if cluster_runtime is not None:
            signature["declared_cluster_runtime"] = cluster_runtime
        key = ident("job", signature)
        existing = self.store.get("jobs", key)
        if existing:
            if existing.get("model_key") != self.model_keys[expert["model"]]:
                existing["model_key"] = self.model_keys[expert["model"]]
                self.store.put("jobs", key, existing)
            cache=self.store.get("cache",key)
            if existing.get("processing_version","grounding-1")!=PROCESSING_VERSION and cache and existing["status"] in {"done","partial","split"}:
                existing.update(status="pending",reason="cached_response_processing_upgrade",processing_version=PROCESSING_VERSION)
                self.store.put("jobs",key,existing)
            return existing
        record = {"job_id": key, "source_id": source["source_id"], "expert": expert,
            "record_type": self.recipe.get("data_type", "term"),
            "model": model, "signature": signature, "policy_hash": self.policy, "start": start,
            "end": end, "depth": depth, "parent": parent, "children": [], "status": "pending",
            "reason": "not_dispatched", "attempts": 0, "created_at": now(), "run_id": None,
            "prompt_sha256": digest(prompt), "coverage_complete": False, "max_output_tokens": output,
            "transport_identity": self.provider_identity, "model_key":self.model_keys[expert["model"]]}
        record["processing_version"]=PROCESSING_VERSION
        if admission is not None:
            record["token_admission"] = admission
        record["runtime"] = runtime_manifest(model)
        record["declared_cluster_runtime"] = cluster_runtime
        record["declared_cluster_runtime_reason"] = None if cluster_runtime else "not_running_with_cluster_declaration"
        record["request_decoding"] = {"temperature": 0, "max_output_tokens": output,
                                      "thinking_budget": model["thinking_budget"],
                                      "origin": "quarry_transport_configuration"}
        self.store.put("jobs", key, record)
        return record

    def prepare(self, *, streaming=False):
        if not hasattr(self, "deadline"):
            self.deadline = self.clock.monotonic() + self.execution["deadline_seconds"]
        self.store.prune_run_index(self.run_id)
        roots=IndexedRoots(self.store,self.run_id)
        root_count=0
        self.planning_complete = True
        for source in self.source_map.values():
            if self.project.source_exclusion(source) is not None:
                continue
            for expert in self.expert_map.values():
                if "*" not in expert["communities"] and source.get("community") not in expert["communities"]:
                    continue
                model = self.profile["models"][expert["model"]]
                if "context_limit_tokens" in model or expert["model"] in self.tokenizers:
                    windows = planned_windows(source["text"], self.execution, model,
                        lambda text: build_prompt(self.recipe, expert, text, source),
                        tokenizer=self.tokenizers.get(expert["model"]))
                else:
                    windows = ((s, e, None) for s, e in window_ranges(len(source["text"]), self.execution))
                for start, end, admission in windows:
                    if self.store.read_setting("cancel_requested") or self.clock.monotonic() >= self.deadline:
                        self.planning_complete = False
                        break
                    if root_count >= min(MAX_PLANNED_JOBS,self.execution["max_calls"] if self.resilience else MAX_PLANNED_JOBS):
                        self.planning_complete = False
                        break
                    record = self.job(source, expert, start, end)
                    if admission is not None and not admission["admitted"] and record["status"] == "pending":
                        record.update(status="partial", reason=admission["blocked_reason"], coverage_complete=False)
                        self.store.put("jobs", record["job_id"], record)
                        self.audit(record, record["reason"])
                    self.store.register_jobs(self.run_id,[record["job_id"]],root=True)
                    root_count+=1
                if not self.planning_complete:
                    break
            if not self.planning_complete: break
            if self.store.read_setting("cancel_requested"):
                self.planning_complete = False
                break
        self.current_jobs=IndexedJobs(self.store,self.run_id)
        def descendants(record):
            for key in record.get("children",[]):
                child=self.store.get("jobs",key)
                if child is None:raise ValueError("missing persisted recovery child")
                self.store.register_jobs(self.run_id,[key])
                descendants(child)
        for record in self.store.iter_run_jobs(self.run_id,root=True):descendants(record)
        if self.journal:
            def restore_job(descriptor):
                source=self.source_map[descriptor["source_id"]]
                expert=self.expert_map[descriptor["expert_id"]]
                result=self.job(source,expert,descriptor["start"],descriptor["end"],
                    depth=descriptor.get("depth",0),parent=descriptor.get("parent"))
                if result["job_id"]!=descriptor["job_id"]:raise ValueError("journal job configuration mismatch")
                self.store.register_jobs(self.run_id,[result["job_id"]],root=not result.get("parent"))
                if result.get("parent"):
                    parent=self.store.get("jobs",result["parent"])
                    if not parent or parent["source_id"]!=result["source_id"] or parent["expert"]!=result["expert"] or result["depth"]!=parent["depth"]+1 or not parent["start"]<=result["start"]<result["end"]<=parent["end"]:
                        raise ValueError("journal recovery child differs from parent")
                    parent.update(status="split",reason="reconstructed_durable_recovery_child",
                        children=sorted(set(parent.get("children",[])+[result["job_id"]])),coverage_complete=False)
                    self.store.put("jobs",parent["job_id"],parent)
                return result
            self.journal.reconcile(self.store,restore_job=restore_job)
        self.reconcile_quota_receipts()
        # A process crash after dispatch cannot prove whether it was billed.
        for job in self.store.run_job_rows(self.run_id, status="running"):
            key = job["job_id"]
            if job["status"] == "running":
                cache = self.store.get("cache", key)
                if cache and cache.get("attempt_id") == job.get("attempt_id"):
                    job.update(status="pending", reason="replay_settled_cached_response_after_interruption")
                else:
                    job.update(status="uncertain", reason="interrupted_after_dispatch_outcome_unknown")
                    attempt = self.store.get("costs", job.get("attempt_id"))
                    if attempt:
                        attempt.update(status="uncertain", finished_at=now())
                        self.store.put("costs", attempt["attempt_id"], attempt)
                    if self.resilience and self.resilience["automatic_uncertain_retries"] and attempt:
                        self.failure(job, attempt, ProviderError("interrupted_after_dispatch_outcome_unknown", uncertain=True, retryable=True))
                        continue
                self.store.put("jobs", key, job)
        for job in self.store.iter_run_jobs(self.run_id):
            if job["status"]!="uncertain" or job.get("response_processed"):continue
            cache=self.store.get("cache",job["job_id"])
            if cache and cache.get("attempt_id")==job.get("attempt_id") and cache.get("usage_status")=="unknown":
                job.update(status="pending",reason="replay_unknown_usage_receipt_grounding_only")
                self.store.put("jobs",job["job_id"],job)
        for run in self.store.rows("runs", where="json_extract(data,'$.status')='running'"):
            if run["status"] == "running":
                run.update(status="partial", stop_reason="process_interrupted", finished_at=now())
                self.store.put("runs", run["run_id"], run)
        if streaming:return roots
        # Preserve the small trusted API's source/expert/window order. The
        # production scheduler uses indexed iteration rather than this list.
        expert_order={expert:index for index,expert in enumerate(self.expert_map)}
        def root_order(key):
            job=self.store.get("jobs",key)
            return job["source_id"],expert_order[job["expert"]["id"]],job["start"],job["end"]
        return sorted(roots,key=root_order)

    def _ledger(self):
        if self.ledger is None:
            self.ledger = {"debit":0.0, "stages":{s:0.0 for s in STAGES}, "calls":0, "retries":0,"request_seconds":0.0}
            for row in self.store.iter_rows("costs", where="json_extract(data,'$.policy_hash')=? AND (json_extract(data,'$.budget_scope')=? OR json_extract(data,'$.stage')='discovery')", params=(self.policy,self.budget_scope)):
                debit = row.get("settled_usd", row.get("reserved_usd",0))
                self.ledger["debit"] += debit
                self.ledger["stages"][row["stage"]] += debit
                self.ledger["calls"] += row.get("request_count",0)
                self.ledger["retries"] += int(row.get("is_retry",False))
                self.ledger["request_seconds"]+=row.get("settled_seconds",row.get("reserved_seconds",0.0))
        return self.ledger

    def _adjust_reserve(self, attempt, settled):
        ledger = self._ledger()
        delta = settled - attempt["reserved_usd"]
        ledger["debit"] += delta
        ledger["stages"][attempt["stage"]] += delta

    def _adjust_time(self,attempt,seconds):
        self._ledger()["request_seconds"]+=seconds-attempt.get("reserved_seconds",0)

    def _state(self, alias):
        key = self.model_keys[alias]
        if key not in self.health:
            model = self.profile["models"][alias]
            self.health[key] = {"model_key":key, "model_alias":alias, "provider":model["provider"],
                "model":model["model"], "policy_hash":self.policy, "budget_scope":self.budget_scope,
                "state":"closed", "failures":0, "probe_job_id":None, "retry_at":0,
                "last_started_at":0, "reason":None, "completed_requests":0,
                "latency_samples_seconds":[]}
        return self.health[key]

    def _save_health(self):
        self.store.setting("model_circuits", self.health)

    def _disable(self, job, reason):
        state = self._state(job["expert"]["model"])
        state.update(state="disabled", reason=reason, retry_at=None, disabled_at=now())
        self._save_health()
        if job["status"] == "pending":
            job.update(status="deferred", reason=reason)
            self.store.put("jobs",job["job_id"],job)
        self.audit(job, reason)
        self._clear_quota_waiters(job["expert"]["model"])

    def _clear_quota_waiters(self,alias,except_job=None):
        if not self.quota:return
        for token,(model,job_id) in list(self.quota_wait_jobs.items()):
            if model==alias and job_id!=except_job:
                self.quota.cancel_waiter(token)
                self.quota_waiters.discard(token)
                self.quota_wait_jobs.pop(token,None)

    def _model_failure(self, job, error):
        scope=getattr(getattr(error,"failure_scope",None),"value",None)
        if scope is None:
            scope="request" if error.reason in {"http_400","http_413","http_422"} else "model"
        permitted = error.retryable and (not error.uncertain or self.resilience["automatic_uncertain_retries"])
        if scope in {"request","source"}:
            if permitted and job["attempts"]<=self.execution["max_retries"]:
                hint=error.retry_after_seconds
                if hint is not None and hint>self.resilience["max_retry_after_seconds"]:
                    job.update(status="deferred",reason="request_retry_after_exceeds_policy")
                else:
                    delay=retry_delay(self.resilience,job["attempts"],retry_after=hint,random=self.random)
                    job.update(status="pending",reason="scheduled_request_retry",not_before=self.clock.time()+delay,
                               possible_duplicate_billing=error.uncertain)
                self.store.put("jobs",job["job_id"],job)
            return
        state = self._state(job["expert"]["model"])
        if not permitted:
            self._disable(job, "model_disabled_nonretryable_" + error.reason)
            if scope=="provider":
                for alias,model in self.profile["models"].items():
                    if model["provider"]==job["model"]["provider"]:
                        self._state(alias).update(state="disabled",reason="provider_disabled_"+error.reason,retry_at=None)
                        self._clear_quota_waiters(alias)
                self._save_health()
            return
        if state["state"] == "disabled": return
        if state["state"] == "cooldown" and state["probe_job_id"] != job["job_id"]:
            # Already-in-flight failures do not each create a competing probe.
            job.update(status="pending", reason="waiting_for_model_probe", not_before=state["retry_at"])
            self.store.put("jobs",job["job_id"],job)
            return
        failures = state["failures"] + 1
        state.update(failures=failures, last_error=error.reason, probe_job_id=job["job_id"])
        if failures >= self.execution["max_retries"] + 1:
            job.update(status="deferred", reason="model_retry_attempts_exhausted")
            self.store.put("jobs",job["job_id"],job)
            self._disable(job,"model_retry_attempts_exhausted")
            return
        hint = error.retry_after_seconds
        if hint is not None and hint > self.resilience["max_retry_after_seconds"]:
            job.update(status="deferred",reason="server_retry_after_exceeds_policy")
            self.store.put("jobs",job["job_id"],job)
            self._disable(job,"server_retry_after_exceeds_policy")
            return
        delay = retry_delay(self.resilience, failures, retry_after=hint, random=self.random)
        state.update(state="cooldown", retry_at=self.clock.time()+delay, reason=error.reason,
                     selected_delay_seconds=delay, updated_at=now())
        job.update(status="pending", reason="scheduled_model_retry", not_before=state["retry_at"],
                   automatic_retry_policy="bounded_model_backoff_v1",
                   possible_duplicate_billing=error.uncertain)
        self.store.put("jobs",job["job_id"],job)
        self._save_health()
        self.audit(job,"scheduled_model_retry")
        self._clear_quota_waiters(job["expert"]["model"],except_job=job["job_id"])

    def _model_success(self, job, *, cached=False):
        if not self.resilience: return
        state = self._state(job["expert"]["model"])
        if not cached: state["completed_requests"] += 1
        if state["state"] != "disabled" and (state["state"] == "closed" or state["probe_job_id"] == job["job_id"]):
            state.update(state="closed", failures=0, retry_at=0, probe_job_id=None, reason=None)
        self._save_health()

    def admit(self, job):
        if not getattr(self,"quota_reconciliation_complete",True):
            return None,"quota_receipt_reconciliation_pending"
        admission = job.get("token_admission")
        if admission is not None and not admission["admitted"]:
            self.split(job, "context_capacity_split_recovery")
            return None, "context_capacity_split_recovery"
        reserve = reserve_cost(job["model"], job["max_output_tokens"])
        stage = job["expert"]["stage"]
        ledger = self._ledger()
        if ledger["calls"] >= self.execution["max_calls"]:
            return None, "request_budget_exhausted"
        remaining_seconds=self.execution["deadline_seconds"]-ledger["request_seconds"]
        if remaining_seconds<1:return None,"cumulative_request_time_budget_exhausted"
        reserved_seconds=min(self.execution["timeout_seconds"],int(remaining_seconds))
        if self.resilience and job["attempts"] and ledger["retries"] >= self.resilience["max_retry_calls"]:
            return None, "aggregate_retry_budget_exhausted"
        if ledger["debit"] + reserve > self.execution["budget_usd"] + 1e-12 or ledger["stages"][stage] + reserve > self.execution["stage_budgets"][stage] + 1e-12:
            return None, "spending_budget_reservation_exhausted"
        aid = job.get("quota_attempt_token") if self.quota else None
        aid = aid or "attempt_" + uuid.uuid4().hex
        lease=None
        if self.quota:
            tokens=job.get("token_admission",{}).get("input_tokens")
            if type(tokens) is not int or tokens<0:
                tokens=token_admission(job["model"],self.request(job)["prompt"],job["max_output_tokens"],
                    tokenizer=self.tokenizers.get(job["expert"]["model"]))["input_tokens"]
            admission=self.quota.try_acquire(str(self.project.store.read_setting("study_id") or digest(str(self.project.path))[:24]),
                job["job_id"],aid,tokens+job["max_output_tokens"],retry=job["attempts"]>0)
            if admission.lease is None:
                job.update(reason=admission.reason,capacity_wait_started=job.get("capacity_wait_started") or now(),
                           quota_wait_seconds=admission.retry_after,quota_config_conflict=admission.config_conflict,
                           quota_attempt_token=aid)
                self.quota_waiters.add(aid)
                self.quota_wait_jobs[aid]=(job["expert"]["model"],job["job_id"])
                self.store.put("jobs",job["job_id"],job)
                return None,"quota_"+admission.reason
            lease=admission.lease
            self.quota_leases[aid]=lease
            self.quota_waiters.discard(aid)
            self.quota_wait_jobs.pop(aid,None)
            job.pop("quota_attempt_token",None)
        attempt = {"attempt_id": aid, "job_id": job["job_id"], "run_id": self.run_id,
            "stage": stage, "policy_hash": self.policy, "reserved_usd": reserve,
            "budget_scope": self.budget_scope,
            "status": "dispatched", "request_count": 1, "created_at": now(), "is_retry":job["attempts"] > 0,
            "billing_kind": "provider_reported_token_estimate" if getattr(self.provider, "paid", False) else "simulated",
            "invoice_usd": None, "invoice_usd_reason": "provider_invoice_not_available"}
        attempt["reserved_seconds"]=reserved_seconds
        attempt["time_accounting_version"]=2
        job["attempt_timeout_seconds"]=reserved_seconds
        if lease:attempt["quota_lease_id"]=lease.lease_id
        self.queue_wait_deadline=None
        job.update(status="running", attempts=job["attempts"]+1, run_id=self.run_id,
                   reason="request_dispatched", attempt_id=aid, cache_bypass_once=False,
                   response_processed=False)
        try:
            with self.store.connection() as db:
                self.store.put("costs", aid, attempt, db)
                self.store.put("jobs", job["job_id"], job, db)
        except BaseException:
            if lease:self.quota.release(lease,outcome="not_sent")
            raise
        ledger["debit"] += reserve
        ledger["stages"][stage] += reserve
        ledger["calls"] += 1
        ledger["retries"] += int(attempt["is_retry"])
        ledger["request_seconds"]+=reserved_seconds
        if self.resilience:
            try:
                self._state(job["expert"]["model"])["last_started_at"] = self.clock.time()
                self._save_health()
            except BaseException:
                # The caller cannot submit until admission returns. A local
                # health failure therefore proves this request was never sent.
                try:
                    self.not_sent(job,attempt,"dispatch_not_started")
                finally:
                    # Even unavailable local settlement storage must not strand
                    # known uninvoked capacity under a still-live notebook owner.
                    retained=self.quota_leases.pop(aid,None)
                    if retained:self.quota.release(retained,outcome="not_sent")
                raise
        return attempt, None

    def _ack_quota_receipt(self,attempt):
        attempt.update(quota_receipt_version=QUOTA_RECEIPT_VERSION,
            quota_receipt_scope_id=self.quota.scope_id,
            quota_receipt_lease_id=attempt["quota_lease_id"])
        self.store.put("costs",attempt["attempt_id"],attempt)

    def _settle_quota_receipt(self,lease,attempt):
        outcome="uncertain" if attempt["status"]=="uncertain" else "not_sent" if attempt["status"]=="not_sent" else "settled"
        tokens=(attempt.get("input_tokens",0)+attempt.get("output_tokens",0)) if outcome=="settled" else None
        try:
            self.quota.release(lease,outcome=outcome,actual_tokens=tokens)
        except ValueError:
            if outcome!="settled":raise
            # A verified local terminal attempt proves this call ended. It may
            # resolve a registry's uncertain state; worker death alone may not.
            proof={k:attempt.get(k) for k in ("attempt_id","job_id","quota_lease_id",
                "status","settled_usd","input_tokens","output_tokens","request_count")}
            self.quota.resolve_uncertain(lease,
                evidence="local-attempt:"+attempt["attempt_id"]+":"+digest(proof)[:24],
                actual_tokens=tokens)

    def reconcile_quota_receipts(self):
        """Close only identity-bound, known local terminal quota outcomes.

        Unknown execution or usage never supplies this proof. Acknowledgments
        bound each closed lease so bounded resume passes make durable progress.
        """
        self.quota_reconciliation_complete=True
        if not self.quota:return
        study_id=str(self.project.store.read_setting("study_id") or digest(str(self.project.path))[:24])
        where="""json_extract(data,'$.status') IN ('settled','rejected','not_sent')
            AND json_type(data,'$.quota_lease_id')='text'
            AND (coalesce(json_extract(data,'$.quota_receipt_version'),'')!=?
                OR coalesce(json_extract(data,'$.quota_receipt_scope_id'),'')!=?
                OR coalesce(json_extract(data,'$.quota_receipt_lease_id'),'')!=json_extract(data,'$.quota_lease_id'))"""
        for index,attempt in enumerate(self.store.iter_rows("costs",where=where,
                params=(QUOTA_RECEIPT_VERSION,self.quota.scope_id),batch_size=32)):
            if (index>=MAX_PLANNED_JOBS or self.store.read_setting("cancel_requested")
                    or self.clock.monotonic()>=self.deadline):
                self.quota_reconciliation_complete=False
                self.planning_complete=False
                return
            job=self.store.get("jobs",attempt.get("job_id"))
            status=attempt["status"]
            usage=(attempt.get("input_tokens"),attempt.get("output_tokens"))
            if (not job or job.get("job_id")!=attempt.get("job_id")
                    or not isinstance(attempt.get("attempt_id"),str)
                    or status=="settled" and (any(type(n) is not int or n<0 for n in usage)
                        or sum(usage)>100_000_000)
                    or status in {"rejected","not_sent"} and attempt.get("settled_usd")!=0
                    or status=="not_sent" and attempt.get("request_count")!=0):
                raise ValueError("Known quota outcome lacks a compatible durable local attempt receipt")
            lease=self.quota.lease(attempt["quota_lease_id"])
            if lease:
                if (lease.scope_id!=self.quota.scope_id or lease.study_id!=study_id
                        or lease.job_id!=attempt["job_id"] or lease.attempt_token!=attempt["attempt_id"]):
                    raise ValueError("Quota terminal receipt identity does not match this study and attempt")
                self._settle_quota_receipt(lease,attempt)
            # Only terminal registry history is pruned. A missing lease beside a
            # compatible known local completion needs no new call or new lease.
            self._ack_quota_receipt(attempt)

    def _terminal(self,job,attempt):
        try:
            if self.journal:self.journal.terminal(job,attempt)
        finally:
            lease=self.quota_leases.get(attempt["attempt_id"])
            if lease:
                self._settle_quota_receipt(lease,attempt)
                self.quota_leases.pop(attempt["attempt_id"],None)
                if attempt["status"] in {"settled","rejected","not_sent"}:
                    self._ack_quota_receipt(attempt)

    def not_sent(self,job,attempt,reason,*,journal_intent=False):
        attempt.update(status="not_sent",settled_usd=0,settled_seconds=0,request_count=0,reason=reason,finished_at=now())
        job.update(status="pending",reason=reason,attempts=max(0,job["attempts"]-1))
        with self.store.connection() as db:
            self.store.put("costs",attempt["attempt_id"],attempt,db)
            self.store.put("jobs",job["job_id"],job,db)
        self._adjust_reserve(attempt,0)
        self._adjust_time(attempt,0)
        self.ledger["calls"]-=1
        self.ledger["retries"]-=int(attempt["is_retry"])
        if journal_intent:self._terminal(job,attempt)
        else:
            lease=self.quota_leases.pop(attempt["attempt_id"],None)
            if lease:self.quota.release(lease,outcome="not_sent")

    def request(self, job):
        source = self.source_map[job["source_id"]]
        text = source["text"][job["start"]:job["end"]]
        return {"job_id": job["job_id"], "attempt_id":job.get("attempt_id"),"attempt_number":job["attempts"],
                "logical_request_id":ident("logical",{"source_id":job["source_id"],"prompt_sha256":job["prompt_sha256"],"expert":job["expert"],"model":job["model"],"start":job["start"],"end":job["end"],"max_output_tokens":job["max_output_tokens"]}),
                "prompt": build_prompt(self.recipe, job["expert"], text, source),
                "text": text, "start": job["start"], "source": source, "expert": job["expert"],
                "max_output_tokens": job["max_output_tokens"], "timeout_seconds": min(job.get("attempt_timeout_seconds",self.execution["timeout_seconds"]),max(1,int(getattr(self,"deadline",self.clock.monotonic()+self.execution["timeout_seconds"])-self.clock.monotonic()))),
                "recipe": self.recipe}

    def audit(self, job, reason, proposal=None):
        row = {"audit_id": "audit_" + uuid.uuid4().hex, "job_id": job["job_id"],
               "source_id": job["source_id"], "run_id": self.run_id, "reason": reason,
               "proposal": proposal, "created_at": now(), "review_status": "unresolved"}
        self.store.put("audit", row["audit_id"], row)

    def persist_grounded(self, term, occurrence, db):
        previous = self.store.get("terms", term["term_id"], db)
        if previous:
            previous["original_spellings"] = sorted(set(previous["original_spellings"] + term["original_spellings"]))
            previous["recipe_ids"] = sorted(set(previous["recipe_ids"] + term["recipe_ids"]))
            previous["first_observed_in_corpus"] = min(previous["first_observed_in_corpus"], term["first_observed_in_corpus"])
            if previous["source_supported_definition"]["text"] is None and term["source_supported_definition"]["text"]:
                previous["source_supported_definition"] = term["source_supported_definition"]
            term = previous
        previous = self.store.get("occurrences", occurrence["occurrence_id"], db)
        if previous:
            for field in ("provenance", "contexts"):
                for item in occurrence[field]:
                    if item not in previous[field]:
                        previous[field].append(item)
            occurrence = previous
        self.store.put("terms", term["term_id"], term, db)
        self.store.put("occurrences", occurrence["occurrence_id"], occurrence, db)

    def accept(self, job, response, *, cached=False):
        source = self.source_map[job["source_id"]]
        candidates, complete, errors = parse_response(response.text)
        for error in errors:
            self.audit(job, error, {"raw_response": response.text})
        provenance = {"job_id": job["job_id"], "run_id": job.get("run_id"), "expert_id": job["expert"]["id"],
            "record_type": self.recipe.get("data_type", "term"),
            "observed_text_contract": "exact_contiguous_source_span",
            "interpretation_origin": "model_generated_suggestion",
            "lens": job["expert"]["lens"], "stage": job["expert"]["stage"],
            "provider": job["model"]["provider"], "model": job["model"]["model"],
            "configured_model_version": job["model"]["version"], "reported_model_version": response.model_version,
            "reported_model_version_reason": None if response.model_version else "not_reported_by_provider",
            "prompt_version": VERSION, "prompt_sha256": job["prompt_sha256"], "recipe_sha256": self.policy,
            "processing_version":PROCESSING_VERSION,
            "request_id": response.request_id, "cached": cached, "created_at": now(),
            "transport_identity": self.provider_identity,
            "runtime": job.get("runtime", runtime_manifest(job["model"])),
            "declared_cluster_runtime": job.get("declared_cluster_runtime"),
            "declared_cluster_runtime_reason": None if job.get("declared_cluster_runtime") else "not_running_with_cluster_declaration",
            "request_decoding": job.get("request_decoding", {"temperature": 0,
                "max_output_tokens": job["max_output_tokens"], "thinking_budget": job["model"]["thinking_budget"],
                "origin": "quarry_transport_configuration"}),
            "token_admission": job.get("token_admission"),
            "token_admission_reason": None if job.get("token_admission") else "legacy_profile_without_total_context_capacity"}
        response_hash=digest(response.text)
        cursor=job.get("candidate_cursor",0) if job.get("candidate_processing_version")==PROCESSING_VERSION and job.get("candidate_response_sha256")==response_hash else 0
        for index,proposal in enumerate(candidates):
            if index<cursor:continue
            if time.monotonic()>=getattr(self,"processing_deadline",float("inf")):
                raise RuntimeError("Local processing interrupted; raw receipt retained")
            # Every successful proposal variant remains in the occurrence's
            # provenance, including conflicting attributes/quotes/translations.
            proposal_provenance = dict(provenance, proposal=proposal, proposal_origin="model_output")
            grounded, proposal_errors = ground(proposal, source, job, self.recipe, proposal_provenance,stream=True)
            if proposal_errors:
                self.audit(job, ";".join(proposal_errors), proposal)
            occurrence_cursor=job.get("grounding_cursor",{})
            resume_occurrence=(occurrence_cursor.get("occurrence",0) if occurrence_cursor.get("candidate")==index and occurrence_cursor.get("response_sha256")==response_hash and occurrence_cursor.get("processing_version")==PROCESSING_VERSION else 0)
            for ordinal,(term,occurrence) in enumerate(grounded):
                if ordinal<resume_occurrence:continue
                if ordinal%64==0 and (time.monotonic()>=getattr(self,"processing_deadline",float("inf")) or shutil.disk_usage(self.project.path).free<256*1024*1024):
                    raise RuntimeError("Grounding interrupted; committed evidence and raw receipt retained")
                with self.store.connection() as db:
                    self.persist_grounded(term, occurrence, db)
                    job["grounding_cursor"]={"candidate":index,"occurrence":ordinal+1,"response_sha256":response_hash,"processing_version":PROCESSING_VERSION}
                    self.store.put("jobs",job["job_id"],job,db)
            with self.store.connection() as db:
                job.update(candidate_cursor=index+1,candidate_processing_version=PROCESSING_VERSION,candidate_response_sha256=response_hash)
                job.pop("grounding_cursor",None)
                self.store.put("jobs",job["job_id"],job,db)
        complete = complete and response.finish_reason in {"stop", "STOP"} and not errors
        job["response_processed"]=True
        if complete:
            job.update(status="done", reason="model_reported_complete", coverage_complete=True,processing_version=PROCESSING_VERSION)
        else:
            self.split(job, "incomplete_response_split_recovery")
        self.store.put("jobs", job["job_id"], job)

    def split(self, job, reason):
        source = self.source_map[job["source_id"]]
        if job["depth"] < self.execution["split_depth"] and job["end"] - job["start"] > 32:
            span = job["end"] - job["start"]
            mid = job["start"] + span // 2
            overlap = min(self.execution["overlap_chars"], span // 4)
            children = [self.job(source, job["expert"], s,e, depth=job["depth"]+1, parent=job["job_id"])
                        for s,e in ((job["start"], mid + overlap), (mid - overlap, job["end"]))]
            self.current_jobs.update(c["job_id"] for c in children)
            self.store.register_jobs(self.run_id, [c["job_id"] for c in children])
            job.update(status="split", reason=reason,
                       children=[c["job_id"] for c in children], coverage_complete=False)
        else:
            job.update(status="partial", reason="recovery_depth_or_minimum_window_exhausted", coverage_complete=False)
            self.audit(job, job["reason"])
        self.store.put("jobs", job["job_id"], job)

    def settle(self, job, attempt, response):
        if not isinstance(response,Response) or not isinstance(response.text,str) or len(response.text.encode("utf-8"))>8_000_000:
            raise ProviderError("invalid_provider_response",uncertain=True)
        known = (type(response.input_tokens) is int and response.input_tokens >= 0
                 and type(response.output_tokens) is int and response.output_tokens >= 0)
        if not known:
            # Keep exact grounded discoveries, but do not make more paid requests
            # after unknown usage. The full reserve remains charged to the budget.
            job.update(status="uncertain", reason="provider_usage_unknown")
            attempt.update(status="uncertain", finished_at=now())
            with self.store.connection() as db:
                self.store.put("jobs",job["job_id"],job,db)
                self.store.put("costs",attempt["attempt_id"],attempt,db)
                self.store.put("cache",job["job_id"],{"key":job["job_id"],"response":asdict(response),
                    "attempt_id":attempt["attempt_id"],"usage_status":"unknown","response_sha256":digest(response.text)},db)
            receipt_failure=None
            try:self._terminal(job,attempt)
            except BaseException:
                receipt_failure="local_accounting_receipt_failure"
                self.incident(receipt_failure,job=job,attempt=attempt)
            self.accept(job, response)
            job.update(status="uncertain",reason="provider_usage_unknown")
            self.store.put("jobs",job["job_id"],job)
            self.audit(job, "provider_usage_unknown")
            if self.resilience:
                self._disable(job,"model_disabled_unknown_usage")
                return receipt_failure
            return receipt_failure or "provider_usage_unknown"
        billed = token_cost(job["model"], response.input_tokens, response.output_tokens)
        attempt.update(status="settled", settled_usd=billed, input_tokens=response.input_tokens,
                       output_tokens=response.output_tokens, finished_at=now(),
                       reservation_overrun=billed > attempt["reserved_usd"] + 1e-12)
        seconds=max(0,attempt.get("latency_seconds",0))
        attempt["settled_seconds"]=seconds
        # Cache response and settle atomically. Crash between this and grounding
        # replays the cached response without issuing a second API request.
        with self.store.connection() as db:
            self.store.put("costs", attempt["attempt_id"], attempt, db)
            self.store.put("cache", job["job_id"], {"key": job["job_id"], "response": asdict(response),
                         "attempt_id": attempt["attempt_id"],"usage_status":"known","response_sha256":digest(response.text)}, db)
        self._adjust_reserve(attempt,billed)
        self._adjust_time(attempt,seconds)
        receipt_failure=None
        try:self._terminal(job,attempt)
        except BaseException:
            receipt_failure="local_accounting_receipt_failure"
            self.incident(receipt_failure,job=job,attempt=attempt)
        self.accept(job, response)
        self._model_success(job)
        return receipt_failure or ("provider_contract_cost_overrun" if attempt["reservation_overrun"] else None)

    def failure(self, job, attempt, error):
        if not isinstance(error, ProviderError):
            error = ProviderError("adapter_timeout_outcome_unknown" if isinstance(error,TimeoutError) else "unhandled_provider_error",
                                  uncertain=True,retryable=isinstance(error,TimeoutError))
        attempt.update(failure_reason=error.reason,failure_scope=getattr(getattr(error,"failure_scope",None),"value","uncertain"),
                       retryable=error.retryable,outcome_uncertain=error.uncertain)
        if error.uncertain:
            job.update(status="uncertain", reason=error.reason)
            attempt.update(status="uncertain", finished_at=now())
        else:
            attempt.update(status="rejected", settled_usd=0, finished_at=now())
            seconds=max(0,attempt.get("latency_seconds",0))
            attempt["settled_seconds"]=seconds
            self._adjust_reserve(attempt,0)
            self._adjust_time(attempt,seconds)
            retry = error.retryable and job["attempts"] <= self.execution["max_retries"]
            job.update(status="pending" if retry else "failed", reason=error.reason,
                       not_before=self.clock.time() + min(30, 2 ** job["attempts"]) if retry else 0)
        with self.store.connection() as db:
            self.store.put("jobs", job["job_id"], job, db)
            self.store.put("costs", attempt["attempt_id"], attempt, db)
        self.audit(job, error.reason)
        self._terminal(job,attempt)
        if self.quota and getattr(getattr(error,"failure_scope",None),"value",None)=="provider" and error.retry_after_seconds is not None:
            self.quota.cooldown(error.retry_after_seconds)
        if self.resilience and error.reason == "http_413" and not error.uncertain:
            self.split(job, "payload_too_large_split_recovery")
            # A per-window size problem must not disable an otherwise healthy model.
            self._model_success(job)
            return None
        if self.resilience:
            self._model_failure(job,error)
            return None
        return error.reason if error.uncertain else None

    def coverage(self, key):
        job = self.store.get("jobs", key)
        if job["status"] == "done":
            return True
        return bool(job.get("children")) and all(self.coverage(c) for c in job["children"])

    def run(self, max_jobs=None):
        try:
            with self.store.session():return self._run(max_jobs)
        except (OSError,sqlite3.Error):
            self.incident("local_storage_failure")
            raise RuntimeError("Quarry storage unavailable; last durable state retained; run doctor after storage recovery") from None

    def _invoke(self,request,attempt):
        lease=self.quota_leases.get(attempt["attempt_id"])
        if lease:
            try:self.quota.mark_dispatched(lease)
            except BaseException:
                raise ProviderError("quota_dispatch_not_started",uncertain=False,retryable=False) from None
        if getattr(self.provider,"enforceable_deadline",False):request["cancellation_event"]=self.cancel_event
        return self.provider.complete(request)

    def _processing_failure(self,job,attempt):
        cache=self.store.get("cache",job["job_id"])
        if cache and cache.get("attempt_id")==attempt["attempt_id"]:
            job.update(status="uncertain" if cache.get("usage_status")=="unknown" else "pending",
                       reason="raw_response_saved_processing_failed",coverage_complete=False)
        else:
            durable=self.store.get("costs",attempt["attempt_id"])
            if durable and durable["status"] in {"settled","rejected","not_sent"}:
                # A failed secondary journal/quota receipt must not overwrite
                # a committed provider outcome with fabricated uncertainty.
                if job["status"]=="running":
                    job.update(status="uncertain",reason="local_failure_response_not_durable",coverage_complete=False)
            else:
                job.update(status="uncertain",reason="local_failure_response_not_durable",coverage_complete=False)
                attempt.update(status="uncertain",finished_at=now())
                self.store.put("costs",attempt["attempt_id"],attempt)
        self.store.put("jobs",job["job_id"],job)
        self.incident("local_processing_failure",job=job,attempt=attempt)

    def _consume(self,future,job,attempt,started):
        self.processing_deadline=min(time.monotonic()+SHUTDOWN_GRACE_SECONDS,getattr(self,"drain_deadline",float("inf")))
        attempt["latency_seconds"]=max(0,self.clock.monotonic()-started)
        if self.resilience:
            samples=self._state(job["expert"]["model"])["latency_samples_seconds"]
            samples.append(attempt["latency_seconds"]);del samples[:-32]
        try:
            try:response=future.result()
            except BaseException as error:return self.failure(job,attempt,error)
            try:return self.settle(job,attempt,response)
            except ProviderError as error:return self.failure(job,attempt,error)
            except (OSError,sqlite3.Error):
                self._processing_failure(job,attempt)
                self.incident("local_storage_failure",job=job,attempt=attempt)
                return "local_storage_failure"
            except BaseException:
                self._processing_failure(job,attempt)
                return "local_processing_failure"
        except (OSError,sqlite3.Error):
            self.storage_failed=True
            self.incident("local_storage_failure",job=job,attempt=attempt)
            return "local_storage_failure"
        except BaseException:
            # Journal/quota receipt failures cannot erase the local provider receipt.
            try:self._processing_failure(job,attempt)
            except (OSError,sqlite3.Error):self.storage_failed=True
            self.incident("local_finalization_failure",job=job,attempt=attempt)
            return "local_finalization_failure"

    def replay_cache(self,job,cached):
        if cached.get("response_sha256") and digest(cached["response"]["text"])!=cached["response_sha256"]:
            raise ValueError("saved response receipt hash mismatch")
        token=job.pop("quota_attempt_token",None)
        if token and self.quota:
            self.quota.cancel_waiter(token)
            self.quota_waiters.discard(token)
            self.quota_wait_jobs.pop(token,None)
        self.processing_deadline=min(time.monotonic()+SHUTDOWN_GRACE_SECONDS,getattr(self,"drain_deadline",float("inf")))
        self.accept(job,Response(**cached["response"]),cached=True)
        if cached.get("usage_status")=="unknown":
            job.update(status="uncertain",reason="provider_usage_unknown",response_processed=True)
            self.store.put("jobs",job["job_id"],job)
            if self.resilience:self._disable(job,"model_disabled_unknown_usage")
            else:return "provider_usage_unknown"
        else:self._model_success(job,cached=True)
        return None

    def _run(self, max_jobs=None):
        if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 0):
            raise ValueError("max_jobs must be a nonnegative integer")
        self.deadline = self.clock.monotonic() + self.execution["deadline_seconds"]
        roots = self.prepare(streaming=True)
        run = {"run_id": self.run_id, "created_at": now(), "status": "running",
               "recipe": self.recipe, "profile": self.profile, "policy_hash": self.policy,
               "prompts":prompt_manifest(), "budget_scope":self.budget_scope,
               "root_job_count":len(roots), "transport_identity": self.provider_identity,
               "processing_version":PROCESSING_VERSION,"execution_version":EXECUTION_VERSION,
               "billing_kind": "provider_reported_token_estimate" if getattr(self.provider,"paid",False) else "simulated"}
        run["inference_runtime"] = {alias: runtime_manifest(model) for alias, model in self.profile["models"].items()}
        run["declared_cluster_runtimes"] = self.cluster_runtimes
        run["registered_tokenizers"] = {alias: tokenizer.manifest() for alias, tokenizer in self.tokenizers.items()}
        self.store.put("runs", self.run_id, run)
        deadline = self.deadline
        inflight, dispatched, stop = {}, 0, None
        import resource
        file_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        workers = min(self.execution["concurrency"], max(1,(file_limit-64)//8)) if file_limit != resource.RLIM_INFINITY else self.execution["concurrency"]
        executor = ThreadPoolExecutor(max_workers=workers)
        aliases = list(dict.fromkeys(e["model"] for e in self.expert_map.values()))
        run["model_health"] = [self._state(a) for a in aliases] if self.resilience else []
        if self.resilience: self._save_health()
        rotation = 0
        drain_deadline=None
        run["runtime_limits"] = {"configured_concurrency":self.execution["concurrency"], "active_concurrency":workers,
                                 "resilience":self.resilience, "source_cache_entries":self.source_map.limit,
                                 "cumulative_request_seconds_limit":self.execution["deadline_seconds"],
                                 "historical_time_accounting":"pre-recovery-2 attempts lack request-time reservations"}
        self.store.put("runs",self.run_id,run)
        try:
            while True:
                if shutil.disk_usage(self.project.path).free < 256*1024*1024+workers*8_000_000:
                    stop = "local_disk_reserve_exhausted"
                if self.store.path.stat().st_size+sum(p.stat().st_size for p in self.project.path.glob("project.sqlite3-wal"))>2*1024*1024*1024:
                    stop="local_store_capacity_exhausted"
                if self.store.read_setting("cancel_requested"):
                    stop = "cancelled_by_researcher"
                if self.clock.monotonic() >= deadline:
                    stop = "run_deadline_exhausted"
                if not self.resilience and self.store.run_job_rows(self.run_id,status="uncertain",limit=1):
                    stop = stop or "unresolved_uncertain_api_outcome"
                if max_jobs is not None and dispatched >= max_jobs:
                    stop = stop or "interrupted_at_job_limit"
                if stop and drain_deadline is None:
                    drain_deadline=time.monotonic()+SHUTDOWN_GRACE_SECONDS
                    self.drain_deadline=drain_deadline
                if drain_deadline is not None and time.monotonic()>=drain_deadline:break
                if not stop:
                    for job in self.store.run_cached_jobs(self.run_id):
                        stop=self.replay_cache(job,self.store.get("cache",job["job_id"])) or stop
                        if stop:break
                    # Replay has no provider admission. Disabled circuits,
                    # account capacity and exhausted paid-call budgets must
                    # not strand already committed response receipts.
                    if not stop and self.store.run_cached_jobs(self.run_id,limit=1):continue
                counts = {alias:sum(j["expert"]["model"] == alias for j,_,_ in inflight.values()) for alias in aliases}
                pending = []
                ordered = aliases[rotation:] + aliases[:rotation]
                rotation = (rotation + 1) % max(1,len(aliases))
                for alias in ordered:
                    if stop: break
                    capacity = workers - len(inflight)
                    if self.resilience:
                        state = self._state(alias)
                        capacity = min(capacity, self.resilience["model_concurrency"]-counts[alias])
                        if state["state"] == "disabled" or capacity <= 0: continue
                        if self.clock.time() < state["last_started_at"] + self.resilience["min_request_interval_seconds"]: continue
                        if state["state"] == "cooldown":
                            if counts[alias] or self.clock.time() < state["retry_at"]: continue
                            job = self.store.get("jobs",state["probe_job_id"])
                            if not job or job["job_id"] not in self.current_jobs or job["status"] != "pending":
                                replacement = self.store.run_job_rows(self.run_id,status="pending",model_key=self.model_keys[alias],limit=1)
                                job = replacement[0] if replacement else None
                                if job:
                                    state["probe_job_id"] = job["job_id"]
                                    self._save_health()
                            if job: pending.append(job)
                            continue
                    if capacity > 0:
                        pending.extend(self.store.run_job_rows(self.run_id,status="pending", model_key=self.model_keys[alias],ready_at=self.clock.time(),limit=min(capacity,64)))
                for job in pending:
                    if stop or len(inflight) >= workers:
                        break
                    if job.get("not_before", 0) > self.clock.time():
                        continue
                    alias = job["expert"]["model"]
                    if self.resilience:
                        state = self._state(alias)
                        if counts[alias] >= self.resilience["model_concurrency"]: continue
                        if self.clock.time() < state["last_started_at"] + self.resilience["min_request_interval_seconds"]: continue
                    cached = self.store.get("cache", job["job_id"])
                    if cached and not job.get("cache_bypass_once"):
                        stop=self.replay_cache(job,cached) or stop
                        continue
                    attempt, reason = self.admit(job)
                    if reason:
                        if reason == "context_capacity_split_recovery":
                            continue
                        if reason == "aggregate_retry_budget_exhausted":
                            self._disable(job,reason)
                            continue
                        if reason.startswith("quota_"):
                            if inflight:continue
                            diagnostics=self.quota.diagnostics()
                            entirely_uncertain=diagnostics["states"].get("uncertain",0)>=diagnostics["effective_limits"]["max_inflight"]
                            delay=job.get("quota_wait_seconds")
                            transient=reason in {"quota_account_fair_queue","quota_account_inflight_limit","quota_account_registry_busy","quota_account_cooldown","quota_account_request_rate","quota_account_token_rate"}
                            if transient and not entirely_uncertain and (delay is None or delay<=QUEUE_WAIT_SECONDS):
                                self.queue_wait_deadline=self.queue_wait_deadline or min(self.deadline,self.clock.monotonic()+QUEUE_WAIT_SECONDS)
                                if self.clock.monotonic()<self.queue_wait_deadline:break
                            stop=reason
                            break
                        # A live reservation may be released on settlement. Wait
                        # before deciding that a spending cap leaves work pending.
                        if not inflight or reason not in {"spending_budget_reservation_exhausted","cumulative_request_time_budget_exhausted"}:
                            stop = reason
                        break
                    intent=False
                    try:
                        request=self.request(job)
                        if self.journal:
                            self.journal.intent(job,attempt);intent=True
                        future = executor.submit(self._invoke,request,attempt)
                    except BaseException:
                        self.not_sent(job,attempt,"dispatch_not_started",journal_intent=intent)
                        self.incident("local_dispatch_failure",job=job,attempt=attempt)
                        stop="local_dispatch_failure"
                        break
                    inflight[future] = (job, attempt, self.clock.monotonic())
                    counts[alias] += 1
                    dispatched += 1
                    if max_jobs is not None and dispatched >= max_jobs:
                        break
                if not inflight:
                    if stop or not self.store.run_job_rows(self.run_id,status="pending",limit=1):
                        break
                    if self.resilience and all(self._state(a)["state"] == "disabled" or not self.store.run_job_rows(self.run_id,status="pending",model_key=self.model_keys[a],limit=1) for a in aliases):
                        stop = "model_degraded_after_retry_exhaustion"
                        break
                    self.clock.sleep(0.2)
                    continue
                completed, _ = wait(inflight, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in completed:
                    job, attempt, started = inflight.pop(future)
                    stop = self._consume(future,job,attempt,started) or stop
        except BaseException as error:
            stop="keyboard_interrupt" if isinstance(error,KeyboardInterrupt) else "local_orchestration_failure"
            self.incident(stop)
        finally:
            # One finalizer for every exit path. Already returned evidence is
            # processed even when another job fails. Never await an arbitrary
            # Python adapter indefinitely here.
            drain_deadline=drain_deadline or time.monotonic()+SHUTDOWN_GRACE_SECONDS
            self.drain_deadline=drain_deadline
            while inflight and time.monotonic()<drain_deadline:
                completed,_=wait(inflight,timeout=min(.2,max(0,drain_deadline-time.monotonic())),return_when=FIRST_COMPLETED)
                for future in completed:
                    job,attempt,started=inflight.pop(future)
                    stop=self._consume(future,job,attempt,started) or stop
            if inflight:
                self.cancel_event.set()
                completed,_=wait(inflight,timeout=2)
                for future in completed:
                    job,attempt,started=inflight.pop(future)
                    stop=self._consume(future,job,attempt,started) or stop
                for future,(job,attempt,started) in list(inflight.items()):
                    try:self.failure(job,attempt,ProviderError("shutdown_deadline_outcome_unknown",uncertain=True))
                    except BaseException:self.incident("unresolved_shutdown_attempt",job=job,attempt=attempt)
                stop=stop or "shutdown_deadline_outcome_unknown"
            executor.shutdown(wait=not inflight,cancel_futures=True)
            if self.quota:
                for token in self.quota_waiters:
                    try:self.quota.cancel_waiter(token)
                    except BaseException:self.incident("quota_queue_cleanup_failure")
        if self.storage_failed:
            raise RuntimeError("Quarry storage unavailable; inspect last durable run and attempts after recovery")
        complete = not (stop and stop.startswith("local_")) and self.planning_complete and all(self.coverage(k) for k in roots)
        if not self.planning_complete: stop = stop or "planning_limit_or_cancel_exhausted"
        model_health = [self._state(a) for a in aliases] if self.resilience else []
        if self.resilience: self._save_health()
        run["model_health"] = model_health
        run["degraded"] = any(h["state"] == "disabled" for h in model_health)
        if run["degraded"] and not complete: stop = stop or "model_degraded_after_retry_exhaustion"
        run["healthy_models"] = [h["model_alias"] for h in model_health if h["state"] == "closed"]
        run["planning_complete"] = self.planning_complete
        run["coverage_by_model"] = {a:{"roots":0,"complete":0} for a in aliases}
        for key in roots:
            alias = self.store.get("jobs",key)["expert"]["model"]
            run["coverage_by_model"][alias]["roots"] += 1
            run["coverage_by_model"][alias]["complete"] += int(self.coverage(key))
        complete_roots = sum(v["complete"] for v in run["coverage_by_model"].values())
        run.update(finished_at=now(), status="complete" if complete else "partial", stop_reason=stop,
                   dispatched_calls=dispatched, coverage={"roots":len(roots),
                    "complete":complete_roots,
                    "partial":len(roots)-complete_roots})
        self.store.put("runs", self.run_id, run)
        self.store.setting("last_run_id", self.run_id)
        self.store.checkpoint()
        return self.project.status()
