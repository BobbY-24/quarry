"""Small explicit transports with no SDK retries or response tool dispatch."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from importlib.resources import files
import json
import math
import os
import re
import socket
import ssl
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
from .process_transport import bounded_exchange, TransportFailure


@dataclass(frozen=True)
class Response:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str = "stop"
    model_version: str | None = None
    request_id: str | None = None


class FailureScope(str, Enum):
    REQUEST = "request"
    SOURCE = "source"
    MODEL = "model"
    PROVIDER = "provider"
    LOCAL = "local"
    UNCERTAIN = "uncertain"


def _scope(reason):
    if reason in {"http_400", "http_413", "http_422", "transport_request_size_limit"}:
        return FailureScope.REQUEST
    if reason in {"http_401", "http_403", "http_429", "tls_identity_verification_failed"} or reason.startswith("http_5"):
        return FailureScope.PROVIDER
    if reason in {"missing_credential_environment", "unsupported_paid_adapter", "invalid_process_configuration"}:
        return FailureScope.MODEL
    if reason in {"transport_worker_not_started", "invalid_transport_deadline", "invalid_transport_limits",
                  "process_boundary_requires_posix", "transport_cancelled_before_start"}:
        return FailureScope.LOCAL
    return FailureScope.UNCERTAIN


class ProviderError(Exception):
    """Safe category only; raw provider messages may contain credentials/source text."""
    def __init__(self, reason, *, uncertain=False, retryable=False, retry_after_seconds=None, failure_scope=None):
        # Safe bounded category; never interpolate raw exception/provider bodies.
        if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", reason):
            reason = "unsafe_provider_error_category"
        super().__init__(reason)
        self.reason = reason
        self.uncertain = uncertain
        self.retryable = retryable
        self.failure_scope = FailureScope(failure_scope) if failure_scope is not None else _scope(reason)
        self.retry_after_seconds = (retry_after_seconds if type(retry_after_seconds) in (int, float)
                                    and math.isfinite(retry_after_seconds) and retry_after_seconds >= 0 else None)


@dataclass(frozen=True)
class RejectionContract:
    """Trusted operator declaration, never inferred from an HTTP status alone.

    reference names the reviewed provider guarantee that these status codes mean
    no inference was accepted. It is not verified automatically by this class.
    """
    reference: str
    status_codes: frozenset[int]

    def __post_init__(self):
        if (not isinstance(self.reference, str) or not self.reference.strip() or len(self.reference) > 200
                or any(type(code) is not int or not 400 <= code < 500 for code in self.status_codes)):
            raise ValueError("Invalid reviewed rejection contract")


def _environment(names=(), python_paths=()):
    env = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join((str(Path(__file__).resolve().parent.parent), *python_paths))}
    for name in names:
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name)
                or name in env or name in {"HOME", "TMPDIR", "ENV", "BASH_ENV", "ZDOTDIR"}
                or name.startswith(("PYTHON", "LD_", "DYLD_"))):
            raise ProviderError("invalid_process_configuration", failure_scope=FailureScope.MODEL)
        if not os.environ.get(name):
            raise ProviderError("missing_credential_environment", failure_scope=FailureScope.MODEL)
        env[name] = os.environ[name]
    return env


def _payload(value, limit):
    """Encode incrementally and reject before spawning when the wire is too big."""
    output = bytearray()
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False)
        for chunk in encoder.iterencode(value):
            if len(chunk) > limit:
                raise ProviderError("transport_request_size_limit", failure_scope=FailureScope.REQUEST)
            block = chunk.encode()
            if len(output) + len(block) > limit:
                raise ProviderError("transport_request_size_limit", failure_scope=FailureScope.REQUEST)
            output.extend(block)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ProviderError("invalid_process_request", failure_scope=FailureScope.REQUEST) from None
    return bytes(output)


def _reviewed_argv(command):
    """Reject recognizable credential argv without echoing rejected content."""
    from .agent_setup import _credential_free
    _credential_free(list(command))
    secret_flags = {"--api-key", "--apikey", "--password", "--passwd", "--secret", "--token",
                    "--access-token", "--authorization", "--credential", "--credentials"}
    for argument in command:
        if argument.split("=", 1)[0].lower().replace("_", "-") in secret_flags:
            raise ValueError("Credentials must use selected environment names, never command arguments")
        if re.search(r"\b(?:Bearer|Basic)\s+\S+", argument, re.I):
            raise ValueError("Credentials must use selected environment names, never command arguments")
        for address in re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+", argument):
            parts = urlsplit(address)
            if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
                raise ValueError("Reviewed command URLs must be credential-free without query or fragment")


def _exchange(command, payload, *, env, request, max_request_bytes=20_000_000, max_response_bytes=8_000_000):
    try:
        result = bounded_exchange(command, payload, env=env, timeout_seconds=request["timeout_seconds"],
                                  max_request_bytes=max_request_bytes, max_response_bytes=max_response_bytes,
                                  cancellation_event=request.get("cancellation_event"))
    except TransportFailure as error:
        raise ProviderError(error.reason, uncertain=error.started, retryable=error.retryable) from None
    if result.returncode != 0:
        raise ProviderError("transport_worker_crashed", uncertain=True, failure_scope=FailureScope.LOCAL)
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError()
        # A reviewed endpoint/command still might echo the selected credential.
        for name, secret in env.items():
            if name not in {"PATH", "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE"} and secret:
                if secret in json.dumps(value, ensure_ascii=False):
                    raise ProviderError("credential_echo_in_provider_response", uncertain=True)
        if "error" in value:
            if (set(value) - {"error", "uncertain", "retryable", "retry_after_seconds", "failure_scope"}
                    or not isinstance(value["error"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", value["error"])
                    or type(value.get("uncertain")) is not bool or type(value.get("retryable")) is not bool):
                raise ValueError()
            raise ProviderError(value["error"], uncertain=value["uncertain"], retryable=value["retryable"],
                                retry_after_seconds=value.get("retry_after_seconds"),
                                failure_scope=value.get("failure_scope", "uncertain"))
        if set(value) != {"response"} or not isinstance(value["response"], dict):
            raise ValueError()
        response = Response(**value["response"])
        if (not isinstance(response.text, str) or len(response.text.encode()) > max_response_bytes
                or any(v is not None and (type(v) is not int or v < 0) for v in (response.input_tokens, response.output_tokens))
                or not isinstance(response.finish_reason, str) or len(response.finish_reason) > 128
                or any(v is not None and (not isinstance(v, str) or len(v) > 2048)
                       for v in (response.model_version, response.request_id))):
            raise ValueError()
        return response
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ProviderError("transport_worker_outcome_unknown", uncertain=True) from None


class ProcessProvider:
    """Reviewed POSIX JSON adapter with a hard wall deadline and clean environment.

    A command reads {"request": ...} on stdin and emits {"response": Response
    fields} or a typed error envelope. Only fixed configured argv is executed.
    This boundary provides bounded transport, not isolation from hostile code;
    use an OS sandbox/container when a command is untrusted. Daemonizing or
    escaping the process group is unsupported. No source config selects commands.
    """
    paid = True
    execution_boundary = "reviewed_process"
    enforceable_deadline = True

    def __init__(self, command, *, reviewed=False, credential_env=(), credential_env_by_model=None,
                 python_paths=(), adapter_version=None,
                 max_request_bytes=20_000_000, max_response_bytes=8_000_000):
        if (reviewed is not True or not isinstance(command, (list, tuple)) or not command
                or len(command) > 128 or any(not isinstance(arg, str) or "\x00" in arg or len(arg) > 4096 for arg in command)
                or not Path(command[0]).is_absolute()
                or any(not Path(path).is_absolute() for path in python_paths)):
            raise ValueError("ProcessProvider requires a reviewed absolute command and runtime paths")
        _reviewed_argv(command)
        self.command, self.credential_env, self.python_paths = tuple(command), tuple(credential_env), tuple(python_paths)
        if credential_env_by_model is not None and (self.credential_env or not isinstance(credential_env_by_model, dict)
                or not credential_env_by_model
                or any(not isinstance(alias, str) or not 1 <= len(alias) <= 128
                       or not isinstance(names, (list, tuple)) for alias, names in credential_env_by_model.items())):
            raise ValueError("Declare fixed credentials or an explicit model-to-credential-name mapping")
        self.credential_env_by_model = (None if credential_env_by_model is None else
                                        {alias: tuple(names) for alias, names in credential_env_by_model.items()})
        if adapter_version is not None and (not isinstance(adapter_version, str) or not 1 <= len(adapter_version) <= 256):
            raise ValueError("adapter_version must be a bounded reviewed revision identifier")
        self.adapter_version = adapter_version
        self.cache_reuse_scope = "pinned_adapter_revision" if adapter_version else "process_instance"
        self.max_request_bytes, self.max_response_bytes = max_request_bytes, max_response_bytes
        self.cache_identity = "reviewed-process-v1:" + hashlib.sha256(json.dumps(
            {"command": self.command, "runtime_paths": self.python_paths, "adapter_version": adapter_version,
             "credential_env": self.credential_env, "credential_env_by_model": self.credential_env_by_model},
            sort_keys=True).encode()).hexdigest()
        if adapter_version is None:
            # A path or module name does not prove the reviewed program remains
            # unchanged. Prototype adapters cannot reuse another instance's cache.
            self.cache_identity += ":prototype-" + uuid.uuid4().hex

    def complete(self, request):
        names = self.credential_env
        if self.credential_env_by_model is not None:
            alias = request.get("expert", {}).get("model")
            if alias not in self.credential_env_by_model:
                raise ProviderError("missing_credential_configuration", failure_scope=FailureScope.MODEL)
            names = self.credential_env_by_model[alias]
        env = _environment(names, self.python_paths)
        fields = ("job_id", "logical_request_id", "attempt_id", "attempt_number", "expert", "prompt", "text", "max_output_tokens", "timeout_seconds")
        payload = _payload({"request": {k: request[k] for k in fields if k in request}}, self.max_request_bytes)
        return _exchange(self.command, payload, env=env, request=request,
                         max_request_bytes=self.max_request_bytes, max_response_bytes=self.max_response_bytes)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPProvider:
    paid = True
    execution_boundary = "reviewed_process"
    enforceable_deadline = True

    def __init__(self, profile, *, _direct=False, rejection_contract=None):
        from .config import load_profile
        self.profile = load_profile(profile)
        self._direct = _direct
        if rejection_contract is not None and not isinstance(rejection_contract, RejectionContract):
            raise ValueError("Expected a reviewed RejectionContract")
        self.rejection_contract = rejection_contract

    def complete(self, request):
        if not self._direct:
            # A process wall deadline bounds DNS/TLS/slow response reads. Only
            # this provider's credential is inherited; never all of os.environ.
            model = self.profile["models"][request["expert"]["model"]]
            provider = self.profile["providers"][model["provider"]]
            credential_name = provider["credential_env"]
            key = os.environ.get(credential_name) if credential_name else None
            if credential_name and not key:
                raise ProviderError("missing_credential_environment")
            env = _environment((credential_name,) if credential_name else ())
            wire_request = {k:request[k] for k in ("expert","prompt","max_output_tokens","timeout_seconds")}
            contract = None if self.rejection_contract is None else {
                "reference": self.rejection_contract.reference, "status_codes": sorted(self.rejection_contract.status_codes)}
            payload = _payload({"profile":self.profile,"request":wire_request,"rejection_contract":contract}, 20_000_000)
            return _exchange([sys.executable, "-m", "termfinder.transport_worker"], payload, env=env, request=request)
        expert = request["expert"]
        model = self.profile["models"][expert["model"]]
        provider = self.profile["providers"][model["provider"]]
        credential_name = provider["credential_env"]
        credential = os.environ.get(credential_name) if credential_name else None
        if credential_name and not credential:
            raise ProviderError("missing_credential_environment", uncertain=False)
        # Credentials stay in transport headers, never args/URLs/errors/logs.
        headers = {"Content-Type": "application/json"}
        if provider["adapter"] == "openai":
            url = provider["base_url"].rstrip("/") + "/chat/completions"
            if credential is not None:
                headers["Authorization"] = "Bearer " + credential
            body = {"model": model["model"], "messages": [{"role": "user", "content": request["prompt"]}],
                    "temperature": 0, "max_tokens": request["max_output_tokens"]}
            if provider.get("response_format", "json_object") == "json_object":
                body["response_format"] = {"type": "json_object"}
            if model["thinking_budget"] is not None:
                body["reasoning_effort"] = model["thinking_budget"] or "none"
        elif provider["adapter"] == "gemini":
            url = provider["base_url"].rstrip("/") + "/models/" + quote(model["model"], safe="") + ":generateContent"
            headers["x-goog-api-key"] = credential
            body = {"contents": [{"parts": [{"text": request["prompt"]}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": request["max_output_tokens"],
                                         "responseMimeType": "application/json"}}
            if model["thinking_budget"] is not None:
                body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": model["thinking_budget"]}
        else:
            raise ProviderError("unsupported_paid_adapter")
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        try:
            with opener.open(Request(url, data=json.dumps(body).encode(), headers=headers),
                             timeout=request["timeout_seconds"]) as result:
                raw = result.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ProviderError("response_size_limit", uncertain=True)
                payload = json.loads(raw)
                # A buggy endpoint may echo its authentication header. Do not
                # persist it as model text, request ID, model metadata or cache.
                if credential and (credential.encode() in raw or credential in json.dumps(payload, ensure_ascii=False)):
                    raise ProviderError("credential_echo_in_provider_response", uncertain=True)
        except HTTPError as e:
            # Scope and acceptance are independent. An OpenAI-compatible HTTP
            # status is not an idempotency/billing contract. Only the trusted
            # operator's reviewed declaration establishes known nonacceptance.
            from .resilience import parse_retry_after
            retry_after = parse_retry_after(e.headers.get("Retry-After") if e.headers else None, now=time.time())
            known_rejected = self.rejection_contract is not None and e.code in self.rejection_contract.status_codes
            raise ProviderError("http_" + str(e.code), uncertain=not known_rejected,
                                retryable=e.code in (408, 429, 500, 502, 503, 504),
                                retry_after_seconds=retry_after) from None
        except ssl.SSLCertVerificationError:
            raise ProviderError("tls_identity_verification_failed") from None
        except URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                raise ProviderError("tls_identity_verification_failed") from None
            raise ProviderError("transport_outcome_unknown", uncertain=True, retryable=True) from None
        except (TimeoutError, socket.timeout, OSError):
            raise ProviderError("transport_outcome_unknown", uncertain=True, retryable=True) from None
        except (ValueError, KeyError, TypeError):
            raise ProviderError("malformed_provider_envelope", uncertain=True) from None
        try:
            if provider["adapter"] == "openai":
                choice = payload["choices"][0]
                if choice.get("finish_reason") == "content_filter":
                    raise ProviderError("provider_content_blocked", uncertain=True, failure_scope=FailureScope.SOURCE)
                usage = payload.get("usage", {})
                return Response(choice["message"]["content"], usage.get("prompt_tokens"),
                                usage.get("completion_tokens"), choice.get("finish_reason") or "unknown",
                                payload.get("model"), payload.get("id"))
            feedback = payload.get("promptFeedback", {})
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                raise ProviderError("provider_content_blocked", uncertain=True, failure_scope=FailureScope.SOURCE)
            candidate = payload["candidates"][0]
            usage = payload.get("usageMetadata", {})
            output = usage.get("candidatesTokenCount")
            if type(output) is int:
                output += usage.get("thoughtsTokenCount", 0)
            finish = candidate.get("finishReason")
            if finish in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
                raise ProviderError("provider_content_blocked", uncertain=True, failure_scope=FailureScope.SOURCE)
            return Response("".join(p.get("text", "") for p in candidate["content"]["parts"]),
                            usage.get("promptTokenCount"), output,
                            "stop" if finish == "STOP" else "length" if finish == "MAX_TOKENS" else "unknown",
                            payload.get("modelVersion"), payload.get("responseId"))
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("malformed_provider_envelope", uncertain=True) from None


class FakeProvider:
    """Synthetic fixture extractor, not a lexical algorithm or quality benchmark.

    Supply explicit expectations or a script of Response/ProviderError instances
    for fault tests. Does not access environment variables or network.
    """
    paid = False
    execution_boundary = "trusted_in_process"
    enforceable_deadline = False

    def __init__(self, expectations=None, responses=None):
        if expectations is None:
            resource = files("termfinder").joinpath("fixtures", "expectations.json")
            expectations = json.loads(resource.read_text()) if resource.is_file() else []
        self.expectations = expectations
        from .store import digest
        self.cache_identity = "offline-fixture-v1:" + digest(expectations)
        self.responses = list(responses or [])
        self.calls = []

    def complete(self, request):
        self.calls.append(request["job_id"])
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        candidates = []
        text = request["text"]
        for e in self.expectations:
            if e.get("expert_ids") and request["expert"]["id"] not in e["expert_ids"]:
                continue
            if e.get("recipe_ids") and request["recipe"]["id"] not in e["recipe_ids"]:
                continue
            if e["expression"] not in text or e["context"] not in text:
                continue
            item = {k: e.get(k) for k in ("expression", "language", "sense", "context", "definition_quote", "translation")}
            item["start"] = text.index(e["expression"], text.index(e["context"]))
            item["attributes"] = e.get("attributes", {})
            candidates.append(item)
        return Response(json.dumps({"candidates": candidates, "coverage_complete": True}, ensure_ascii=False),
                        len(request["prompt"].encode()) // 3 + 1, 128 + len(candidates) * 40,
                        "stop", "synthetic-v1", "fake-" + request["job_id"])
