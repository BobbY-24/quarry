"""Trusted offline fault injection keyed by stable job and attempt identities.

These helpers never execute model text, launch tools, or read credentials. They
run in process and do not provide a hard execution deadline. Use ProcessProvider
for reviewed adapters requiring enforceable deadlines. A sleep is bounded here
only to keep deliberately injected tests finite, not as a production timeout.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import threading
import time

from .providers import ProviderError, Response


def _key(value):
    if (not isinstance(value, tuple) or len(value) != 2 or not isinstance(value[0], str)
            or not 1 <= len(value[0]) <= 256 or type(value[1]) is not int or value[1] < 1):
        raise ValueError("Tape keys must be (nonempty job_id, positive attempt_number)")
    return value


def request_fingerprint(request):
    """Stable extraction request key independent of cache/job/attempt identity."""
    if "logical_request_id" in request:
        logical = request["logical_request_id"]
        if not isinstance(logical, str) or not 1 <= len(logical) <= 256:
            raise ProviderError("invalid_fault_tape_request", failure_scope="request")
        return _hash({"logical_request_id": logical})
    if not isinstance(request.get("prompt"), str) or not isinstance(request.get("expert"), dict):
        raise ProviderError("invalid_fault_tape_request", failure_scope="request")
    try:
        return _hash({key: request.get(key) for key in ("prompt", "text", "expert", "max_output_tokens")})
    except (ValueError, TypeError, RecursionError):
        raise ProviderError("invalid_fault_tape_request", failure_scope="request") from None


def _request_key(request, scheme="job"):
    try:
        return _key((request["job_id"] if scheme == "job" else request_fingerprint(request), request["attempt_number"]))
    except (KeyError, TypeError, ValueError):
        raise ProviderError("invalid_fault_tape_request", failure_scope="request") from None


def _error(error):
    return {"reason": error.reason, "uncertain": error.uncertain, "retryable": error.retryable,
            "retry_after_seconds": error.retry_after_seconds, "failure_scope": error.failure_scope.value}


def _copy_error(error):
    values = _error(error)
    return ProviderError(values.pop("reason"), **values)


def _hash(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class FaultAction:
    error: ProviderError | None = None
    delay_seconds: float = 0

    def __post_init__(self):
        if (self.error is not None and not isinstance(self.error, ProviderError)
                or type(self.delay_seconds) not in (int, float) or not math.isfinite(self.delay_seconds)
                or not 0 <= self.delay_seconds <= 30):
            raise ValueError("Fault actions require typed errors and finite delays from 0 to 30 seconds")


class KeyedFakeProvider:
    """A repeatable immutable response tape; missing entries reject before work.

    The response tape, including attempt keys, is hashed into cache_identity.
    Scheduling order changes only the diagnostic calls list, never responses.
    """
    paid = False
    execution_boundary = "trusted_in_process"
    enforceable_deadline = False

    def __init__(self, tape, *, key_scheme="job", fallback_provider=None):
        if key_scheme not in {"job", "request"}:
            raise ValueError("Choose job or request tape keys")
        self.key_scheme = key_scheme
        if fallback_provider is not None and (not callable(getattr(fallback_provider, "complete", None))
                                              or getattr(fallback_provider, "paid", False)):
            raise ValueError("Response-tape fallback must be an explicitly supplied offline provider")
        self.fallback_provider = fallback_provider
        self._tape = {}
        records = []
        for key, value in sorted((_key(key), value) for key, value in tape.items()):
            if not isinstance(value, (Response, ProviderError)):
                raise ValueError("Response tape entries require Response or ProviderError")
            self._tape[key] = value if isinstance(value, Response) else _copy_error(value)
            records.append({"job_id": key[0], "attempt_number": key[1],
                            "response": asdict(value) if isinstance(value, Response) else None,
                            "error": _error(value) if isinstance(value, ProviderError) else None})
        self.tape_sha256 = _hash({"key_scheme": key_scheme, "records": records,
                                 "fallback_identity": getattr(fallback_provider, "cache_identity", None)})
        self.cache_identity = "offline-keyed-response-v1:" + self.tape_sha256
        self.calls = []
        self._lock = threading.Lock()

    def complete(self, request):
        key = _request_key(request, self.key_scheme)
        with self._lock:
            self.calls.append(key)
        if key not in self._tape:
            if self.fallback_provider is not None:
                return self.fallback_provider.complete(request)
            raise ProviderError("fault_tape_entry_missing", failure_scope="request")
        value = self._tape[key]
        if isinstance(value, ProviderError):
            raise _copy_error(value)
        return value


class FaultTapeProvider:
    """Runtime faults wrap a provider while preserving its normal cache identity.

    Set cache_faults=True only for experiments intentionally treating a fault
    tape as part of extraction identity. Faults are evaluated before delegation,
    so a simulated uncertain fault never implies a real provider was called.
    """
    execution_boundary = "trusted_in_process"
    enforceable_deadline = False

    def __init__(self, provider, tape, *, cache_faults=False, key_scheme="job"):
        if not callable(getattr(provider, "complete", None)) or type(cache_faults) is not bool:
            raise ValueError("Expected a provider and an explicit cache-fault policy")
        self.provider = provider
        if key_scheme not in {"job", "request"}:
            raise ValueError("Choose job or request tape keys")
        self.key_scheme = key_scheme
        self.paid = getattr(provider, "paid", False)
        self._tape = {}
        records = []
        for key, value in sorted((_key(key), value) for key, value in tape.items()):
            value = FaultAction(error=_copy_error(value)) if isinstance(value, ProviderError) else value
            if not isinstance(value, FaultAction):
                raise ValueError("Fault tape entries require ProviderError or FaultAction")
            value = FaultAction(error=_copy_error(value.error) if value.error else None,
                                delay_seconds=value.delay_seconds)
            self._tape[key] = value
            records.append({"job_id": key[0], "attempt_number": key[1], "delay_seconds": value.delay_seconds,
                            "error": _error(value.error) if value.error else None})
        self.fault_tape_sha256 = _hash({"key_scheme": key_scheme, "records": records})
        underlying = getattr(provider, "cache_identity", type(provider).__qualname__)
        self.cache_identity = ("offline-runtime-fault-v1:" + _hash([underlying, self.fault_tape_sha256])
                               if cache_faults else underlying)
        self.calls = []
        self._lock = threading.Lock()

    def complete(self, request):
        key = _request_key(request, self.key_scheme)
        with self._lock:
            self.calls.append(key)
        action = self._tape.get(key)
        if action:
            if action.delay_seconds:
                time.sleep(action.delay_seconds)
            if action.error:
                raise _copy_error(action.error)
        return self.provider.complete(request)
