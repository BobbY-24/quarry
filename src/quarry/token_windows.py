"""Finite token-aware planning using untouched source codepoint offsets."""
from __future__ import annotations

from .runtime import PromptTokenizer

VERSION = "token-admission-v1"


def token_admission(model, prompt, max_output_tokens, *, tokenizer=None):
    if not isinstance(prompt, str) or type(max_output_tokens) is not int or max_output_tokens < 0:
        raise ValueError("token admission requires a prompt and nonnegative integer output reserve")
    if tokenizer is not None and not isinstance(tokenizer, PromptTokenizer):
        raise ValueError("tokenizer must be a trusted PromptTokenizer registration")
    if tokenizer is not None:
        declared = model.get("runtime", {})
        for field in ("tokenizer_sha256", "chat_template_sha256"):
            if declared.get(field) and getattr(tokenizer, field) and declared[field] != getattr(tokenizer, field):
                raise ValueError("registered tokenizer differs from the declared model artifacts")
    capacity = model.get("context_limit_tokens", model["input_token_ceiling"])
    template = model.get("prompt_overhead_tokens", 256)
    if type(capacity) is not int or capacity < 1 or type(template) is not int or template < 0:
        raise ValueError("invalid context or template capacity")
    manifest = tokenizer.manifest() if tokenizer is not None else None
    reason = None
    if tokenizer is not None:
        try:
            tokens = tokenizer.count(prompt)
        except Exception:
            # Do not expose tokenizer exception messages, source text or paths.
            tokens = len(prompt.encode("utf-8")) + template
            method, reason = "utf8_bytes_plus_template_reserve", "trusted_prompt_tokenizer_failed_conservative_fallback"
        else:
            method = "trusted_registered_prompt_tokenizer"
    else:
        tokens = len(prompt.encode("utf-8")) + template
        method, reason = "utf8_bytes_plus_template_reserve", "trusted_prompt_tokenizer_unavailable_conservative_fallback"
    total = tokens + max_output_tokens
    return {"version": VERSION, "admitted": tokens <= model["input_token_ceiling"] and total <= capacity,
            "input_tokens": tokens, "reserved_output_tokens": max_output_tokens,
            "total_reserved_tokens": total, "context_limit_tokens": capacity,
            "input_token_ceiling": model["input_token_ceiling"], "method": method, "reason": reason,
            "template_reserved_tokens": template if method == "utf8_bytes_plus_template_reserve" else 0,
            "tokenizer": manifest,
            "fallback_note": "UTF8 bytes are a conservative heuristic for common byte-based tokenizers; unusual tokenizer/template contracts require a reviewed callback and reserve." if reason else None}


def planned_windows(text, execution, model, prompt_builder, *, tokenizer=None, max_output_tokens=None):
    """Yield (start,end,admission), retaining unfit spans as explicit partial work.

    No normalized/decoded token text replaces original text. Initial character
    windows remain upper bounds; each is bisected with bounded overlap until it
    fits, or until 32 codepoints/a finite depth make further splitting unsuitable.
    """
    from .costs import window_ranges
    output = execution["max_output_tokens"] if max_output_tokens is None else max_output_tokens
    empty = token_admission(model, prompt_builder(""), output, tokenizer=tokenizer)
    for start, end in window_ranges(len(text), execution):
        if not empty["admitted"]:
            admission = token_admission(model, prompt_builder(text[start:end]), output, tokenizer=tokenizer)
            yield start, end, dict(admission, blocked_reason="prompt_overhead_exceeds_context_capacity")
            continue
        stack = [(start, end, 0)]
        while stack:
            begin, finish, depth = stack.pop()
            admission = token_admission(model, prompt_builder(text[begin:finish]), output, tokenizer=tokenizer)
            if admission["admitted"]:
                yield begin, finish, admission
            elif finish - begin <= 32 or depth >= 16:
                yield begin, finish, dict(admission, blocked_reason="minimum_window_exceeds_context_capacity")
            else:
                span = finish - begin
                midpoint = begin + span // 2
                overlap = min(execution["overlap_chars"], span // 4)
                stack.append((midpoint - overlap, finish, depth + 1))
                stack.append((begin, midpoint + overlap, depth + 1))
