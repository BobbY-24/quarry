"""Researcher-owned compute choices. No credential values, discovery or network calls."""
from __future__ import annotations

from copy import deepcopy
from datetime import date

from .config import load_profile, provider_endpoint


def build_compute_profile(*, backend, preset=None, base_url=None, model=None,
                          model_version=None, credential_env=None,
                          input_per_million=None, output_per_million=None,
                          context_limit_tokens=32768, max_output_tokens=8192,
                          response_format="json_object",
                          runtime=None,
                          configuration_reference="researcher local configuration"):
    if backend not in {"api", "local", "institutional"}:
        raise ValueError("Choose api, local or institutional compute")
    if preset is not None:
        if backend != "api" or preset not in {"glm-deepseek", "gemini"}:
            raise ValueError("Packaged presets are API profiles")
        if any(v is not None for v in (base_url, model, model_version, input_per_million, output_per_million, runtime)):
            raise ValueError("Use a preset or a complete custom endpoint configuration")
        if response_format != "json_object" or context_limit_tokens != 32768 or max_output_tokens != 8192:
            raise ValueError("Preset transport and token ceilings are preserved; use a custom profile for overrides")
        profile = load_profile(preset)
        if credential_env is not None:
            for provider in profile["providers"].values():
                provider["credential_env"] = credential_env
        basis = "token_rates"
    else:
        if not model or not model_version or not base_url:
            raise ValueError("Custom inference requires an endpoint and exact model/version identifiers")
        if backend == "api" and (not credential_env or input_per_million is None or output_per_million is None):
            raise ValueError("Custom API compute requires its credential environment name and explicit token rates")
        if type(context_limit_tokens) is not int or type(max_output_tokens) is not int or max_output_tokens < 128 or max_output_tokens > context_limit_tokens:
            raise ValueError("Custom token ceilings must be integer limits with output at least 128 and within context capacity")
        provider = {"adapter": "openai", "base_url": base_url,
                    "credential_env": credential_env,
                    "auth": "bearer" if credential_env is not None else "none",
                    "response_format": response_format}
        endpoint, loopback, _ = provider_endpoint(provider)
        if backend == "local" and (not loopback or credential_env is not None):
            raise ValueError("Local compute requires a loopback endpoint without a credential")
        if (input_per_million is None) != (output_per_million is None):
            raise ValueError("Supply both token rates or neither")
        basis = "unmetered_infrastructure" if input_per_million is None else "token_rates"
        profile = {"schema_version": 1, "id": "researcher-" + backend, "version": "1.0.0",
            "providers": {"researcher": dict(provider, base_url=endpoint)},
            "models": {"researcher": {"provider": "researcher", "model": model,
                "version": model_version, "thinking_budget": None,
                "input_per_million": 0 if input_per_million is None else input_per_million,
                "output_per_million": 0 if output_per_million is None else output_per_million,
                "input_token_ceiling": context_limit_tokens, "output_token_ceiling": max_output_tokens,
                "context_limit_tokens": context_limit_tokens,
                "price_source": "researcher-configured; confirm with the service or allocation owner",
                "prices_recorded_at": date.today().isoformat(),
                "price_note": "Token-rate estimate only; infrastructure and harness charges are not measured."}},
            "broad": [{"id": "researcher-general", "model": "researcher",
                       "lens": "Enumerate all qualifying observed expressions and senses under the research recipe.",
                       "communities": ["*"]}]}
        if runtime is not None:
            from .runtime import validate_runtime
            profile["models"]["researcher"]["runtime"] = validate_runtime(runtime)
    profile["compute"] = {"backend": backend, "cost_basis": basis,
        "infrastructure_cost_usd": None,
        "infrastructure_cost_reason": "GPU time, electricity, allocation charges and planning-agent charges are not metered by Quarry",
        "configuration_reference": configuration_reference}
    return load_profile(profile)


def compute_summary(profile, *, configured=False):
    """Credential presence only. Exported provenance retains names, never key values."""
    import os
    if not profile:
        return {"configured": False, "backend": None, "inference_enabled": False,
                "next_step": "Choose your own API, local server or institutional compute before planning."}
    profile = load_profile(profile)
    metadata = profile.get("compute", {})
    backends = {p["adapter"] for p in profile["providers"].values()}
    endpoints = []
    for name, provider in profile["providers"].items():
        env_name = provider["credential_env"]
        endpoints.append({"provider": name, "adapter": provider["adapter"],
            "base_url": provider["base_url"], "credential_env": env_name,
            "authentication": provider.get("auth", "none" if provider["adapter"] == "fake" else "environment_header"),
            "credential_present": bool(os.environ.get(env_name)) if env_name else None,
            "credential_presence_reason": None if env_name else "no_credential_required"})
    return {"configured": configured, "backend": metadata.get("backend", "offline" if backends == {"fake"} else "api"),
        "profile_id": profile["id"], "profile_version": profile["version"], "providers": endpoints,
        "models": deepcopy(profile["models"]), "general_pass_count": len(profile["broad"]),
        "cost_basis": metadata.get("cost_basis", "token_rates"),
        "infrastructure_cost_usd": None,
        "infrastructure_cost_reason": metadata.get("infrastructure_cost_reason", "not_metered_by_collector"),
        "account_or_allocation_owner": None,
        "account_or_allocation_owner_reason": "Credential holder or allocation owner; identity is not verified by Quarry",
        "inference_enabled": False,
        "authorization_note": "Configuration does not launch inference. Every nonfake server, including local servers, still requires the legacy allow-paid launch gate and a reviewed finite collection plan."}
