"""Predeclared Quarry extraction schedules and grounded union composition.

The manifest is inert. An explicit runner owns dispatch enforcement and fresh
project/cache creation; these functions cannot discover providers or credentials.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from .adapters import DEFAULT_ENVELOPE
from .config import STAGES
from .experiments import PROVENANCE, _corpus, _hash, _costs
from .exports import canonical_json

KINDS = {"single", "repeated_general", "broad_mixed_union", "specialists", "additional_general_control", "warm_extension"}


def make_ablation_manifest(extractors, specialist_lenses, *, general=None, passes=3, envelope=None, warm_extension=True, seed="quarry-ablation-v1"):
    """Schedule every single, repeated general, mixed union and equal-pass control.

    Resource ceilings are equal for multi-component primary arms. Equality of
    ceilings is not equality of realized calls/tokens; report their measurements.
    Development selects `general` before held-out execution, never by held-out gold.
    """
    if not isinstance(extractors, list) or not extractors or len(set(extractors)) != len(extractors) or len(extractors) > 10:
        raise ValueError("Supply 1–10 distinct extractor identifiers")
    if any(not isinstance(v, str) or not v or len(v) > 100 for v in extractors + specialist_lenses):
        raise ValueError("Extractor/lens identifiers must be bounded strings")
    if type(passes) is not int or not 2 <= passes <= 10 or not specialist_lenses or len(specialist_lenses) > 9:
        raise ValueError("Declare 2–10 general passes and 1–9 specialist lenses")
    general = general or extractors[0]
    if general not in extractors:
        raise ValueError("Development-selected general extractor is absent")
    limit = DEFAULT_ENVELOPE | (envelope or {})
    arms = []

    def add(arm_id, kind, components, *, regime="cold", parent=None):
        arms.append({"arm_id": arm_id, "kind": kind, "cache_regime": regime, "parent_arm_id": parent,
            "resource_envelope": deepcopy(limit), "components": [{"component_id": f"pass-{i + 1}", "extractor_id": extractor,
                "attention": attention, "seed": seed + ":" + arm_id + ":" + str(i + 1)} for i, (extractor, attention) in enumerate(components)]})

    for extractor in extractors:
        add("single-" + extractor, "single", [(extractor, "general")])
    add("repeated-general", "repeated_general", [(general, "general")] * passes)
    add("broad-mixed-union", "broad_mixed_union", [(v, "general") for v in extractors])
    specialist_components = [(general, "general")] + [(general, lens) for lens in specialist_lenses]
    add("specialists", "specialists", specialist_components)
    add("general-control-for-specialists", "additional_general_control", [(general, "general")] * len(specialist_components))
    add("general-control-for-mixed", "additional_general_control", [(general, "general")] * len(extractors))
    if warm_extension:
        add("warm-repeated-general-extension", "warm_extension", [(general, "general")] * (passes + 1), regime="warm", parent="repeated-general")
    return validate_ablation_manifest({"schema_version": "1", "seed": seed, "development_selected_general": general,
        "selection_reason": "Operator must record development-only selection rationale in the study spec",
        "union_policy": "all_exact_grounded_discoveries_without_agreement_or_count_threshold",
        "arms": arms})


def validate_ablation_manifest(manifest):
    required = {"schema_version", "seed", "development_selected_general", "selection_reason", "union_policy", "arms"}
    if not isinstance(manifest, dict) or set(manifest) != required or manifest["schema_version"] != "1":
        raise ValueError("Invalid ablation manifest/version")
    if manifest["union_policy"] != "all_exact_grounded_discoveries_without_agreement_or_count_threshold":
        raise ValueError("Ablation cannot introduce agreement/count filtering")
    for key in ("seed", "development_selected_general", "selection_reason"):
        if not isinstance(manifest[key], str) or not manifest[key] or len(manifest[key]) > 20000:
            raise ValueError("Invalid selection/seed declaration")
    arms = manifest["arms"]
    if not isinstance(arms, list) or not 1 <= len(arms) <= 20:
        raise ValueError("Declare 1–20 bounded arms")
    seen = {}
    for arm in arms:
        fields = {"arm_id", "kind", "cache_regime", "parent_arm_id", "resource_envelope", "components"}
        if not isinstance(arm, dict) or set(arm) != fields or arm["kind"] not in KINDS:
            raise ValueError("Invalid ablation arm")
        if not isinstance(arm["arm_id"], str) or not arm["arm_id"] or arm["arm_id"] in seen or len(arm["arm_id"]) > 100:
            raise ValueError("Arm identifiers must be unique and bounded")
        seen[arm["arm_id"]] = arm
        env = arm["resource_envelope"]
        if not isinstance(env, dict) or set(env) != set(DEFAULT_ENVELOPE) or any(type(v) not in {int, float} or not math.isfinite(v) or v < 0 for v in env.values()):
            raise ValueError("Declare finite allocation ceilings")
        for key in ("max_calls", "max_input_tokens", "max_output_tokens", "per_call_input_tokens", "per_call_output_tokens"):
            if type(env[key]) is not int or env[key] < 1:
                raise ValueError("Positive integer call/token ceilings required")
        if env["max_seconds"] <= 0:
            raise ValueError("Positive time ceiling required")
        if arm["cache_regime"] not in {"cold", "warm"} or (arm["kind"] == "warm_extension") != (arm["cache_regime"] == "warm"):
            raise ValueError("Warm extensions must be labeled separately")
        if arm["cache_regime"] == "cold" and arm["parent_arm_id"] is not None:
            raise ValueError("Cold arms cannot inherit caches")
        components = arm["components"]
        if not isinstance(components, list) or not 1 <= len(components) <= 11:
            raise ValueError("Unbounded component schedule")
        ids = set()
        for component in components:
            if not isinstance(component, dict) or set(component) != {"component_id", "extractor_id", "attention", "seed"}:
                raise ValueError("Invalid component fields")
            if any(not isinstance(v, str) or not v or len(v) > 1000 for v in component.values()) or component["component_id"] in ids:
                raise ValueError("Invalid/duplicate component identity")
            ids.add(component["component_id"])
    for arm in arms:
        if arm["cache_regime"] == "warm":
            parent = seen.get(arm["parent_arm_id"])
            if parent is None or parent["cache_regime"] != "cold":
                raise ValueError("Warm extension needs an explicit frozen cold parent")
            signatures = lambda rows: [(c["extractor_id"], c["attention"]) for c in rows]
            if signatures(arm["components"][:len(parent["components"])]) != signatures(parent["components"]) or len(arm["components"]) <= len(parent["components"]):
                raise ValueError("Warm extension must preserve parent components and add work")
    canonical_json(manifest)
    return deepcopy(manifest)


def union_runs(corpus, runs, *, run_id, system="quarry-ablation", software_revision=None):
    """Compose separately metered components without deleting invalid proposals.

    Exact duplicate occurrences are deduplicated; every contributing proposal ID
    remains in the union audit. Single-model and single-pass discoveries survive.
    Native-filtered/nonexact proposals remain unscored with their raw offsets.
    """
    sources = _corpus(corpus)
    if not isinstance(runs, list) or not runs:
        raise ValueError("Union needs component runs")
    predictions, attribution, duplicates, unique = [], [], [], {}
    component_outcomes = {sid: [] for sid in sources}
    ids = set()
    for run in runs:
        if run.get("run_id") in ids or run.get("data_type") != corpus["data_type"] or run.get("schema_version") != "1":
            raise ValueError("Duplicate/mismatched component run")
        ids.add(run["run_id"])
        outcomes = {r["source_id"]: r for r in run["source_results"]}
        if len(outcomes) != len(run["source_results"]) or set(outcomes) != set(sources):
            raise ValueError("Union component omitted a source")
        for sid, result in outcomes.items():
            if result["text_sha256"] != sources[sid]["text_sha256"]:
                raise ValueError("Union component changed frozen text")
            component_outcomes[sid].append(result)
        for proposal in run["predictions"]:
            sid, start, end = proposal["source_id"], proposal["start"], proposal["end"]
            if sid not in sources:
                raise ValueError("Unknown union proposal source")
            exact = type(start) is int and type(end) is int and 0 <= start < end <= len(sources[sid]["text"]) and sources[sid]["text"][start:end] == proposal["observed_text"]
            key = canonical_json([sid, start, end, proposal["observed_text"], proposal["language"], proposal["interpretation"]]) if exact else None
            owner = {"component_run_id": run["run_id"], "component_prediction_id": proposal["prediction_id"]}
            if key is not None and key in unique:
                duplicates.append(owner | {"union_prediction_id": predictions[unique[key]]["prediction_id"]})
                attribution[unique[key]]["contributors"].append(owner)
                continue
            index = len(predictions)
            normalized = deepcopy(proposal) | {"prediction_id": f"{run_id}:{index}"}
            predictions.append(normalized)
            attribution.append({"union_prediction_id": normalized["prediction_id"], "contributors": [owner], "exact_grounded": exact})
            if key is not None:
                unique[key] = index
    outcomes = []
    for sid, rows in component_outcomes.items():
        statuses = {r["status"] for r in rows}
        status = "complete" if statuses == {"complete"} else "uncertain" if "uncertain" in statuses else "partial" if "complete" in statuses or any(p["source_id"] == sid for p in predictions) else "failed" if statuses == {"failed"} else "pending"
        outcomes.append({"source_id": sid, "text_sha256": sources[sid]["text_sha256"], "status": status,
                         "reason": None if status == "complete" else "component_outcomes:" + ",".join(sorted(statuses))})
    by_stage = {}
    for run in runs:
        _costs(run["costs"])
        for row in run["costs"]:
            by_stage.setdefault(row["stage"], []).append(row)
    costs, cost_details = [], []
    for stage, rows in by_stage.items():
        bases = {r["basis"] for r in rows if r["known_usd"] is not None}
        if len(bases) > 1:
            raise ValueError("Cannot combine simulation/invoice/estimate costs")
        known = None if any(r["known_usd"] is None for r in rows) else sum(r["known_usd"] for r in rows)
        reserved = None if any(r["uncertain_reserved_usd"] is None for r in rows) else sum(r["uncertain_reserved_usd"] for r in rows)
        costs.append({"stage": stage, "known_usd": known, "uncertain_reserved_usd": reserved,
            "basis": next(iter(bases)) if bases else "not_metered", "missing_reason": "one_or_more_component_costs_unavailable" if known is None or reserved is None else None})
        cost_details.append({"stage": stage, "known_subtotal_usd": sum(r["known_usd"] or 0 for r in rows), "components": deepcopy(rows)})
    provenance = {"software_revision": software_revision, "model_version": canonical_json([r["provenance"]["model_version"] for r in runs]),
        "prompt_sha256": _hash([r["provenance"]["prompt_sha256"] for r in runs]),
        "configuration_sha256": _hash([r["provenance"]["configuration_sha256"] for r in runs]), "adapter_version": "quarry-union-7.0.0",
        "unavailable_reasons": {} if software_revision else {"software_revision": "operator_did_not_supply_revision"}}
    run = {"schema_version": "1", "run_id": run_id, "system": system, "data_type": corpus["data_type"],
           "proposal_population": "raw_proposals" if all(r["proposal_population"] == "raw_proposals" for r in runs) else "grounded_inventory",
           "provenance": provenance, "source_results": outcomes, "predictions": predictions, "costs": costs}
    return {"run": run, "audit": {"component_run_ids": [r["run_id"] for r in runs], "attribution": attribution,
            "duplicate_proposals": duplicates, "cost_details": cost_details,
            "union_rule": "exact_union_no_agreement_frequency_or_candidate_count_gate"}}


def execute_ablations(corpus, manifest, runner, *, software_revision=None):
    """Execute an explicit component runner with isolated namespaces.

    runner(arm, component, context) returns a normalized run or {'run','audit'}.
    context contains immutable frozen corpus and cold project/cache names; only
    warm extension components explicitly inherit their cold parent's namespaces.
    Runner must enforce aggregate arm envelopes and attest realized accounting.
    """
    _corpus(corpus)
    manifest = validate_ablation_manifest(manifest)
    outputs, previous = [], {}
    for arm in manifest["arms"]:
        packets = []
        for index, component in enumerate(arm["components"]):
            parent = next((a for a in manifest["arms"] if a["arm_id"] == arm["parent_arm_id"]), None)
            inherited = parent is not None and index < len(parent["components"])
            namespace = (parent["arm_id"] + "/" + parent["components"][index]["component_id"]) if inherited else arm["arm_id"] + "/" + component["component_id"]
            context = {"corpus": deepcopy(corpus), "run_id": arm["arm_id"] + ":" + component["component_id"],
                "project_namespace": arm["arm_id"] + "/" + component["component_id"], "cache_namespace": namespace,
                "cache_regime": arm["cache_regime"], "parent_component_run": deepcopy(previous.get(namespace)) if inherited else None,
                "resource_envelope": deepcopy(arm["resource_envelope"]), "component_index": index,
                "component_count": len(arm["components"])}
            packet = runner(deepcopy(arm), deepcopy(component), context)
            packet = packet if "run" in packet else {"run": packet, "audit": {"verification_kind": "runner_audit_unavailable"}}
            if packet["run"]["run_id"] != context["run_id"]:
                raise ValueError("Runner did not preserve component run identity")
            packets.append(packet)
            if arm["cache_regime"] == "cold":
                previous[namespace] = packet["run"]
        combined = union_runs(corpus, [p["run"] for p in packets], run_id=arm["arm_id"],
                              system="quarry:" + arm["kind"] + ":" + arm["cache_regime"], software_revision=software_revision)
        combined["audit"].update(arm=deepcopy(arm), components=packets,
            enforcement="explicit_runner_responsibility", realized_resource_equality="unproven_until_dispatch_token_time_and_cost_accounting_compared")
        outputs.append(combined)
    return {"schema_version": "1", "manifest_sha256": _hash(manifest), "manifest": manifest, "arms": outputs}


def prepare_quarry_ablations(corpus, documents, out, *, recipe, profile, concurrency=2, passes=3, software_revision=None):
    """Prepare fresh real Quarry projects and freeze provenance before extraction.

    Offline fake profiles only. Input documents must be the complete source-only
    master snapshot so IDs and parser provenance survive Project.add_source.
    """
    from .config import load_profile, load_recipe
    from .experiments import quarry_run
    from .project import Project
    sources = _corpus(corpus)
    recipe, profile = load_recipe(recipe), load_profile(profile)
    if any(p["adapter"] != "fake" for p in profile["providers"].values()):
        raise ValueError("Synthetic ablation runner accepts offline fake profiles only")
    if type(concurrency) is not int or not 1 <= concurrency <= 32:
        raise ValueError("Bound concurrency to 1–32")
    if {d["source_id"] for d in documents} != set(sources) or len(documents) != len(sources):
        raise ValueError("Frozen master document inventory differs from corpus")
    for document in documents:
        source = sources[document["source_id"]]
        if document["text"] != source["text"] or document["text_sha256"] != source["text_sha256"]:
            raise ValueError("Ablation cannot replace frozen text")
    root = Path(out).resolve()
    root.mkdir(parents=True, exist_ok=False)
    extractor_map = {e["id"]: e for e in profile["broad"]}
    lenses = {e["id"]: e for e in recipe["specialist_lenses"]}
    if not lenses:
        lenses = {"attention-to-ambiguous-senses": {"lens": "Attend to ambiguous and contextual senses while retaining all qualifying terms."}}
    envelope = DEFAULT_ENVELOPE | {"max_usd": recipe["execution"]["budget_usd"]}
    input_rate = max(m["input_per_million"] for m in profile["models"].values())
    output_rate = max(m["output_per_million"] for m in profile["models"].values())
    envelope["per_call_reserved_usd"] = (envelope["per_call_input_tokens"] * input_rate + envelope["per_call_output_tokens"] * output_rate) / 1000000
    manifest = make_ablation_manifest(list(extractor_map), list(lenses), passes=passes, envelope=envelope)
    arms = []
    for arm in manifest["arms"]:
        arm_recipe, arm_profile = deepcopy(recipe), deepcopy(profile)
        arm_profile["broad"] = []
        arm_recipe["specialist_lenses"] = []
        for component in arm["components"]:
            original = extractor_map[component["extractor_id"]]
            expert = {"id": component["component_id"], "model": original["model"],
                "lens": original["lens"] if component["attention"] == "general" else lenses[component["attention"]]["lens"],
                "communities": ["*"]}
            if component["attention"] == "general":
                arm_profile["broad"].append(expert)
            else:
                arm_recipe["specialist_lenses"].append(expert)
        arm_recipe["mode"] = "specialists" if arm_recipe["specialist_lenses"] else "broad"
        execution = arm_recipe["execution"]
        execution.update(max_calls=envelope["max_calls"], concurrency=concurrency,
            deadline_seconds=envelope["max_seconds"], timeout_seconds=min(30, envelope["max_seconds"]), max_retries=0,
            budget_usd=envelope["max_usd"], max_output_tokens=envelope["per_call_output_tokens"],
            recovery_output_tokens=envelope["per_call_output_tokens"])
        execution["stage_budgets"] = {s: 0 for s in STAGES}
        # Each active stage can use the common ceiling; the Engine's shared total
        # budget still prevents double spending. No unequal specialist subquota.
        execution["stage_budgets"]["extraction"] = envelope["max_usd"]
        execution["stage_budgets"]["specialist"] = envelope["max_usd"] if arm_recipe["mode"] == "specialists" else 0
        execution["resilience"].update(min_request_interval_seconds=0, model_concurrency=concurrency, max_retry_calls=0)
        project_path = root / arm["arm_id"]
        parent_path = root / arm["parent_arm_id"] if arm["parent_arm_id"] else None
        normalized = None
        if arm["cache_regime"] == "cold":
            project = Project(project_path)
            project.configure(arm_recipe, profile=arm_profile)
            for document in documents:
                if project.add_source(document) != document["source_id"]:
                    raise ValueError("Quarry source identity changed on import")
            snapshot = project.dataset(project.snapshot("prepared-before-any-extraction"))
            normalized = quarry_run(snapshot, run_id=arm["arm_id"], software_revision=software_revision)
        arms.append({"arm_id": arm["arm_id"], "project_path": str(project_path),
            "warm_parent_path": str(parent_path) if parent_path else None,
            "normalized_pre_run": normalized, "recipe": arm_recipe, "profile": arm_profile})
    plan = {"schema_version": "1", "corpus_sha256": _hash(corpus), "manifest": manifest, "arms": arms,
            "verification_kind": "synthetic_real_quarry_engine", "paid_requests": 0,
            "seed_execution_reason": "Seeds identify schedules; current Quarry fake and HTTP transports do not implement stochastic seed control"}
    plan["plan_sha256"] = _hash(plan)
    return plan


def run_prepared_quarry_ablations(corpus, plan, *, expectations, software_revision=None):
    """Collect each prepared arm with actual Engine and metered fake dispatches."""
    from .adapters import DispatchMeter
    from .experiments import quarry_run
    from .project import Project
    from .providers import FakeProvider, ProviderError
    from .costs import token_cost
    from .store import digest
    _corpus(corpus)
    if plan["corpus_sha256"] != _hash(corpus):
        raise ValueError("Prepared ablation corpus changed")
    if plan.get("plan_sha256") != _hash({k: v for k, v in plan.items() if k != "plan_sha256"}):
        raise ValueError("Prepared ablation plan changed; prepare and freeze again")
    manifest = validate_ablation_manifest(plan["manifest"])
    prepared = {row["arm_id"]: row for row in plan["arms"]}
    outputs = []
    for arm in manifest["arms"]:
        row = prepared[arm["arm_id"]]
        project = Project(row["warm_parent_path"] or row["project_path"])
        if any(p["adapter"] != "fake" for p in row["profile"]["providers"].values()):
            raise ValueError("Prepared runner cannot enable live providers")
        expected_current = prepared[arm["parent_arm_id"]] if arm["cache_regime"] == "warm" else row
        if project.recipe != expected_current["recipe"] or project.profile != expected_current["profile"]:
            raise ValueError("Saved arm configuration changed after preparation")
        if row["normalized_pre_run"] is not None and row["normalized_pre_run"]["provenance"]["configuration_sha256"] != _hash({"recipe": row["recipe"], "profile": row["profile"]}):
            raise ValueError("Prepared provenance differs from predeclared configuration")
        previous_snapshot = project.dataset(project.snapshot("before-warm-extension")) if arm["cache_regime"] == "warm" else None
        project.configure(row["recipe"], profile=row["profile"])
        translated = []
        for expectation in expectations:
            item = deepcopy(expectation)
            if item.get("expert_ids"):
                allowed = set(item["expert_ids"])
                mapped = [c["component_id"] for c in arm["components"]
                          if c["extractor_id"] in allowed or c["attention"] in allowed]
                # An empty expert_ids list would mean unrestricted to FakeProvider.
                item["expert_ids"] = mapped or ["no-eligible-component-in-this-arm"]
            translated.append(item)
        fake = FakeProvider(expectations=translated)
        # Earlier warm-parent components keep the same fixture identity when an
        # extra pass is appended; eligibility is still mapped explicitly above.
        fake.cache_identity = "offline-ablation-fixture-v1:" + digest(expectations)
        meter = DispatchMeter(arm["resource_envelope"], "synthetic-v1")

        class MeteredFake:
            paid = False
            cache_identity = fake.cache_identity

            def complete(self, request):
                response_box = []
                class Transport:
                    single_attempt = honors_limits = True
                    def dispatch(self, metered_request):
                        response = fake.complete(request)
                        response_box.append(response)
                        model = row["profile"]["models"][request["expert"]["model"]]
                        return {"raw_reply": response.text, "usage": {"input_tokens": response.input_tokens, "output_tokens": response.output_tokens},
                            "cost_usd": token_cost(model, response.input_tokens, response.output_tokens), "cost_basis": "simulated", "missing_reason": None}
                try:
                    meter.dispatch(Transport(), source_id=request["source"]["source_id"] if "source" in request else request["source_id"],
                        prompt=request["prompt"], logical_request={"job_id": request["job_id"], "expert_id": request["expert"]["id"]})
                except Exception as error:
                    raise ProviderError("offline_meter:" + type(error).__name__, uncertain=bool(response_box), retryable=False) from None
                return response_box[0]

        collection = project.collect(MeteredFake(), allow_paid=False)
        version = project.snapshot("completed-offline-" + arm["arm_id"])
        dataset = project.dataset(version)
        if previous_snapshot is not None:
            # The ordinary bridge deliberately rejects changed configurations.
            # A predeclared warm extension has inherited evidence and costs.
            # Preserve the immutable complete snapshot; derive an explicit view
            # whose completion declaration is taken only from this extension's
            # runs. Never pass it off as a fresh cold unchanged-config snapshot.
            view = deepcopy(dataset)
            view["runs"] = [r for r in dataset.get("runs", []) if r.get("recipe") == dataset["recipe"] and r.get("profile") == dataset["profile"]]
            normalized = quarry_run(view, run_id=arm["arm_id"], software_revision=software_revision)
            normalized["system"] = "quarry:warm_extension:inherited_inventory_and_cumulative_costs"
        else:
            normalized = quarry_run(dataset, run_id=arm["arm_id"], software_revision=software_revision)
        outputs.append({"run": normalized, "audit": {"arm": arm, "project_path": str(project.path), "snapshot_id": version,
            "snapshot_sha256": _hash(dataset), "collection": collection, "actual_dispatches": meter.calls,
            "verification_kind": "synthetic_real_quarry_engine", "paid_requests": 0,
            "prepared_provenance": row["normalized_pre_run"], "before_warm_snapshot_id": previous_snapshot["version_id"] if previous_snapshot else None,
            "fixture_expert_id_mapping": {c["component_id"]: {"extractor_id": c["extractor_id"], "attention": c["attention"]} for c in arm["components"]},
            "snapshot_view_transformation": "completion_from_current_config_runs_with_inherited_evidence_and_cumulative_costs" if previous_snapshot else None,
            "complete_original_run_history": deepcopy(dataset.get("runs", [])) if previous_snapshot else None,
            "cost_scope": "cumulative_parent_and_extension" if previous_snapshot else "fresh_cold_project",
            "claim_limit": "Synthetic fake responses verify scheduling, accounting and union mechanics; they do not test model diversity or specialist quality."}})
    return {"schema_version": "1", "manifest": manifest, "arms": outputs, "paid_requests": 0}


def run_quarry_ablations(corpus, documents, out, *, recipe, profile, expectations, concurrency=2, passes=3, software_revision=None):
    plan = prepare_quarry_ablations(corpus, documents, out, recipe=recipe, profile=profile, concurrency=concurrency,
                                   passes=passes, software_revision=software_revision)
    return run_prepared_quarry_ablations(corpus, plan, expectations=expectations, software_revision=software_revision)
