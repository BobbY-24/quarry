"""Validated researcher-editable contracts. Never loads code from configuration."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from importlib.resources import files
import json
import math
from pathlib import Path
import re
import ipaddress
from urllib.parse import urlsplit, urlunsplit

CORE_FIELDS = {"expression", "language", "sense", "context"}
DATA_TYPES = frozenset({"term", "idea", "opinion", "sentence"})
STAGES = ("discovery", "parsing", "extraction", "specialist", "translation")
RECIPE_KEYS = {"schema_version", "id", "version", "research_question", "inclusion_criteria",
               "exclusion_criteria", "languages", "communities", "dates", "source_scope",
               "examples", "output", "mode", "model_profile", "specialist_lenses",
               "discovery", "execution", "exports", "data_type"}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path):
    p = Path(path)
    if p.stat().st_size > 32_000_000:
        raise ValueError("configuration exceeds 32 MB")
    return json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _keys(value, allowed, label, required=None):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required or allowed) - set(value):
        raise ValueError(f"{label}: invalid or missing fields")


def _text(value, label, *, limit=20000, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{label}: bounded nonempty text required")


def _strings(value, label, *, empty=False):
    if not isinstance(value, list) or len(value) > 500 or (not empty and not value):
        raise ValueError(f"{label}: text list required")
    for item in value:
        _text(item, label, limit=2048)
    if len(value) != len(set(value)):
        raise ValueError(f"{label}: duplicate values")


def _num(value, label, low=0, high=1_000_000, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}: finite number required")
    if integer and type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: value outside limits")


def _boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label}: boolean required")


def validate_recipe(value):
    _keys(value, RECIPE_KEYS, "recipe", required=RECIPE_KEYS - {"data_type"})
    if not isinstance(value.get("data_type", "term"), str) or value.get("data_type", "term") not in DATA_TYPES:
        raise ValueError("data_type must be term, idea, opinion, or sentence")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported recipe schema_version")
    if not isinstance(value["id"], str) or not IDENTIFIER.fullmatch(value["id"]):
        raise ValueError("recipe id must be a lowercase slug")
    for key in ("version", "research_question", "model_profile"):
        _text(value[key], key)
    for key in ("inclusion_criteria", "exclusion_criteria", "languages", "communities"):
        _strings(value[key], key)
    if value["mode"] not in ("broad", "specialists"):
        raise ValueError("mode must be broad or specialists")
    dates = value["dates"]
    _keys(dates, {"start", "end", "unknown"}, "dates")
    for key in ("start", "end"):
        if dates[key] is not None:
            _text(dates[key], "date", limit=10)
            date.fromisoformat(dates[key])
    if dates["start"] and dates["end"] and dates["start"] > dates["end"]:
        raise ValueError("date range is reversed")
    if dates["unknown"] not in ("include", "exclude"):
        raise ValueError("dates.unknown must be include or exclude")
    scope = value["source_scope"]
    _keys(scope, {"domains", "local"}, "source_scope")
    _strings(scope["domains"], "domains", empty=True)
    for domain in scope["domains"]:
        if not re.fullmatch(r"(?:\*\.)?[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or ".." in domain:
            raise ValueError("domain scope requires hostnames or *.hostname")
    _boolean(scope["local"], "source_scope.local")
    _keys(value["examples"], {"positive", "negative", "boundary"}, "examples")
    for kind, examples in value["examples"].items():
        if not isinstance(examples, list) or not 1 <= len(examples) <= 100:
            raise ValueError("each example group requires 1–100 examples")
        for example in examples:
            _keys(example, {"text", "expression", "language", "sense", "reason"}, "example")
            for key in ("text", "expression", "language", "reason"):
                _text(example[key], f"example.{key}")
            _text(example["sense"], "example.sense", nullable=True)
            if example["expression"] not in example["text"]:
                raise ValueError("example expression must occur in text")
    output = value["output"]
    _keys(output, {"required_fields", "attributes", "translations"}, "output")
    _strings(output["required_fields"], "required_fields")
    if set(output["required_fields"]) - CORE_FIELDS:
        raise ValueError("required fields must be core proposal fields")
    _boolean(output["translations"], "translations")
    if not isinstance(output["attributes"], dict) or len(output["attributes"]) > 50:
        raise ValueError("attributes must be a bounded object")
    for field, spec in output["attributes"].items():
        if not IDENTIFIER.fullmatch(field):
            raise ValueError("attribute names must be lowercase slugs")
        _keys(spec, {"type", "required", "description"}, "attribute")
        if spec["type"] not in {"string", "number", "integer", "boolean", "array"}:
            raise ValueError("unsupported attribute type")
        _boolean(spec["required"], "attribute.required")
        _text(spec["description"], "attribute.description")
    lenses = value["specialist_lenses"]
    if not isinstance(lenses, list) or len(lenses) > 8:
        raise ValueError("specialist_lenses requires at most eight passes")
    ids = set()
    for lens in lenses:
        _keys(lens, {"id", "model", "lens", "communities"}, "specialist lens")
        for key in ("id", "model", "lens"):
            _text(lens[key], key, limit=4000)
        if not IDENTIFIER.fullmatch(lens["id"]) or lens["id"] in ids:
            raise ValueError("lens ids must be unique slugs")
        ids.add(lens["id"])
        _strings(lens["communities"], "lens communities")
    discovery = value["discovery"]
    _keys(discovery, {"enabled", "queries", "max_sources", "max_hops", "max_requests",
                      "max_cost_usd", "search_cost_usd", "fetch_cost_usd"}, "discovery")
    _boolean(discovery["enabled"], "discovery.enabled")
    _strings(discovery["queries"], "queries", empty=True)
    for key in ("max_sources", "max_hops", "max_requests"):
        _num(discovery[key], key, integer=True, high=100000)
    for key in ("max_cost_usd", "search_cost_usd", "fetch_cost_usd"):
        _num(discovery[key], key)
    execution = value["execution"]
    execution_keys = {"budget_usd", "stage_budgets", "max_calls", "concurrency", "timeout_seconds",
                      "max_retries", "deadline_seconds", "window_chars", "overlap_chars",
                      "split_depth", "max_output_tokens", "recovery_output_tokens"}
    _keys(execution, execution_keys | {"resilience"}, "execution", required=execution_keys)
    _num(execution["budget_usd"], "budget_usd")
    _keys(execution["stage_budgets"], STAGES, "stage_budgets")
    for stage in STAGES:
        _num(execution["stage_budgets"][stage], f"stage budget {stage}")
    for key, low, high in (("max_calls", 1, 10000000), ("concurrency", 1, 64),
                           ("timeout_seconds", 1, 1800), ("max_retries", 0, 8),
                           ("deadline_seconds", 1, 2592000), ("window_chars", 32, 50000),
                           ("overlap_chars", 0, 49999), ("split_depth", 0, 5),
                           ("max_output_tokens", 128, 131072), ("recovery_output_tokens", 128, 131072)):
        _num(execution[key], key, low, high, integer=True)
    if "resilience" in execution:
        from .resilience import DEFAULT_RESILIENCE
        policy = execution["resilience"]
        _keys(policy, DEFAULT_RESILIENCE, "resilience")
        delays = policy["delays_seconds"]
        if not isinstance(delays, list) or not 1 <= len(delays) <= 8:
            raise ValueError("resilience requires one to eight finite retry delays")
        for delay in delays: _num(delay, "retry delay", 0, 86400)
        if delays != sorted(delays): raise ValueError("retry delays must not decrease")
        _num(policy["jitter_fraction"], "jitter fraction", 0, 1)
        _num(policy["max_retry_after_seconds"], "maximum server delay", 1, 604800)
        _num(policy["max_retry_calls"], "aggregate retry budget", 0, 10000000, integer=True)
        _num(policy["model_concurrency"], "per-model concurrency", 1, 32, integer=True)
        _num(policy["min_request_interval_seconds"], "minimum request interval", 0, 3600)
        _boolean(policy["automatic_uncertain_retries"], "automatic uncertain retries")
    if execution["overlap_chars"] >= execution["window_chars"]:
        raise ValueError("overlap must be smaller than window_chars")
    exports = value["exports"]
    _keys(exports, {"formats", "annotation"}, "exports")
    _strings(exports["formats"], "formats")
    if set(exports["formats"]) - {"csv", "jsonl", "parquet"}:
        raise ValueError("unsupported export format")
    _boolean(exports["annotation"], "annotation export")
    canonical(value)  # refuse nonfinite nested values
    return deepcopy(value)


def starter_recipe(name):
    if name not in {"neologisms", "cultural", "jargon"}:
        raise ValueError("unknown starter recipe")
    return load_recipe(json.loads(files("quarry").joinpath("recipes", name + ".json").read_text()))


def load_recipe(path_or_dict):
    return validate_recipe(path_or_dict if isinstance(path_or_dict, dict) else read_json(path_or_dict))


def provider_endpoint(provider):
    """Validate an operator-selected endpoint; plaintext is loopback-only, without secrets."""
    _text(provider["base_url"], "provider endpoint", limit=2048)
    raw = provider["base_url"]
    if any(c.isspace() or ord(c) < 32 for c in raw) or "?" in raw or "#" in raw:
        raise ValueError("provider endpoint contains unsupported URL components")
    u = urlsplit(raw)
    try:
        port = u.port
    except ValueError:
        raise ValueError("provider endpoint has an invalid port") from None
    if not u.hostname or u.username is not None or u.password is not None or u.scheme not in {"http", "https"}:
        raise ValueError("provider requires a credential-free HTTP(S) base URL")
    host = u.hostname.lower()
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
    auth = provider.get("auth", "api_key" if provider["adapter"] == "gemini" else "bearer")
    if auth not in {"none", "bearer", "api_key"}:
        raise ValueError("unsupported provider authentication")
    if u.scheme == "http" and (not loopback or auth != "none"):
        raise ValueError("plaintext inference requires unauthenticated loopback")
    if auth == "none":
        if not loopback or provider["credential_env"] is not None or provider["adapter"] != "openai":
            raise ValueError("unauthenticated inference is restricted to loopback OpenAI-compatible servers")
    else:
        credential = provider["credential_env"]
        if not isinstance(credential, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", credential):
            raise ValueError("invalid credential environment name")
        if credential in {"PATH", "HOME", "CODEX_HOME", "PYTHONPATH", "PYTHONHOME", "TMPDIR", "SHELL", "USER", "LOGNAME"}:
            raise ValueError("use a dedicated credential environment name")
        if not credential.endswith(("_KEY", "_TOKEN", "_SECRET")) or credential.startswith((
                "LD_", "DYLD_", "PYTHON", "PIP_", "SSL_", "OPENSSL_", "GCONV_", "BASH_", "ZSH_", "LC_")):
            raise ValueError("use a dedicated credential name ending in _KEY, _TOKEN or _SECRET, not a runtime control")
        if (provider["adapter"] == "gemini") != (auth == "api_key"):
            raise ValueError("authentication does not match the provider adapter")
    if provider.get("response_format", "json_object") not in {"json_object", "none"}:
        raise ValueError("unsupported response format option")
    # Do not delegate a plaintext localhost resolution to DNS or a proxy.
    if host == "localhost":
        u = u._replace(netloc="127.0.0.1" + (":" + str(port) if port is not None else ""))
    return urlunsplit(u), loopback, auth


def load_profile(value):
    if isinstance(value, dict):
        profile = deepcopy(value)
    elif str(value) in {"glm-deepseek", "gemini", "fake"}:
        profile = json.loads(files("quarry").joinpath("profiles", str(value) + ".json").read_text())
    else:
        profile = read_json(value)
    required = {"schema_version", "id", "version", "providers", "models", "broad"}
    _keys(profile, required | {"compute"}, "profile", required=required)
    from .agent_setup import _credential_free
    _credential_free(profile)
    if "compute" in profile:
        meta = profile["compute"]
        _keys(meta, {"backend", "cost_basis", "infrastructure_cost_usd", "infrastructure_cost_reason", "configuration_reference"}, "compute")
        if meta["backend"] not in {"api", "local", "institutional"} or meta["cost_basis"] not in {"token_rates", "unmetered_infrastructure"}:
            raise ValueError("invalid compute metadata")
        if meta["infrastructure_cost_usd"] is not None:
            raise ValueError("infrastructure costs must remain unknown until separately measured")
        _text(meta["infrastructure_cost_reason"], "infrastructure cost reason", limit=2048)
        _text(meta["configuration_reference"], "configuration reference", limit=1000)
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("unsupported profile schema")
    for key in ("id", "version"):
        _text(profile[key], key, limit=128)
    if not isinstance(profile["providers"], dict) or not profile["providers"]:
        raise ValueError("providers required")
    for provider in profile["providers"].values():
        required = {"adapter", "base_url", "credential_env"}
        _keys(provider, required | {"auth", "response_format"}, "provider", required=required)
        if provider["adapter"] not in {"openai", "gemini", "fake"}:
            raise ValueError("unknown provider adapter")
        if provider["adapter"] == "fake" and (provider["credential_env"] is not None or provider["base_url"] is not None):
            raise ValueError("fake provider has no credential or network endpoint")
        if provider["adapter"] != "fake":
            provider["base_url"], loopback, auth = provider_endpoint(provider)
            backend = profile.get("compute", {}).get("backend")
            if backend == "local" and (not loopback or auth != "none"):
                raise ValueError("local compute metadata must describe credential-free loopback inference")
            if backend == "api" and auth == "none":
                raise ValueError("API compute metadata must describe authenticated inference")
        elif "compute" in profile:
            raise ValueError("real compute metadata cannot label a fixture provider")
    if not isinstance(profile["models"], dict) or not 1 <= len(profile["models"]) <= 16:
        raise ValueError("1–16 models required")
    for model in profile["models"].values():
        required_model = {"provider", "model", "version", "thinking_budget", "input_per_million",
                      "output_per_million", "input_token_ceiling", "output_token_ceiling",
                      "price_source", "prices_recorded_at", "price_note"}
        _keys(model, required_model | {"runtime", "context_limit_tokens", "prompt_overhead_tokens"},
              "model", required=required_model)
        if "runtime" in model:
            from .runtime import validate_runtime
            model["runtime"] = validate_runtime(model["runtime"])
        if "context_limit_tokens" in model:
            _num(model["context_limit_tokens"], "context_limit_tokens", 1, 10000000, integer=True)
        if "prompt_overhead_tokens" in model:
            _num(model["prompt_overhead_tokens"], "prompt_overhead_tokens", 0, 131072, integer=True)
        for key in ("model", "version", "price_source", "prices_recorded_at", "price_note"):
            _text(model[key], key, limit=2048)
        if model["provider"] not in profile["providers"]:
            raise ValueError("unknown model provider")
        if model["thinking_budget"] is not None:
            _num(model["thinking_budget"], "thinking_budget", integer=True, high=131072)
        for key in ("input_per_million", "output_per_million"):
            _num(model[key], key)
        for key in ("input_token_ceiling", "output_token_ceiling"):
            _num(model[key], key, 1, 10_000_000, integer=True)
        if "context_limit_tokens" in model and (model["input_token_ceiling"] > model["context_limit_tokens"]
                                               or model["output_token_ceiling"] > model["context_limit_tokens"]):
            raise ValueError("model input/output ceilings exceed total context capacity")
    if not isinstance(profile["broad"], list) or not 1 <= len(profile["broad"]) <= 8:
        raise ValueError("broad passes required")
    ids = set()
    for expert in profile["broad"]:
        _keys(expert, {"id", "model", "lens", "communities"}, "broad expert")
        if expert["model"] not in profile["models"] or not IDENTIFIER.fullmatch(expert["id"]) or expert["id"] in ids:
            raise ValueError("invalid broad expert")
        _text(expert["lens"], "lens", limit=4000)
        _strings(expert["communities"], "communities")
        ids.add(expert["id"])
    if profile.get("compute", {}).get("cost_basis") == "unmetered_infrastructure" and any(
            m["input_per_million"] or m["output_per_million"] for m in profile["models"].values()):
        raise ValueError("unmetered infrastructure profiles cannot declare token charges")
    canonical(profile)
    return profile


def experts(recipe, profile):
    result = [dict(e, stage="extraction") for e in profile["broad"]]
    if recipe["mode"] == "specialists":
        for e in recipe["specialist_lenses"]:
            if e["model"] not in profile["models"]:
                # Gemini uses the same research lens with its own independent model.
                if len(profile["models"]) == 1:
                    e = dict(e, model=next(iter(profile["models"])))
                else:
                    raise ValueError("specialist lens references an unknown model")
            result.append(dict(e, stage="specialist"))
    if len({e["id"] for e in result}) != len(result):
        raise ValueError("expert ids overlap")
    return result
