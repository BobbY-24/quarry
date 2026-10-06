"""Public notebook/CLI/UI API for an independently installable research project."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import os
from pathlib import Path
import uuid

from . import costs, prompts
from .config import load_recipe, load_profile, experts, STAGES, canonical
from .engine import Engine, SourceCache, policy_hash
from .providers import FakeProvider, HTTPProvider
from .store import Store, TABLES, digest, ident, now


class Project:
    def __init__(self, path, *, path_guard=None):
        # Optional trusted adapter guard; never supplied by extraction output.
        # This catches observed directory replacements before path-based IO.
        # It is not a replacement for an operating-system filesystem sandbox.
        if path_guard is not None and not callable(path_guard):
            raise ValueError("Invalid project path guard")
        self._path_guard = path_guard
        raw_path = Path(path).expanduser().absolute()
        self._guard_path(raw_path)
        self.path = raw_path.resolve()
        self._guard_path(self.path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._guard_path(self.path)
        if path_guard is None:
            self.store = Store(self.path / "project.sqlite3")
        else:
            self.store = Store(self.path / "project.sqlite3",
                               path_guard=lambda: self._guard_path(self.path))

    def _guard_path(self, path):
        if self._path_guard is not None:
            self._path_guard(path)

    @property
    def recipe(self):
        return self.store.read_setting("recipe")

    @property
    def profile(self):
        return self.store.read_setting("profile")

    @contextmanager
    def _lock(self):
        # macOS/Linux process lock releases on crashes; also excludes UI races.
        self._guard_path(self.path)
        with (self.path / ".collection.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Project has an active collection or configuration operation") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def configuration(self):
        return {"recipe": self.recipe, "profile": self.profile}

    def compute(self):
        from .compute import compute_summary
        configured = self.store.read_setting("configured_profile")
        return compute_summary(configured or self.profile, configured=bool(configured))

    def cluster(self):
        """Durable batch controller; construction never submits or queries jobs."""
        from .cluster import ClusterController
        self._guard_path(self.path)
        return ClusterController(self)

    def configure_cluster(self, profile):
        return self.cluster().configure(profile)

    def configure_cluster_throughput(self, *, concurrency=4, model_concurrency=4,
                                     configuration_reference="researcher operator tuning"):
        """Operator tuning is separate from the research recipe and its budget."""
        from .resilience import cluster_execution
        from .config import starter_recipe
        execution = (self.recipe or starter_recipe("jargon"))["execution"]
        cluster_execution(execution, concurrency=concurrency, model_concurrency=model_concurrency)
        from .agent_setup import _credential_free
        if not isinstance(configuration_reference, str) or not configuration_reference.strip() or len(configuration_reference) > 1000:
            raise ValueError("A bounded operator configuration reference is required")
        _credential_free(configuration_reference)
        with self._lock(), self.store.connection() as db:
            if self.store.count("jobs"):
                raise ValueError("Configure throughput before jobs exist; resume preserves the reviewed execution settings")
            settings = {"concurrency": concurrency, "model_concurrency": model_concurrency}
            self.store.setting("cluster_throughput", settings, db)
            self._plan_event("cluster_throughput_configured", {**settings,
                "configuration_reference": configuration_reference}, db)
        return {"settings": settings, "measured_performance": None,
                "measured_performance_reason": "operator_tuning_requires_representative_benchmark",
                "next_step": "Prepare a fresh collection review before execution."}

    def configure_compute(self, **settings):
        """Save an operator choice, separately from untrusted research/extraction inputs."""
        from .compute import build_compute_profile
        profile = build_compute_profile(**settings)
        with self._lock(), self.store.connection() as db:
            previous = self.store.setting("configured_profile", db=db, write=False)
            if previous != profile:
                if self.store.count("jobs"):
                    raise ValueError("Changing compute after extraction jobs exist requires a separate study; resume preserves the original compute and budget")
                recipe = self.store.setting("recipe", db=db, write=False)
                if recipe:
                    recipe = deepcopy(recipe)
                    recipe["model_profile"] = "configured"
                    aliases = list(profile["models"])
                    for index, lens in enumerate(recipe["specialist_lenses"]):
                        lens["model"] = aliases[index % len(aliases)]
                    ceiling = min(m["output_token_ceiling"] for m in profile["models"].values())
                    for field in ("max_output_tokens", "recovery_output_tokens"):
                        recipe["execution"][field] = min(recipe["execution"][field], ceiling)
                    load_recipe(recipe)
                    experts(recipe, profile)
                    self.store.setting("recipe", recipe, db)
                self.store.setting("configured_profile", profile, db)
                self.store.setting("profile", profile, db)
                self.store.setting("agent_setup", None, db)
                self.store.setting("agent_proposal", None, db)
                event = self._plan_event("compute_configured", {"profile": profile,
                    "profile_sha256": digest(profile), "configuration_does_not_authorize_inference": True}, db)
                self.store.setting("ui_setup_revision", event, db)
        return self.compute()

    def _planning_profile(self, brief):
        from .agent_setup import planning_profile
        configured = self.store.read_setting("configured_profile")
        if configured and brief["model_profile"] != "configured":
            raise ValueError("Research plans must use the researcher-selected compute")
        return planning_profile(brief, configured)

    def configure(self, recipe, profile=None):
        recipe = load_recipe(recipe)
        profile = load_profile(profile or (self.store.read_setting("configured_profile")
                                          if recipe["model_profile"] == "configured" else recipe["model_profile"]))
        experts(recipe, profile)
        with self._lock(), self.store.connection() as db:
            operator = self.store.setting("configured_profile", db=db, write=False)
            if operator and (recipe["model_profile"] != "configured" or profile != operator):
                raise ValueError("Use the saved configured compute; changes require configure_compute before jobs or a separate study")
            self.store.setting("recipe", recipe, db)
            self.store.setting("profile", profile, db)
            self.store.setting("cancel_requested", False, db)
        return {"recipe_id": recipe["id"], "mode": recipe["mode"], "profile_id": profile["id"],
                "recipe": recipe, "profile": profile}

    def agent_setup(self):
        """Latest handoff; reading never launches an assistant or model."""
        return self.store.read_setting("agent_setup") or {}

    def _plan_event(self, event_type, payload, db):
        from .publication import verify_history
        history = self.store.setting("agent_workflow", db=db, write=False) or []
        if not verify_history(history):
            raise ValueError("Research setup history failed its integrity check")
        event = {"sequence": len(history), "event_type": event_type, "created_at": now(),
                 "previous_sha256": history[-1]["event_sha256"] if history else None,
                 "payload": deepcopy(payload)}
        event["event_sha256"] = digest(event)
        self.store.setting("agent_workflow", history + [event], db)
        return event["event_sha256"]

    def prepare_agent_setup(self, brief):
        from .agent_setup import VERSION, normalize_brief, build_prompt, template_bundle
        brief = deepcopy(brief)
        operator = self.store.read_setting("configured_profile")
        if operator:
            if brief.get("model_profile", "configured") != "configured":
                raise ValueError("Use the researcher-configured compute profile; research plans cannot replace compute settings")
            brief["model_profile"] = "configured"
        brief = normalize_brief(brief)
        selected = self._planning_profile(brief)
        prompt = build_prompt(brief, selected)
        setup = {"version": VERSION, "brief": brief, "brief_sha256": digest(brief), "prompt": prompt,
                 "prompt_sha256": digest(prompt), "starter_bundle": template_bundle(brief, selected), "applied": False}
        with self._lock(), self.store.connection() as db:
            if self.store.setting("configured_profile", db=db, write=False) != operator:
                raise ValueError("Compute changed during preparation; prepare the study again")
            setup["event_sha256"] = self._plan_event("brief_prepared", setup, db)
            self.store.setting("agent_setup", setup, db)
            self.store.setting("agent_proposal", None, db)
            self.store.setting("ui_setup_revision", setup["event_sha256"], db)
        return setup

    def validate_agent_bundle(self, bundle):
        from .agent_setup import validate_bundle
        setup = self.agent_setup()
        if not setup:
            raise ValueError("Describe the study and create an agent request first")
        report = validate_bundle(bundle, setup["brief"], self._planning_profile(setup["brief"]))
        with self._lock(), self.store.connection() as db:
            # Rejected objects can contain credentials. Preserve diagnostics and
            # safe hashes only, never their raw content or exception bodies.
            self._plan_event("bundle_validated" if report["valid"] else "bundle_rejected",
                {"brief_sha256": setup["brief_sha256"], "bundle_sha256": report["bundle_sha256"],
                 "validation": report, **({"submitted_bundle": bundle} if report["valid"] else {})}, db)
        return report

    def apply_agent_bundle(self, bundle, *, purpose="researcher_apply"):
        from .agent_setup import validate_bundle, write_plan_inputs
        if purpose not in {"researcher_apply", "guided_preparation"}:
            raise ValueError("Unknown plan application purpose")
        setup = self.agent_setup()
        if not setup:
            raise ValueError("Create an agent request first")
        report = validate_bundle(bundle, setup["brief"], self._planning_profile(setup["brief"]))
        if not report["valid"]:
            raise ValueError("Plan is not ready. Validate it and send the repair prompt to your agent.")
        recipe = load_recipe(bundle["recipe"])
        profile = self._planning_profile(setup["brief"])
        with self._lock(), self.store.connection() as db:
            current = self.store.setting("agent_setup", db=db, write=False)
            if not current or current["brief_sha256"] != setup["brief_sha256"]:
                raise ValueError("Brief changed during plan review; validate against the latest request")
            self.store.setting("recipe", recipe, db)
            self.store.setting("profile", profile, db)
            self.store.setting("cancel_requested", False, db)
            approved = deepcopy(setup)
            approved.update(bundle=deepcopy(bundle), bundle_sha256=report["bundle_sha256"], applied=True,
                            validation=report, recipe_sha256=digest(recipe), profile_sha256=digest(profile))
            approved["event_sha256"] = self._plan_event("plan_applied",
                {"brief_sha256": setup["brief_sha256"], "prompt_sha256": setup["prompt_sha256"],
                 "bundle_sha256": report["bundle_sha256"], "submitted_bundle": bundle,
                 "recipe_sha256": digest(recipe), "profile_sha256": digest(profile),
                 "approval": "validated_plan_preparation" if purpose == "guided_preparation" else "researcher_explicit_apply",
                 "application_origin": purpose,
                 "identity_note": "Plan application is a recorded operation, not authenticated human identity. Guided collection requires separate hash-bound approval.",
                 "validation": report}, db)
            approved["input_files"] = write_plan_inputs(approved, profile, self.path / "agent-inputs" / report["bundle_sha256"])
            self.store.setting("agent_setup", approved, db)
            self.store.setting("ui_setup_revision", approved["event_sha256"], db)
        # Only researcher-approved local files are read. No URL/model dispatch.
        ingested = self.ingest_agent_sources(include_remote=False, expected_bundle_sha256=report["bundle_sha256"])
        return {**report, **ingested, "applied": True, "estimate": self.estimate(), "input_files": approved["input_files"],
                "next_step": "Inspect sources, freeze whole-source evaluation material and review costs before collection."}

    def ingest_agent_sources(self, *, include_remote=True, expected_bundle_sha256=None):
        from .agent_setup import validate_bundle, read_approved_local
        from .sources import SafeFetcher, error_category
        setup = self.agent_setup()
        if expected_bundle_sha256 is not None and setup.get("bundle_sha256") != expected_bundle_sha256:
            raise ValueError("Plan changed after approval; review the current plan before ingestion")
        if not setup.get("applied"):
            raise ValueError("Apply a validated plan before ingesting its sources")
        if digest(self.recipe) != setup["recipe_sha256"] or digest(self.profile) != setup["profile_sha256"]:
            raise ValueError("Configuration changed since plan approval; create or reapply a reviewed plan")
        report = validate_bundle(setup["bundle"], setup["brief"], self._planning_profile(setup["brief"]))
        if not report["valid"]:
            raise ValueError("Approved inputs changed or are no longer valid; validate the plan again")
        source_ids, failures, staged = [], [], []
        with self._lock():
            current = self.agent_setup()
            if current.get("bundle_sha256") != setup["bundle_sha256"] or current.get("brief_sha256") != setup["brief_sha256"] or not current.get("applied") or digest(self.recipe) != setup["recipe_sha256"] or digest(self.profile) != setup["profile_sha256"]:
                raise ValueError("Plan or configuration changed before ingestion; review the current plan again")
            fetcher = SafeFetcher(self.recipe["source_scope"], timeout=self.recipe["execution"]["timeout_seconds"])
            existing = self.store.read_setting("agent_source_map") or {}
            for source in setup["bundle"]["sources"]:
                key = setup["bundle_sha256"] + ":" + source["source_key"]
                if source["kind"] == "url" and not include_remote:
                    staged.append(source["source_key"])
                    continue
                # Immutable plan source bindings avoid fetching completed URLs
                # again on resume. A new plan is required for content refresh.
                if key in existing and self.store.get("sources", existing[key]):
                    source_ids.append(existing[key])
                    continue
                metadata = deepcopy(source["metadata"])
                metadata["constraints"].update(agent_plan_sha256=setup["bundle_sha256"],
                    agent_brief_sha256=setup["brief_sha256"], agent_source_key=source["source_key"],
                    family_id=source["family_id"], source_selection_origin=source["origin"],
                    source_selection_reason=source["why_selected"], search_refs=source["search_refs"],
                    approved_locator=source["locator"])
                try:
                    document = read_approved_local(source["locator"], setup["brief"], metadata) if source["kind"] == "local" else fetcher.fetch(source["locator"], metadata)
                    sid = self.add_source(document)
                    source_ids.append(sid)
                    existing[key] = sid
                    self.store.setting("agent_source_map", existing)
                except (ValueError, OSError, RuntimeError) as error:
                    reason = error_category(error)
                    self._ingest_failure(source["locator"], reason)
                    failures.append({"source_key": source["source_key"], "reason": reason})
            result = {"source_ids": source_ids, "failures": failures, "staged_remote_source_keys": staged,
                      "bundle_sha256": setup["bundle_sha256"], "network_fetch_authorized": include_remote}
            with self.store.connection() as db:
                self._plan_event("approved_sources_ingested", result, db)
        return result

    def publication_audit(self, version):
        from .publication import audit_dataset
        return audit_dataset(self.dataset(version))

    def freeze_agent_corpus(self, name="corpus-v1", seed="v6-agent-study-v1"):
        """Prepare complete-source human review; never manufacture gold labels."""
        with self._lock():
            return self._freeze_agent_corpus_unlocked(name, seed)

    def _freeze_agent_corpus_unlocked(self, name, seed):
        from .evaluation import source_splits
        from .exports import annotation_sources
        from .config import canonical
        setup = self.agent_setup()
        if not setup.get("applied"):
            raise ValueError("Apply a plan and ingest its sources first")
        if digest(self.recipe) != setup["recipe_sha256"] or digest(self.profile) != setup["profile_sha256"]:
            raise ValueError("Configuration changed since plan approval; review the current plan first")
        source_map = self.store.read_setting("agent_source_map") or {}
        plan = setup["bundle_sha256"]
        selected_ids = {source_map.get(plan + ":" + s["source_key"]) for s in setup["bundle"]["sources"]}
        selected_ids.discard(None)
        if not selected_ids:
            raise ValueError("No successfully ingested plan sources are available")
        all_sources = self.store.all("sources")
        selected_hashes = {s["text_sha256"] for s in all_sources if s["source_id"] in selected_ids}
        previously_processed = {j["source_id"] for j in self.store.all("jobs")}
        if any(s["source_id"] in previously_processed and s["text_sha256"] in selected_hashes for s in all_sources):
            raise ValueError("Processing was already prepared for this source text. Freeze an unseen corpus before collection for independent blind evaluation.")
        version = self._snapshot_unlocked(name)
        dataset = self.dataset(version)
        sources = [s for s in dataset["sources"] if s["source_id"] in selected_ids]
        families = {s["source_id"]: (s.get("constraints", {}).get("family_id") or s["source_id"]) for s in sources}
        grouped = [dict(s, family_id=families[s["source_id"]]) for s in sources]
        holdout = setup["bundle"]["evaluation"]["holdout_fraction"]
        splits = source_splits(grouped, seed=seed, ratios=(1-holdout, 0, holdout), group_field="family_id")
        out = self.path / "human-review" / version
        out.mkdir(parents=True, exist_ok=False)
        packets = annotation_sources(dict(dataset, sources=sources))
        tests = set(splits["splits"]["test"])
        files = {"family-map.json": canonical(families) + "\n", "source-splits.json": canonical(splits) + "\n",
                 "annotation_sources.jsonl": "".join(canonical(packet) + "\n" for packet in packets),
                 "heldout_sources.jsonl": "".join(canonical(packet) + "\n" for packet in packets if packet["source_id"] in tests)}
        for filename, value in files.items():
            (out / filename).write_text(value, encoding="utf-8")
        result = {"version_id": version, "out": str(out), "source_count": len(sources), "split_manifest": splits,
                  "family_map": families, "annotation_files": sorted(files),
                  "note": "Blank packets are not gold. Humans must annotate complete held-out sources; small collections can have an empty test split. Unknown families default to individual sources."}
        with self.store.connection() as db:
            self._plan_event("blind_corpus_prepared", {**result, "bundle_sha256": plan,
                "file_sha256": {key: digest(value) for key, value in files.items()}}, db)
        return result

    def _configured(self):
        if not self.recipe or not self.profile:
            raise ValueError("Configure a project first (termfinder init)")

    def add_source(self, document):
        self._configured()
        document = deepcopy(document)
        if not isinstance(document.get("text"), str) or not document.get("text"):
            raise ValueError("Source has no extractable text")
        if digest(document["text"]) != document["text_sha256"]:
            raise ValueError("source text hash mismatch")
        sid = ident("src", [document["locator"], document["raw_sha256"], document["parser_version"],
                            document.get("language"), document.get("community"), document.get("publication_date"),
                            document.get("constraints"), document.get("domain")])
        document["source_id"] = sid
        if not self.store.get("sources", sid):
            document["ingested_at"] = now()
            document["source_status"] = "ready"
            document["scope_exclusion"] = self.source_exclusion(document)
            self.store.put("sources", sid, document)
        return sid

    def source_exclusion(self, source):
        recipe = self.recipe
        from urllib.parse import urlsplit
        from .sources import in_domain_scope
        locator = source.get("locator", "")
        if urlsplit(locator).scheme in {"http", "https"}:
            if not in_domain_scope(locator, recipe["source_scope"]):
                return "source_domain_out_of_scope"
        elif not recipe["source_scope"]["local"]:
            return "local_sources_disabled"
        dates = recipe["dates"]
        value = source.get("publication_date")
        if value is None and dates["unknown"] == "exclude":
            return "publication_date_unavailable"
        if value:
            if dates["start"] and value[:10] < dates["start"] or dates["end"] and value[:10] > dates["end"]:
                return "publication_date_out_of_scope"
        language = source.get("language", "und")
        if language not in {"und", "mul"} and "*" not in recipe["languages"] and language not in recipe["languages"] and language.split("-")[0] not in recipe["languages"]:
            return "source_language_out_of_scope"
        community = source.get("community")
        if community and "*" not in recipe["communities"] and community not in recipe["communities"]:
            return "source_community_out_of_scope"
        return None

    def _ingest_failure(self, locator, reason):
        aid = "audit_" + uuid.uuid4().hex
        self.store.put("audit", aid, {"audit_id":aid, "source_id":None, "job_id":None,
            "stage":"parsing", "reason":reason, "locator":locator, "created_at":now(),
            "review_status":"unresolved", "proposal":None})

    def ingest(self, paths=(), urls=(), metadata=None):
        from .sources import load_local, SafeFetcher, canonical_url, error_category
        self._configured()
        result = []
        with self._lock():
            for path in paths:
                locator = str(Path(path).expanduser().resolve())
                try:
                    if not self.recipe["source_scope"]["local"]:
                        raise ValueError("local_sources_disabled")
                    result.append(self.add_source(load_local(path, metadata)))
                except (ValueError, OSError, RuntimeError) as error:
                    self._ingest_failure(locator, error_category(error))
            fetcher = SafeFetcher(self.recipe["source_scope"], timeout=self.recipe["execution"]["timeout_seconds"])
            for url in urls:
                locator = None
                try:
                    locator = canonical_url(url)
                    result.append(self.add_source(fetcher.fetch(locator, metadata)))
                except (ValueError, OSError, RuntimeError) as error:
                    self._ingest_failure(locator, error_category(error))
        return result

    def discover(self, *, seeds=(), search_adapter=None, fetcher=None, resume=False):
        from .discovery import discover
        from .sources import SafeFetcher, error_category
        self._configured()
        with self._lock():
            recipe = deepcopy(self.recipe)
            if not recipe["discovery"]["enabled"]:
                raise ValueError("Enable bounded discovery in the recipe before discovery")
            policy = policy_hash(recipe)
            scope_hash = digest({key: recipe[key] for key in ("source_scope", "dates", "languages", "communities")}
                                | {"queries": recipe["discovery"]["queries"]})
            previous = self.store.read_setting("discovery_state") if resume else None
            if previous and (previous.get("scope_hash") != scope_hash or previous.get("policy_hash") != policy):
                raise ValueError("Discovery resume requires the saved research policy and scope; start a new campaign explicitly")
            spent_before = (previous or {}).get("spent_usd", 0)
            requests_before = (previous or {}).get("requests", 0)
            attempts_before = (previous or {}).get("source_attempts", 0)
            campaign = (previous or {}).get("campaign_id") or "discovery_" + uuid.uuid4().hex
            cost_id = "cost_" + campaign
            if previous:
                seeds = [p for p in previous.get("pending", []) if "url" in p or "path" in p]
                recipe["discovery"]["queries"] = [p["query"] for p in previous.get("pending", [])
                    if "query" in p and not ("url" in p or "path" in p)]
            # Campaign counters and all campaigns' stage reservations both cap
            # retries; a crash cannot reset prior estimated charges.
            all_costs = self.store.all("costs")
            total_used = sum(c.get("settled_usd", c.get("reserved_usd", 0)) for c in all_costs if c.get("policy_hash") == policy)
            stage_used = sum(c.get("settled_usd", c.get("reserved_usd", 0)) for c in all_costs
                             if c.get("policy_hash") == policy and c["stage"] == "discovery")
            recipe["discovery"]["max_cost_usd"] = max(0, min(recipe["discovery"]["max_cost_usd"] - spent_before,
                recipe["execution"]["budget_usd"] - total_used, recipe["execution"]["stage_budgets"]["discovery"] - stage_used))
            recipe["discovery"]["max_requests"] = max(0, recipe["discovery"]["max_requests"] - requests_before)
            recipe["discovery"]["max_sources"] = max(0, recipe["discovery"]["max_sources"] - attempts_before)
            existing = {}
            for source in sorted(self.store.all("sources"), key=lambda s: s.get("retrieved_at", "")):
                existing.setdefault(source["locator"], []).insert(0, source)
            base = fetcher or SafeFetcher(recipe["source_scope"], timeout=recipe["execution"]["timeout_seconds"])

            class CachedFetcher:
                def lookup(self, url, metadata=None):
                    metadata = metadata or {}
                    for source in existing.get(url, []):
                        if all(source.get(key) == value for key, value in metadata.items()
                               if key in {"language", "community", "publication_date", "constraints", "domain"}):
                            return source
                    return None

                def is_cached(self, url, metadata=None):
                    return self.lookup(url, metadata) is not None

                def fetch(self, url, metadata=None):
                    source = self.lookup(url, metadata)
                    return deepcopy(source) if source is not None else base.fetch(url, metadata)

            def save_document(document):
                try:
                    sid = self.add_source(document)
                    stored = self.store.get("sources", sid)
                    existing.setdefault(stored["locator"], []).insert(0, stored)
                except (ValueError, OSError, RuntimeError) as exc:
                    self._ingest_failure(document.get("locator"), error_category(exc))

            def save_decision(decision):
                decision = dict(decision, discovery_id="discovery_"+uuid.uuid4().hex)
                decision["campaign_id"] = campaign
                self.store.put("discovery", decision["discovery_id"], decision)

            def save_state(state):
                state = dict(state, campaign_id=campaign, scope_hash=scope_hash, policy_hash=policy,
                             spent_usd=spent_before + state["spent_usd"],
                             requests=requests_before + state["requests"],
                             source_attempts=attempts_before + state["source_attempts"])
                # Queue state and conservative reservation commit before the
                # coordinator starts each potentially billable adapter call.
                cost = {"attempt_id": cost_id, "stage": "discovery", "policy_hash": policy,
                        "campaign_id": campaign, "reserved_usd": state["spent_usd"],
                        "status": "settled_estimate" if state["status"] == "complete" else "reserved_estimate",
                        "request_count": 0, "adapter_request_count": state["requests"],
                        "billing_kind": "configured_adapter_cost_estimate", "created_at": now(),
                        "invoice_usd": None, "invoice_usd_reason": "adapter_cost_estimate_not_invoice"}
                if state["status"] == "complete":
                    cost["settled_usd"] = state["spent_usd"]
                with self.store.connection() as db:
                    self.store.setting("discovery_state", state, db)
                    self.store.put("costs", cost_id, cost, db)

            self.store.setting("cancel_requested", False)
            result = discover(recipe, CachedFetcher(), search_adapter=search_adapter, seeds=seeds,
                              on_document=save_document, on_decision=save_decision, on_state=save_state,
                              is_cancelled=lambda: bool(self.store.read_setting("cancel_requested")))
            result["spent_usd"] += spent_before
            result["requests"] += requests_before
            result["source_attempts"] += attempts_before
            result["campaign_id"] = campaign
        return {k:v for k,v in result.items() if k not in {"documents", "excluded_documents"}}

    def estimate(self, links=None, **assumptions):
        self._configured()
        for old, new in (("average_chars", "chars_per_link"), ("cache_hit_rate", "cache_fraction")):
            if old in assumptions:
                assumptions[new] = assumptions.pop(old)
        sources = []
        if links is None:
            for source in self.store.iter_rows("sources",batch_size=1):
                if self.source_exclusion(source) is None:
                    sources.append({k:v for k,v in source.items() if k not in {"text","blocks","outlinks"}} | {"text_length":len(source["text"])})
        def source_text(metadata):
            # One source is resident at a time. ASCII length placeholders cannot
            # establish Unicode prompt fit, and inventories can contain many PDFs.
            source = self.store.get("sources", metadata["source_id"])
            if digest(source["text"]) != metadata["text_sha256"]:
                raise ValueError("Source text changed before cost estimation")
            return source["text"]
        return costs.estimate(self.recipe, self.profile, sources, links=links,
            source_text_loader=source_text if links is None else None, **assumptions)

    def collect(self, provider=None, *, allow_paid=False, max_jobs=None, tokenizers=None):
        self._configured()
        if provider is None:
            if all(p["adapter"] == "fake" for p in self.profile["providers"].values()):
                provider = FakeProvider()
            elif allow_paid:
                provider = HTTPProvider(self.profile)
            else:
                raise ValueError("Configured profile requires explicit allow_paid=True or an offline FakeProvider")
        if getattr(provider, "paid", False) and not allow_paid:
            raise ValueError("Paid transport requires explicit authorization")
        with self._lock():
            self.cluster().ensure_control_idle()
            self.store.setting("cancel_requested", False)
            return Engine(self, provider, tokenizers=tokenizers).run(max_jobs)

    def resume(self, provider=None, *, allow_paid=False, max_jobs=None, tokenizers=None):
        return self.collect(provider, allow_paid=allow_paid, max_jobs=max_jobs, tokenizers=tokenizers)

    def cancel(self):
        self.store.setting("cancel_requested", True)

    def retry_failed(self, job_id):
        with self._lock():
            job = self.store.get("jobs", job_id)
            if not job or job["status"] not in {"failed", "partial"}:
                raise ValueError("Only a known failed or unresolved partial job can be retried")
            job.update(status="pending", reason="researcher_requested_retry", cache_bypass_once=True)
            self.store.put("jobs", job_id, job)

    def resolve_uncertain(self, job_id, *, retry=False, acknowledge_possible_duplicate_billing=False):
        with self._lock():
            job = self.store.get("jobs", job_id)
            if not job or job["status"] != "uncertain":
                raise ValueError("job is not uncertain")
            if retry and not acknowledge_possible_duplicate_billing:
                raise ValueError("Retry requires acknowledgement of possible duplicate billing")
            job.update(status="pending" if retry else "failed", reason="human_resolved_uncertain_outcome",
                       resolution={"retry":retry, "possible_duplicate_billing_acknowledged":acknowledge_possible_duplicate_billing,
                                   "created_at":now()})
            self.store.put("jobs", job_id, job)
        # Unknown attempt reserves remain in budget; future invoices can be reconciled externally.

    def configure_large_run(self):
        """Explicit local upgrade; previous snapshots and money limits are unchanged."""
        from .resilience import large_run_execution
        self._configured()
        recipe = deepcopy(self.recipe)
        recipe["execution"] = large_run_execution(recipe["execution"])
        return self.configure(recipe,self.profile)

    def reset_model(self, model_alias):
        self._configured()
        if model_alias not in self.profile["models"]: raise ValueError("Unknown configured model alias")
        with self._lock(), self.store.connection() as db:
            health = self.store.setting("model_circuits",db=db,write=False) or {}
            keys=[]
            for key,state in health.items():
                if state["model_alias"] == model_alias and state["policy_hash"] == policy_hash(self.recipe):
                    state.update(state="closed",failures=0,probe_job_id=None,retry_at=0,reason="researcher_reset",last_started_at=0,reset_at=now())
                    keys.append(key)
            for key in keys:
                for job in self.store.rows("jobs",where="json_extract(data,'$.model_key')=? AND json_extract(data,'$.status') IN ('deferred','failed')",params=(key,),db=db):
                    if job.get("resolution",{}).get("retry") is False: continue
                    job.update(status="pending",reason="researcher_reset_model",not_before=0)
                    self.store.put("jobs",job["job_id"],job,db)
            self.store.setting("model_circuits",health,db)
        return {"model_alias":model_alias,"reset_circuits":len(keys),"cost_reservations_retained":True}

    def inventory(self):
        with self.store.connection() as db:
            if not db.in_transaction: db.execute("BEGIN")
            result = {t:self.store.all(t, db) for t in TABLES if t not in {"cache", "versions"}}
        annotations = {}
        for a in result["annotations"]:
            if a.get("active",True): annotations.setdefault(a["term_id"],[]).append(a)
        for term in result["terms"]:
            choices = sorted(annotations.get(term["term_id"],[]), key=lambda a:a["created_at"])
            term["review_status"] = choices[-1]["status"] if choices else "unreviewed"
            term["human_attributes"] = {}
            for annotation in choices:
                term["human_attributes"].update(annotation.get("attributes") or {})
        for source in result["sources"]:
            source["scope_exclusion"] = self.source_exclusion(source) if self.recipe else None
        from .exports import record_view
        result["records"] = record_view(result["terms"])
        result["terms"] = [term for term in result["terms"] if term.get("record_type", "term") == "term"]
        return result

    def page_inventory(self, *, offset=0, limit=50, query="", record_id=None, evidence_offset=0, recovery_offset=0):
        """Bounded browser view; evidence excerpts retain absolute Unicode offsets."""
        if any(type(n) is not int or n < 0 for n in (offset,evidence_offset,recovery_offset)) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid page bounds")
        if not isinstance(query,str) or len(query)>400: raise ValueError("Search must be at most 400 characters")
        where,params="1",()
        if query:
            # Parameter binding and literal substring semantics, including %/_ .
            where="instr(unicode_fold(json_extract(data,'$.expression')),unicode_fold(?))>0 OR instr(unicode_fold(json_extract(data,'$.sense')),unicode_fold(?))>0 OR instr(unicode_fold(json_extract(data,'$.language')),unicode_fold(?))>0 OR instr(unicode_fold(json_extract(data,'$.community')),unicode_fold(?))>0"
            params=(query,)*4
        total=self.store.count("terms",where=where,params=params)
        terms=self.store.rows("terms",where=where,params=params,limit=limit,offset=offset)
        page_ids={term["term_id"] for term in terms}
        if record_id and not any(t["term_id"] == record_id for t in terms):
            selected=self.store.get("terms",record_id)
            if selected: terms.append(selected)
        annotations=[]
        for term in terms:
            choices=self.store.rows("annotations",where="json_extract(data,'$.term_id')=?",params=(term["term_id"],))
            active=sorted((a for a in choices if a.get("active",True)),key=lambda a:a["created_at"])
            term["review_status"]=active[-1]["status"] if active else "unreviewed"
            term["human_attributes"]={}
            for a in active: term["human_attributes"].update(a.get("attributes") or {})
            if term["term_id"] == record_id: annotations=choices[-200:]
        occurrence_where="json_extract(data,'$.term_id')=?"
        occurrences=self.store.rows("occurrences",where=occurrence_where,params=(record_id,),limit=limit,offset=evidence_offset) if record_id else []
        evidence_total=self.store.count("occurrences",where=occurrence_where,params=(record_id,)) if record_id else 0
        sources={}
        source_cache=SourceCache(self.store)
        for occurrence in occurrences:
            source=source_cache[occurrence["source_id"]]
            sources[source["source_id"]]={k:v for k,v in source.items() if k not in {"text","blocks","outlinks"}}
            context_start=max(0,occurrence.get("context_start",occurrence["start"]-160))
            context_end=min(len(source["text"]),occurrence.get("context_end",occurrence["end"]+160))
            # The selected observed span is never clipped, even for long sentences.
            excerpt_start=max(context_start,occurrence["start"]-1200)
            excerpt_end=min(context_end,occurrence["end"]+1200)
            occurrence["inspection_excerpt"]={"text":source["text"][excerpt_start:excerpt_end],"start":excerpt_start,"end":excerpt_end}
        recovery_where="json_extract(data,'$.status') IN ('failed','partial','uncertain','deferred')"
        from .exports import record_view
        selected_record=next((t for t in terms if t["term_id"]==record_id),None)
        result={"records":record_view([t for t in terms if t["term_id"] in page_ids]),
                "selected_record":record_view([selected_record])[0] if selected_record else None,
                "terms":[t for t in terms if t.get("record_type","term") == "term" and t["term_id"] in page_ids],
                "occurrences":occurrences,"sources":list(sources.values()),"annotations":annotations,
                "relations":self.store.rows("relations",where="json_extract(data,'$.term_a')=? OR json_extract(data,'$.term_b')=?",params=(record_id,record_id),limit=200) if record_id else [],
                "jobs":self.store.rows("jobs",where=recovery_where,limit=limit,offset=recovery_offset),
                "audit":self.store.rows("audit",limit=limit),"discovery":self.store.rows("discovery",limit=limit),
                "costs":[],"runs":[]}
        result["page"]={"offset":offset,"limit":limit,"total":total,"record_id":record_id,
                        "evidence_offset":evidence_offset,"evidence_total":evidence_total,
                        "recovery_offset":recovery_offset,"recovery_total":self.store.count("jobs",where=recovery_where),
                        "audit_preview_only":True,"complete_inventory":"CLI inspect or frozen exports"}
        return result

    def status(self):
        jobs = Counter(self.store.status_counts("jobs"))
        run_id = self.store.read_setting("last_run_id")
        last = self.store.get("runs", run_id) if run_id else None
        active = self.store.rows("runs",where="json_extract(data,'$.status')='running'",limit=1)
        running = bool(active)
        if active: last = active[0]
        failure_where="json_extract(data,'$.stage')='parsing'"
        failure_count=self.store.count("audit",where=failure_where)
        failures = self.store.rows("audit",where=failure_where,limit=100)
        stage_costs = self.store.stage_costs(STAGES)
        counts={k:self.store.count(k) for k in ("sources","terms","occurrences","jobs")}
        counts["records"]=counts["terms"]
        counts["terms"]=self.store.count("terms",where="coalesce(json_extract(data,'$.record_type'),'term')='term'")
        # Avoid presenting an old simulation/profile circuit as the current live run.
        health_keys={h["model_key"] for h in (last or {}).get("model_health",[])}
        model_health=[h for key,h in (self.store.read_setting("model_circuits") or {}).items()
                      if self.recipe and h["policy_hash"] == policy_hash(self.recipe) and key in health_keys]
        degraded=any(h["state"] == "disabled" for h in model_health)
        healthy=sorted({h["model_alias"] for h in model_health if h["state"] == "closed"})
        if last: last={k:v for k,v in last.items() if k not in {"root_job_ids","recipe","profile","prompts"}}
        status = "running" if running else (last["status"] if last else "ready")
        if failure_count or jobs["failed"] or jobs["uncertain"] or jobs["deferred"] or degraded:
            status = "partial" if not running else "running"
        if self.store.read_setting("cancel_requested") and not running:
            status = "cancelled"
        return {"status":status,"mode":(self.recipe or {}).get("mode"),"profile":(self.profile or {}).get("id"),
                "counts":counts,
                "data_type": (self.recipe or {}).get("data_type", "term"),
                "jobs":dict(jobs),"costs":stage_costs,"last_run":last,"failures":failures,
                "coverage":last.get("coverage") if last else None,
                "stop_reason":last.get("stop_reason") if last else None,
                "discovery":self.store.read_setting("discovery_state"),
                "unresolved_audit_count":self.store.count("audit"), "failure_count":failure_count,
                "degraded":degraded,"healthy_models":healthy,"model_health":model_health,
                "coverage_note":"model-reported enumeration completion, not measured recall"}

    def annotate(self, term_id, status, note="", attributes=None, actor="researcher"):
        if status not in {"unreviewed","approved","rejected","needs_review"}:
            raise ValueError("unknown annotation status")
        if not self.store.get("terms",term_id):
            raise ValueError("unknown term")
        if not isinstance(note,str) or not isinstance(actor,str) or not actor.strip() or attributes is not None and not isinstance(attributes,dict):
            raise ValueError("invalid annotation")
        canonical(attributes)
        aid = "annotation_" + uuid.uuid4().hex
        self.store.put("annotations",aid,{"annotation_id":aid,"term_id":term_id,"status":status,
            "note":note,"attributes":attributes or {},"actor":actor,"origin":"human","created_at":now(),"active":True})
        return aid

    def undo_annotation(self, annotation_id):
        row = self.store.get("annotations",annotation_id)
        if not row:
            raise ValueError("unknown annotation")
        row.update(active=False,undone_at=now())
        self.store.put("annotations",annotation_id,row)

    def relate(self, term_a, term_b, kind, actor="researcher"):
        if kind not in {"alias","semantic_merge","distinct_sense"} or term_a == term_b:
            raise ValueError("invalid relation")
        if not self.store.get("terms",term_a) or not self.store.get("terms",term_b):
            raise ValueError("unknown relation term")
        rid = "relation_" + uuid.uuid4().hex
        self.store.put("relations",rid,{"relation_id":rid,"term_a":term_a,"term_b":term_b,"kind":kind,
            "actor":actor,"created_at":now(),"origin":"human","active":True,
            "operation":"reversible_view_relation_original_records_retained"})
        return rid

    def undo_relation(self, relation_id):
        row = self.store.get("relations",relation_id)
        if not row:
            raise ValueError("unknown relation")
        row.update(active=False,undone_at=now())
        self.store.put("relations",relation_id,row)

    def snapshot(self, name):
        with self._lock():
            return self._snapshot_unlocked(name)

    def _snapshot_unlocked(self, name):
        from . import __version__
        self._configured()
        if not isinstance(name,str) or not name.strip() or len(name)>128:
            raise ValueError("dataset name required")
        inventory = self.inventory()
        status = self.status()
        if status["status"] == "running":
            raise ValueError("Cannot freeze a dataset while a run is active")
        version_id = "dataset_" + uuid.uuid4().hex
        value = {"schema_version":1,"version_id":version_id,"name":name,"created_at":now(),
            "engine_version":__version__,"recipe":self.recipe,"profile":self.profile,
            "prompts":prompts.manifest(),**inventory,"coverage":status["coverage"],
            "failures":[a for a in inventory["audit"] if a.get("stage") == "parsing"],"constraints":[{"source_id":s["source_id"],"constraints":s.get("constraints")} for s in inventory["sources"]]}
        value["agent_workflow"] = {"events": self.store.read_setting("agent_workflow") or [],
            "source_map": self.store.read_setting("agent_source_map") or {},
            "active_setup": self.agent_setup(),
            "external_agent_costs": {"actual_usd": None, "reason": "not_metered_by_collector",
                                     "included_in_collector_budget": False},
            "scope_note": "Agent planning is recorded separately from deterministic validation and model extraction."}
        value["compute_execution"] = {
            "cluster_execution": self.store.read_setting("cluster_execution"),
            "cluster_accounting": self.store.read_setting("cluster_accounting"),
            "throughput_settings": self.store.read_setting("cluster_throughput"),
            "resource_usage_note": "Reserved allocation bounds and measured worker time are distinct; missing scheduler charges are unknown."}
        self.store.put("versions",version_id,{"dataset":value,"sha256":digest(value)})
        return version_id

    def dataset(self, version):
        row = self.store.get("versions",version)
        if not row:
            raise ValueError("unknown dataset version")
        if digest(row["dataset"]) != row["sha256"]:
            raise ValueError("dataset snapshot hash mismatch")
        return row["dataset"]

    def versions(self):
        return self.store.version_catalog()

    def export(self, version, out, formats=None):
        from .exports import export_dataset
        dataset = self.dataset(version)
        if formats is None:
            formats = list(dataset["recipe"]["exports"]["formats"])
            if dataset["recipe"]["exports"]["annotation"]:
                formats.append("annotation")
        return export_dataset(dataset, Path(out), formats)
