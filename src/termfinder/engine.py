"""Bounded persistent jobs, conservative reservations and grounded union."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict
from collections import OrderedDict
import time
import uuid
import shutil

from .config import experts, STAGES
from .costs import reserve_cost, token_cost, window_ranges
from .grounding import ground, parse_response
from .prompts import build_prompt, VERSION
from .prompts import manifest as prompt_manifest
from .providers import ProviderError, Response
from .store import digest, ident, now
from .resilience import retry_delay


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
    def __init__(self, project, provider, *, clock=None, random=None):
        self.project, self.store = project, project.store
        self.recipe, self.profile, self.provider = project.recipe, project.profile, provider
        self.execution = self.recipe["execution"]
        self.resilience = self.execution.get("resilience")
        self.clock, self.random = clock or time, random
        self.policy = policy_hash(self.recipe)
        self.provider_identity = getattr(provider, "cache_identity", None) or (
            "paid-transport-v1" if getattr(provider, "paid", False) else "offline-fixture-v1")
        self.budget_scope = "live" if getattr(provider, "paid", False) else "simulation:" + self.provider_identity
        self.run_id = "run_" + uuid.uuid4().hex
        self.expert_map = {e["id"]: e for e in experts(self.recipe, self.profile)}
        self.source_map = SourceCache(self.store)
        self.model_keys = {alias: ident("model", {"alias":alias,"model":model,
            "provider":self.profile["providers"][model["provider"]],
            "policy":self.policy, "scope":self.budget_scope}) for alias,model in self.profile["models"].items()}
        self.health = self.store.read_setting("model_circuits") or {}
        self.ledger = None

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
        key = ident("job", signature)
        existing = self.store.get("jobs", key)
        if existing:
            if existing.get("model_key") != self.model_keys[expert["model"]]:
                existing["model_key"] = self.model_keys[expert["model"]]
                self.store.put("jobs", key, existing)
            return existing
        record = {"job_id": key, "source_id": source["source_id"], "expert": expert,
            "record_type": self.recipe.get("data_type", "term"),
            "model": model, "signature": signature, "policy_hash": self.policy, "start": start,
            "end": end, "depth": depth, "parent": parent, "children": [], "status": "pending",
            "reason": "not_dispatched", "attempts": 0, "created_at": now(), "run_id": None,
            "prompt_sha256": digest(prompt), "coverage_complete": False, "max_output_tokens": output,
            "transport_identity": self.provider_identity, "model_key":self.model_keys[expert["model"]]}
        self.store.put("jobs", key, record)
        return record

    def prepare(self):
        if not hasattr(self, "deadline"):
            self.deadline = self.clock.monotonic() + self.execution["deadline_seconds"]
        root_ids = []
        self.planning_complete = True
        for source in self.source_map.values():
            if self.project.source_exclusion(source) is not None:
                continue
            for start, end in window_ranges(len(source["text"]), self.execution):
                if self.store.read_setting("cancel_requested") or self.clock.monotonic() >= self.deadline:
                    self.planning_complete = False
                    break
                for expert in self.expert_map.values():
                    if "*" not in expert["communities"] and source.get("community") not in expert["communities"]:
                        continue
                    if self.resilience and len(root_ids) >= self.execution["max_calls"]:
                        self.planning_complete = False
                        break
                    root_ids.append(self.job(source, expert, start, end)["job_id"])
                if not self.planning_complete: break
            if not self.planning_complete: break
            if self.store.read_setting("cancel_requested"):
                self.planning_complete = False
                break
        ids = set(root_ids)
        stack = list(ids)
        while stack:
            record = self.store.get("jobs", stack.pop())
            for child in record.get("children", []):
                if child not in ids:
                    ids.add(child)
                    stack.append(child)
        self.current_jobs = ids
        self.store.prune_run_index(self.run_id)
        self.store.register_jobs(self.run_id, root_ids, root=True)
        self.store.register_jobs(self.run_id, ids.difference(root_ids))
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
        for run in self.store.rows("runs", where="json_extract(data,'$.status')='running'"):
            if run["status"] == "running":
                run.update(status="partial", stop_reason="process_interrupted", finished_at=now())
                self.store.put("runs", run["run_id"], run)
        return root_ids

    def _ledger(self):
        if self.ledger is None:
            self.ledger = {"debit":0.0, "stages":{s:0.0 for s in STAGES}, "calls":0, "retries":0}
            for row in self.store.iter_rows("costs", where="json_extract(data,'$.policy_hash')=? AND (json_extract(data,'$.budget_scope')=? OR json_extract(data,'$.stage')='discovery')", params=(self.policy,self.budget_scope)):
                debit = row.get("settled_usd", row.get("reserved_usd",0))
                self.ledger["debit"] += debit
                self.ledger["stages"][row["stage"]] += debit
                self.ledger["calls"] += row.get("request_count",0)
                self.ledger["retries"] += int(row.get("is_retry",False))
        return self.ledger

    def _adjust_reserve(self, attempt, settled):
        ledger = self._ledger()
        delta = settled - attempt["reserved_usd"]
        ledger["debit"] += delta
        ledger["stages"][attempt["stage"]] += delta

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

    def _model_failure(self, job, error):
        state = self._state(job["expert"]["model"])
        permitted = error.retryable and (not error.uncertain or self.resilience["automatic_uncertain_retries"])
        if not permitted:
            self._disable(job, "model_disabled_nonretryable_" + error.reason)
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

    def _model_success(self, job, *, cached=False):
        if not self.resilience: return
        state = self._state(job["expert"]["model"])
        if not cached: state["completed_requests"] += 1
        if state["state"] != "disabled" and (state["state"] == "closed" or state["probe_job_id"] == job["job_id"]):
            state.update(state="closed", failures=0, retry_at=0, probe_job_id=None, reason=None)
        self._save_health()

    def admit(self, job):
        reserve = reserve_cost(job["model"], job["max_output_tokens"])
        stage = job["expert"]["stage"]
        ledger = self._ledger()
        if ledger["calls"] >= self.execution["max_calls"]:
            return None, "request_budget_exhausted"
        if self.resilience and job["attempts"] and ledger["retries"] >= self.resilience["max_retry_calls"]:
            return None, "aggregate_retry_budget_exhausted"
        if ledger["debit"] + reserve > self.execution["budget_usd"] + 1e-12 or ledger["stages"][stage] + reserve > self.execution["stage_budgets"][stage] + 1e-12:
            return None, "spending_budget_reservation_exhausted"
        aid = "attempt_" + uuid.uuid4().hex
        attempt = {"attempt_id": aid, "job_id": job["job_id"], "run_id": self.run_id,
            "stage": stage, "policy_hash": self.policy, "reserved_usd": reserve,
            "budget_scope": self.budget_scope,
            "status": "dispatched", "request_count": 1, "created_at": now(), "is_retry":job["attempts"] > 0,
            "billing_kind": "provider_reported_token_estimate" if getattr(self.provider, "paid", False) else "simulated",
            "invoice_usd": None, "invoice_usd_reason": "provider_invoice_not_available"}
        job.update(status="running", attempts=job["attempts"]+1, run_id=self.run_id,
                   reason="request_dispatched", attempt_id=aid, cache_bypass_once=False)
        with self.store.connection() as db:
            self.store.put("costs", aid, attempt, db)
            self.store.put("jobs", job["job_id"], job, db)
        ledger["debit"] += reserve
        ledger["stages"][stage] += reserve
        ledger["calls"] += 1
        ledger["retries"] += int(attempt["is_retry"])
        if self.resilience:
            self._state(job["expert"]["model"])["last_started_at"] = self.clock.time()
            self._save_health()
        return attempt, None

    def request(self, job):
        source = self.source_map[job["source_id"]]
        text = source["text"][job["start"]:job["end"]]
        return {"job_id": job["job_id"], "prompt": build_prompt(self.recipe, job["expert"], text, source),
                "text": text, "start": job["start"], "source": source, "expert": job["expert"],
                "max_output_tokens": job["max_output_tokens"], "timeout_seconds": self.execution["timeout_seconds"],
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
            "request_id": response.request_id, "cached": cached, "created_at": now(),
            "transport_identity": self.provider_identity}
        for proposal in candidates:
            # Every successful proposal variant remains in the occurrence's
            # provenance, including conflicting attributes/quotes/translations.
            proposal_provenance = dict(provenance, proposal=proposal, proposal_origin="model_output")
            grounded, proposal_errors = ground(proposal, source, job, self.recipe, proposal_provenance)
            if proposal_errors:
                self.audit(job, ";".join(proposal_errors), proposal)
            with self.store.connection() as db:
                for term, occurrence in grounded:
                    self.persist_grounded(term, occurrence, db)
        complete = complete and response.finish_reason in {"stop", "STOP"} and not errors
        if complete:
            job.update(status="done", reason="model_reported_complete", coverage_complete=True)
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
        known = (type(response.input_tokens) is int and response.input_tokens >= 0
                 and type(response.output_tokens) is int and response.output_tokens >= 0)
        if not known:
            # Keep exact grounded discoveries, but do not make more paid requests
            # after unknown usage. The full reserve remains charged to the budget.
            self.accept(job, response)
            job = self.store.get("jobs", job["job_id"])
            job.update(status="uncertain", reason="provider_usage_unknown")
            attempt.update(status="uncertain", finished_at=now())
            self.store.put("jobs", job["job_id"], job)
            self.store.put("costs", attempt["attempt_id"], attempt)
            self.audit(job, "provider_usage_unknown")
            if self.resilience:
                self._disable(job,"model_disabled_unknown_usage")
                return None
            return "provider_usage_unknown"
        billed = token_cost(job["model"], response.input_tokens, response.output_tokens)
        attempt.update(status="settled", settled_usd=billed, input_tokens=response.input_tokens,
                       output_tokens=response.output_tokens, finished_at=now(),
                       reservation_overrun=billed > attempt["reserved_usd"] + 1e-12)
        # Cache response and settle atomically. Crash between this and grounding
        # replays the cached response without issuing a second API request.
        with self.store.connection() as db:
            self.store.put("costs", attempt["attempt_id"], attempt, db)
            self.store.put("cache", job["job_id"], {"key": job["job_id"], "response": asdict(response),
                         "attempt_id": attempt["attempt_id"]}, db)
        self._adjust_reserve(attempt,billed)
        self.accept(job, response)
        self._model_success(job)
        return "provider_contract_cost_overrun" if attempt["reservation_overrun"] else None

    def failure(self, job, attempt, error):
        if not isinstance(error, ProviderError):
            error = ProviderError("adapter_timeout_outcome_unknown" if isinstance(error,TimeoutError) else "unhandled_provider_error",
                                  uncertain=True,retryable=isinstance(error,TimeoutError))
        if error.uncertain:
            job.update(status="uncertain", reason=error.reason)
            attempt.update(status="uncertain", finished_at=now())
        else:
            attempt.update(status="rejected", settled_usd=0, finished_at=now())
            self._adjust_reserve(attempt,0)
            retry = error.retryable and job["attempts"] <= self.execution["max_retries"]
            job.update(status="pending" if retry else "failed", reason=error.reason,
                       not_before=self.clock.time() + min(30, 2 ** job["attempts"]) if retry else 0)
        with self.store.connection() as db:
            self.store.put("jobs", job["job_id"], job, db)
            self.store.put("costs", attempt["attempt_id"], attempt, db)
        self.audit(job, error.reason)
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
        with self.store.session():
            return self._run(max_jobs)

    def _run(self, max_jobs=None):
        if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 0):
            raise ValueError("max_jobs must be a nonnegative integer")
        self.deadline = self.clock.monotonic() + self.execution["deadline_seconds"]
        roots = self.prepare()
        run = {"run_id": self.run_id, "created_at": now(), "status": "running",
               "recipe": self.recipe, "profile": self.profile, "policy_hash": self.policy,
               "prompts":prompt_manifest(), "budget_scope":self.budget_scope,
               "root_job_ids": roots, "transport_identity": self.provider_identity,
               "billing_kind": "provider_reported_token_estimate" if getattr(self.provider,"paid",False) else "simulated"}
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
        run["runtime_limits"] = {"configured_concurrency":self.execution["concurrency"], "active_concurrency":workers,
                                 "resilience":self.resilience, "source_cache_entries":self.source_map.limit}
        self.store.put("runs",self.run_id,run)
        try:
            while True:
                if shutil.disk_usage(self.project.path).free < 256*1024*1024:
                    stop = "local_disk_reserve_exhausted"
                if self.store.read_setting("cancel_requested"):
                    stop = "cancelled_by_researcher"
                if self.clock.monotonic() >= deadline:
                    stop = "run_deadline_exhausted"
                if not self.resilience and self.store.run_job_rows(self.run_id,status="uncertain",limit=1):
                    stop = stop or "unresolved_uncertain_api_outcome"
                if max_jobs is not None and dispatched >= max_jobs:
                    stop = stop or "interrupted_at_job_limit"
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
                        self.accept(job, Response(**cached["response"]), cached=True)
                        self._model_success(job, cached=True)
                        continue
                    attempt, reason = self.admit(job)
                    if reason:
                        if reason == "aggregate_retry_budget_exhausted":
                            self._disable(job,reason)
                            continue
                        # A live reservation may be released on settlement. Wait
                        # before deciding that a spending cap leaves work pending.
                        if not inflight or reason != "spending_budget_reservation_exhausted":
                            stop = reason
                        break
                    future = executor.submit(self.provider.complete, self.request(job))
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
                    attempt["latency_seconds"] = max(0,self.clock.monotonic()-started)
                    if self.resilience:
                        samples=self._state(job["expert"]["model"])["latency_samples_seconds"]
                        samples.append(attempt["latency_seconds"])
                        del samples[:-32]
                    try:
                        response = future.result()
                        if not isinstance(response, Response):
                            raise ProviderError("invalid_provider_response", uncertain=True)
                    except BaseException as error:
                        stop = self.failure(job, attempt, error) or stop
                    else:
                        stop = self.settle(job, attempt, response) or stop
        except KeyboardInterrupt:
            stop = "keyboard_interrupt"
            # Finite provider timeouts bound outstanding requests. Account for
            # responses that return while cancellation waits, preserving evidence.
            for future, (job, attempt, started) in list(inflight.items()):
                try:
                    self.settle(job, attempt, future.result())
                except BaseException as error:
                    self.failure(job, attempt, error)
        finally:
            executor.shutdown(wait=True, cancel_futures=False)
        complete = self.planning_complete and all(self.coverage(k) for k in roots)
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
