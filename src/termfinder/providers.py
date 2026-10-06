"""Small explicit transports with no SDK retries or response tool dispatch."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
import math
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler


@dataclass(frozen=True)
class Response:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str = "stop"
    model_version: str | None = None
    request_id: str | None = None


class ProviderError(Exception):
    """Safe category only; raw provider messages may contain credentials/source text."""
    def __init__(self, reason, *, uncertain=False, retryable=False, retry_after_seconds=None):
        super().__init__(reason)
        self.reason = reason
        self.uncertain = uncertain
        self.retryable = retryable
        self.retry_after_seconds = (retry_after_seconds if type(retry_after_seconds) in (int, float)
                                    and math.isfinite(retry_after_seconds) and retry_after_seconds >= 0 else None)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPProvider:
    paid = True

    def __init__(self, profile, *, _direct=False):
        self.profile = profile
        self._direct = _direct

    def complete(self, request):
        if not self._direct:
            # A process wall deadline bounds DNS/TLS/slow response reads. Only
            # this provider's credential is inherited; never all of os.environ.
            model = self.profile["models"][request["expert"]["model"]]
            provider = self.profile["providers"][model["provider"]]
            key = os.environ.get(provider["credential_env"])
            if not key:
                raise ProviderError("missing_credential_environment")
            env = {"PATH":"/usr/bin:/bin", "PYTHONNOUSERSITE":"1", "PYTHONDONTWRITEBYTECODE":"1",
                   "PYTHONPATH":str(Path(__file__).resolve().parent.parent), provider["credential_env"]:key}
            try:
                wire_request = {k:request[k] for k in ("expert","prompt","max_output_tokens","timeout_seconds")}
                payload=json.dumps({"profile":self.profile,"request":wire_request}, ensure_ascii=False, allow_nan=False).encode()
                if len(payload)>20_000_000: raise ProviderError("transport_request_size_limit")
                result = subprocess.run([sys.executable, "-m", "termfinder.transport_worker"],
                    input=payload,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                    timeout=request["timeout_seconds"], check=False)
            except subprocess.TimeoutExpired:
                raise ProviderError("request_wall_timeout_outcome_unknown", uncertain=True, retryable=True) from None
            except OSError:
                raise ProviderError("transport_worker_not_started") from None
            try:
                value = json.loads(result.stdout)
                if "error" in value:
                    raise ProviderError(value["error"], uncertain=value.get("uncertain",True), retryable=value.get("retryable",False), retry_after_seconds=value.get("retry_after_seconds"))
                return Response(**value["response"])
            except (ValueError, TypeError, KeyError):
                raise ProviderError("transport_worker_outcome_unknown", uncertain=True,
                                    retryable=result.returncode < 0) from None
        expert = request["expert"]
        model = self.profile["models"][expert["model"]]
        provider = self.profile["providers"][model["provider"]]
        credential = os.environ.get(provider["credential_env"])
        if not credential:
            raise ProviderError("missing_credential_environment", uncertain=False)
        # Credentials stay in transport headers, never args/URLs/errors/logs.
        headers = {"Content-Type": "application/json"}
        if provider["adapter"] == "openai":
            url = provider["base_url"].rstrip("/") + "/chat/completions"
            headers["Authorization"] = "Bearer " + credential
            body = {"model": model["model"], "messages": [{"role": "user", "content": request["prompt"]}],
                    "temperature": 0, "max_tokens": request["max_output_tokens"],
                    "response_format": {"type": "json_object"}}
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
        except HTTPError as e:
            # 429/400/401 are explicit rejections. 5xx may follow accepted work.
            from .resilience import parse_retry_after
            retry_after = parse_retry_after(e.headers.get("Retry-After") if e.headers else None, now=time.time())
            raise ProviderError("http_" + str(e.code), uncertain=e.code >= 500 or e.code == 408,
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
                usage = payload.get("usage", {})
                return Response(choice["message"]["content"], usage.get("prompt_tokens"),
                                usage.get("completion_tokens"), choice.get("finish_reason") or "unknown",
                                payload.get("model"), payload.get("id"))
            candidate = payload["candidates"][0]
            usage = payload.get("usageMetadata", {})
            output = usage.get("candidatesTokenCount")
            if type(output) is int:
                output += usage.get("thoughtsTokenCount", 0)
            return Response("".join(p.get("text", "") for p in candidate["content"]["parts"]),
                            usage.get("promptTokenCount"), output,
                            "stop" if candidate.get("finishReason") == "STOP" else "length",
                            payload.get("modelVersion"), payload.get("responseId"))
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("malformed_provider_envelope", uncertain=True) from None


class FakeProvider:
    """Synthetic fixture extractor, not a lexical algorithm or quality benchmark.

    Supply explicit expectations or a script of Response/ProviderError instances
    for fault tests. Does not access environment variables or network.
    """
    paid = False

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
