"""Planning scenarios and conservative request reserves; no term-yield assumptions."""
from decimal import Decimal
import math

from .config import STAGES, experts
from .prompts import build_prompt


def token_cost(model, input_tokens, output_tokens):
    return float((Decimal(str(model["input_per_million"])) * input_tokens
                  + Decimal(str(model["output_per_million"])) * output_tokens) / Decimal(1_000_000))


def reserve_cost(model, max_output_tokens):
    # Full model input ceiling covers tokenizer/template uncertainty. Providers
    # can still violate a reviewed contract: settlement reports an overrun.
    return token_cost(model, model["input_token_ceiling"], max_output_tokens)


def window_ranges(length, execution):
    size, overlap = execution["window_chars"], execution["overlap_chars"]
    result = []
    start = 0
    while start < length:
        end = min(length, start + size)
        result.append((start, end))
        if end == length:
            break
        start = end - overlap
    return result


def estimate(recipe, profile, sources=(), *, links=None, chars_per_link=None,
             cache_fraction=0, chars_per_token=3, output_tokens_per_window=1000,
             recovery_fraction=0.15, parsing_usd_per_source=0, translation_usd_per_source=0,
             tokenizers=None, source_text_loader=None):
    from .runtime import PromptTokenizer
    from .token_windows import planned_windows
    tokenizers = dict(tokenizers or {})
    if source_text_loader is not None and not callable(source_text_loader):
        raise ValueError("source text loader must be a trusted callable")
    if set(tokenizers) - set(profile["models"]) or any(not isinstance(t, PromptTokenizer) for t in tokenizers.values()):
        raise ValueError("estimate tokenizers must be trusted model-alias registrations")
    for name, value, low, high in (("cache_fraction", cache_fraction, 0, 1),
                ("chars_per_token", chars_per_token, 0.5, 10),
                ("output_tokens_per_window", output_tokens_per_window, 0, 131072),
                ("recovery_fraction", recovery_fraction, 0, 1),
                ("parsing_usd_per_source", parsing_usd_per_source, 0, 10000),
                ("translation_usd_per_source", translation_usd_per_source, 0, 10000)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"invalid estimate assumption: {name}")
    if links is not None and (type(links) is not int or not 1 <= links <= 100000):
        raise ValueError("links must be 1–100000")
    source_list = list(sources)
    count = len(source_list) if source_list else (links or 0)
    if chars_per_link is not None and (type(chars_per_link) is not int or not 1 <= chars_per_link <= 10_000_000):
        raise ValueError("chars_per_link must be bounded positive integer")
    lengths = [chars_per_link] if chars_per_link else ([None] if source_list else [3000, 12000, 48000])
    scenarios = []
    for length in lengths:
        stages = {s: 0.0 for s in STAGES}
        stages["discovery"] = (len(recipe["discovery"]["queries"]) * recipe["discovery"]["search_cost_usd"]
                               + count * recipe["discovery"]["fetch_cost_usd"]) if recipe["discovery"]["enabled"] else 0
        stages["parsing"] = count * parsing_usd_per_source
        stages["translation"] = count * translation_usd_per_source
        passes, calls, windows, context_blocked = [], 0, 0, 0
        planning = source_list if source_list else [{"text": "", "community": None}] * count
        for source in planning:
            if source_list and source_text_loader is not None:
                source = dict(source, text=source_text_loader(source))
            size = source.get("text_length", len(source.get("text", ""))) if source_list else length
            ranges = window_ranges(size, recipe["execution"])
            windows += len(ranges)
            for expert in experts(recipe, profile):
                routes = expert["communities"]
                routed = "*" in routes or source.get("community") in routes
                # Count-only forecasts cannot know community mix: include lens
                # as an upper scenario, explicitly documented below.
                if source_list and not routed:
                    continue
                model = profile["models"][expert["model"]]
                token_method = "character_ratio_scenario"
                pass_count, blocked = len(ranges), 0
                if "context_limit_tokens" in model or expert["model"] in tokenizers:
                    # Count-only scenarios use bounded placeholders, not an
                    # assertion that English HTML represents PDF/multilingual input.
                    text = source.get("text", "") if source_list else "x" * size
                    if source_list and len(text) != size:
                        text = "x" * size
                    planned = list(planned_windows(text, recipe["execution"], model,
                        lambda fragment: build_prompt(recipe, expert, fragment, source if source_list else None),
                        tokenizer=tokenizers.get(expert["model"])))
                    admitted = [row for row in planned if row[2]["admitted"]]
                    pass_count = len(admitted)
                    blocked = len(planned) - pass_count
                    context_blocked += blocked
                    input_tokens = sum(row[2]["input_tokens"] for row in admitted)
                    token_method = (planned[0][2]["method"] if planned else "empty_source")
                else:
                    prompt_overhead = len(build_prompt(recipe, expert, "", source if source_list else None)) / chars_per_token
                    input_tokens = sum((e-s) / chars_per_token + prompt_overhead for s,e in ranges)
                output_tokens = pass_count * min(output_tokens_per_window, recipe["execution"]["max_output_tokens"])
                factor = (1-cache_fraction) * (1+recovery_fraction)
                cost = token_cost(model, Decimal(str(input_tokens * factor)), Decimal(str(output_tokens * factor)))
                stages[expert["stage"]] += cost
                calls += pass_count * factor
                passes.append({"expert": expert["id"], "model": model["model"], "estimated_usd": cost,
                    "planned_admitted_windows": pass_count, "context_blocked_windows": blocked,
                    "input_token_method": token_method})
        total = sum(stages.values())
        scenarios.append({"chars_per_source": length, "initial_windows": windows,
                          "estimated_calls": math.ceil(calls), "stages_usd": stages,
                          "total_usd": total, "passes": passes,
                          "context_blocked_windows": context_blocked,
                          "fits_context_capacity": context_blocked == 0,
                          "fits_total_budget": total <= recipe["execution"]["budget_usd"],
                          "fits_stage_budgets": all(v <= recipe["execution"]["stage_budgets"][k] for k,v in stages.items())})
    return {"version": "document-window-estimate-v1", "mode": recipe["mode"], "links": count,
            "compute_cost_basis": profile.get("compute", {}).get("cost_basis", "token_rates"),
            "infrastructure_cost_usd": None,
            "infrastructure_cost_reason": profile.get("compute", {}).get("infrastructure_cost_reason", "not_metered_by_collector"),
            "range_usd": [min(s["total_usd"] for s in scenarios), max(s["total_usd"] for s in scenarios)],
            "scenarios": scenarios, "assumptions": {"cache_fraction": cache_fraction,
              "chars_per_token": chars_per_token, "output_tokens_per_window": output_tokens_per_window,
              "recovery_fraction": recovery_fraction, "parsing_usd_per_source": parsing_usd_per_source,
              "translation_usd_per_source": translation_usd_per_source,
              "count_only_lengths": None if source_list else lengths,
              "context_admission": "Full observed prompt and output reserve; trusted registered tokenizer or conservative UTF8 byte/template reserve for explicit total-context profiles. Count-only/missing-text forecasts use ASCII placeholders and cannot establish multilingual fit.",
              "specialist_routing": "observed metadata" if source_list else "all lenses, upper workload scenario",
              "notes": "Planning scenarios, not confidence intervals. Adjust for scripts, PDF page lengths, OCR and output density; no term-yield quota. Parsing is local CPU; OCR/standalone translation adapters are extensions. Inline requested translations are billed within extraction output."},
            "request_reserves_usd": {e["id"]: reserve_cost(profile["models"][e["model"]],
                  recipe["execution"]["recovery_output_tokens"]) for e in experts(recipe, profile)},
            "prices": profile["models"], "actual_is_provider_reported_token_estimate_not_invoice": True}
