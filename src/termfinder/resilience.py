"""Finite retry policy and safe HTTP timing hints. No tools or network calls."""
from __future__ import annotations

from copy import deepcopy
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import random as _random

DEFAULT_RESILIENCE = {
    "delays_seconds": [30, 120, 240, 480],
    "jitter_fraction": 0.2,
    "max_retry_after_seconds": 86400,
    "automatic_uncertain_retries": True,
    "max_retry_calls": 20000,
    "model_concurrency": 1,
    "min_request_interval_seconds": 0.5,
}


def parse_retry_after(value, *, now):
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
            delay = max(0, date.timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay >= 0 else None


def retry_delay(policy, retry_number, *, retry_after=None, random=None):
    if type(retry_number) is not int or retry_number < 1:
        raise ValueError("retry_number starts at one")
    delays = policy["delays_seconds"]
    base = delays[min(retry_number-1, len(delays)-1)]
    base *= 2 ** max(0, retry_number-len(delays))
    base = min(base, policy["max_retry_after_seconds"])
    if retry_after is not None:
        base = max(base, retry_after)  # Never retry before the server permits.
    # Additive jitter preserves the researcher's requested minimum waits.
    jitter = (random or _random.random)()
    return base * (1 + policy["jitter_fraction"] * jitter)


def large_run_execution(execution):
    """Explicit opt-in for existing recipes; never increase monetary budgets."""
    value = deepcopy(execution)
    value.update(max_calls=max(value["max_calls"], 1_000_000),
                 deadline_seconds=max(value["deadline_seconds"], 604800),
                 timeout_seconds=max(value["timeout_seconds"], 180),
                 max_retries=4, resilience=deepcopy(DEFAULT_RESILIENCE))
    return value


def cluster_execution(execution, *, concurrency=4, model_concurrency=4):
    """Explicit bounded throughput settings, without increasing study budgets.

    These are operator choices, not measured optimum values or a benchmark.
    Reuse retry/uncertain-outcome policy; never reduce extraction passes, text
    overlap, output capacity or coverage to improve apparent throughput.
    """
    if type(concurrency) is not int or not 1 <= concurrency <= 64:
        raise ValueError("cluster concurrency must be 1–64")
    if type(model_concurrency) is not int or not 1 <= model_concurrency <= min(32, concurrency):
        raise ValueError("per-model concurrency must be 1–32 and within total concurrency")
    value = deepcopy(execution)
    value["concurrency"] = concurrency
    policy = deepcopy(value.get("resilience", DEFAULT_RESILIENCE))
    if "resilience" not in execution:
        policy["automatic_uncertain_retries"] = False
    policy.update(model_concurrency=model_concurrency, min_request_interval_seconds=0)
    value["resilience"] = policy
    return value
