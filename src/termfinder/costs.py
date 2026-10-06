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
             recovery_fraction=0.15, parsing_usd_per_source=0, translation_usd_per_source=0):
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
        passes, calls, windows = [], 0, 0
        planning = source_list if source_list else [{"text": "", "community": None}] * count
        for source in planning:
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
                prompt_overhead = len(build_prompt(recipe, expert, "", source if source_list else None)) / chars_per_token
                input_tokens = sum((e-s) / chars_per_token + prompt_overhead for s,e in ranges)
                output_tokens = len(ranges) * min(output_tokens_per_window, recipe["execution"]["max_output_tokens"])
                factor = (1-cache_fraction) * (1+recovery_fraction)
                cost = token_cost(model, Decimal(str(input_tokens * factor)), Decimal(str(output_tokens * factor)))
                stages[expert["stage"]] += cost
                calls += len(ranges) * factor
                passes.append({"expert": expert["id"], "model": model["model"], "estimated_usd": cost})
        total = sum(stages.values())
        scenarios.append({"chars_per_source": length, "initial_windows": windows,
                          "estimated_calls": math.ceil(calls), "stages_usd": stages,
                          "total_usd": total, "passes": passes,
                          "fits_total_budget": total <= recipe["execution"]["budget_usd"],
                          "fits_stage_budgets": all(v <= recipe["execution"]["stage_budgets"][k] for k,v in stages.items())})
    return {"version": "document-window-estimate-v1", "mode": recipe["mode"], "links": count,
            "range_usd": [min(s["total_usd"] for s in scenarios), max(s["total_usd"] for s in scenarios)],
            "scenarios": scenarios, "assumptions": {"cache_fraction": cache_fraction,
              "chars_per_token": chars_per_token, "output_tokens_per_window": output_tokens_per_window,
              "recovery_fraction": recovery_fraction, "parsing_usd_per_source": parsing_usd_per_source,
              "translation_usd_per_source": translation_usd_per_source,
              "count_only_lengths": None if source_list else lengths,
              "specialist_routing": "observed metadata" if source_list else "all lenses, upper workload scenario",
              "notes": "Planning scenarios, not confidence intervals. Adjust for scripts, PDF page lengths, OCR and output density; no term-yield quota. Parsing is local CPU; OCR/standalone translation adapters are extensions. Inline requested translations are billed within extraction output."},
            "request_reserves_usd": {e["id"]: reserve_cost(profile["models"][e["model"]],
                  recipe["execution"]["recovery_output_tokens"]) for e in experts(recipe, profile)},
            "prices": profile["models"], "actual_is_provider_reported_token_estimate_not_invoice": True}
