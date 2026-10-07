# Reviewed process adapters and offline fault tapes

Most researchers should use the packaged HTTP adapters described in [compute setup](COMPUTE.md). They already run in a private process with a finite transport deadline. `ProcessProvider` is the Python extension point for an operator's reviewed custom SDK, serving client, or executable. Source content and model proposals cannot select a command, environment, endpoint, or adapter configuration.

## Execution contract

`ProcessProvider` supports macOS and Linux/POSIX. The operator supplies a fixed absolute executable and reviewed argv, attests `reviewed=True`, and pins `adapter_version` to the reviewed program revision. The command must read one bounded JSON request on stdin, write exactly one JSON envelope on stdout, and keep all descendants in its process group. A process that daemonizes or escapes its group is unsupported. This deadline boundary is not a security sandbox: use a reviewed OS sandbox/container for unfamiliar code.

```python
import sys
from termfinder.providers import ProcessProvider

provider = ProcessProvider(
    [sys.executable, "-m", "my_reviewed_adapter"],
    reviewed=True,
    adapter_version="reviewed-adapter-git-revision",
    credential_env_by_model={
        "glm": ["MY_GLM_SERVICE_KEY"],
        "deepseek": ["MY_DEEPSEEK_SERVICE_KEY"],
    },
    max_request_bytes=2_000_000,
    max_response_bytes=1_000_000,
)
```

Replace the module and revision with the actual reviewed adapter. Configure the project profile separately with the operator's model identities, context limits, and rates. These environment values come from the researcher's own shell/credential manager, never a recipe or an argument. A single-service adapter may use `credential_env=("MY_SERVICE_KEY",)` instead. Empty credentials support an operator's approved local model. A model routing map sends only the selected model's listed names/values; unrelated credentials are absent. `credential_env` and `credential_env_by_model` are mutually exclusive.

The clean worker environment contains a minimal PATH, reviewed Python import paths, and only those selected credentials. Python loader controls, library injection controls, shell startup controls, and HOME/TMPDIR cannot be passed as credential names. Command validation rejects recognizable keys, common credential flags/authentication headers, and URLs with userinfo, query strings or fragments. It cannot recognize every arbitrary password string: operator review must ensure argv has no credentials. No key values enter cache identity.

Omitting `adapter_version` is allowed for a prototype, but gives that provider instance a unique cache identity. Its cache is not reusable across newly constructed instances. A pinned revision permits reuse for the same command, import paths, credential-name routing, source, recipe, prompt and model configuration. Reusing a revision after changing its adapter breaks that operator contract.

The worker receives only the configured extraction fields:

```json
{
  "request": {
    "job_id": "job_...",
    "logical_request_id": "logical_...",
    "attempt_id": "attempt_...",
    "attempt_number": 1,
    "expert": {"id": "glm-general", "model": "glm", "lens": "...", "stage": "extraction", "communities": ["*"]},
    "prompt": "The complete researcher-configured extraction prompt for this window",
    "text": "This extraction window only",
    "max_output_tokens": 1024,
    "timeout_seconds": 30
  }
}
```

The full source document, project recipe, cancellation event, credentials, and command configuration are absent from this JSON. The adapter must not interpret model output as tools or configuration. Successful stdout uses the existing extraction response schema inside `text`:

```json
{
  "response": {
    "text": "{\"candidates\":[],\"coverage_complete\":true}",
    "input_tokens": 123,
    "output_tokens": 18,
    "finish_reason": "stop",
    "model_version": "reported-serving-revision",
    "request_id": "safe-provider-request-id"
  }
}
```

Unavailable token counts/model versions/request IDs are `null`, not invented zero values. Missing usage retains uncertainty and the full cost reservation. `finish_reason="length"` triggers bounded extraction recovery. Configured and reported model identities remain distinct; operator review must investigate drift or missing identity. An API alias is not necessarily equal to a serving revision, and a cluster artifact declaration is not a cryptographic attestation of the running model.

A reviewed adapter can return a typed safe error category:

```json
{
  "error": "http_422",
  "failure_scope": "request",
  "uncertain": true,
  "retryable": false,
  "retry_after_seconds": null
}
```

Scopes are `request`, `source`, `model`, `provider`, `local`, or `uncertain`. Scope describes what failed; `uncertain` separately describes whether accepted/billable inference can be ruled out. A request failure should not poison healthy requests to the same model. HTTP status alone does not establish nonexecution: generic compatible API errors retain uncertainty. Only a trusted reviewed provider no-acceptance guarantee can justify `uncertain=false`. `RejectionContract(reference=..., status_codes=frozenset(...))` is an explicit operator declaration, not an automatically verified guarantee. Keep its supporting contract alongside the run configuration.

The packaged HTTP adapters recognize explicitly filtered text responses using the documented [OpenAI completion finish reason](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/retrieve) and [Gemini prompt feedback/finish reasons](https://ai.google.dev/api/generate-content). They record a source-scoped blocked-content failure and conservatively retain the reserve. These content-status schemas do not establish a provider no-charge guarantee. Unknown Gemini finish reasons remain `unknown`, rather than being mislabeled as token truncation.

Malformed envelopes, crashes, timeouts, output overflows, and cancellation after dispatch remain unknown outcomes. The private watchdog starts before the adapter executes and detects owner pipe closure or deadline expiry; normal completion also kills process-group descendants. A request that exceeds the input bound or is cancelled before startup is rejected before execution. stderr is discarded and never copied into audit text. A local process kill cannot prove an already accepted remote request stopped or was not billed.

## Notebook and fixture limits

Notebook providers and `FakeProvider` run trusted Python in process. They are useful for offline development; an arbitrary in-process `complete()` has no enforceable termination boundary. Thread cancellation cannot kill stuck Python/native SDK code. Production adapters requiring a hard deadline should use the packaged HTTP boundary or `ProcessProvider`. The internal HTTP `_direct` option belongs only to the worker and mocked unit tests.

## Reproducible failure experiments

`KeyedFakeProvider` assigns response/error entries by stable key and attempt, never completion order. `FaultTapeProvider` adds bounded delays/errors to a base provider. For engine experiments prefer `key_scheme="request"` and `request_fingerprint(request)`, which uses the engine's logical request identity when present. That logical identity excludes cache/tape/job/attempt IDs; prototype requests fall back to a hash of prompt/text/expert/output limit. A `job_id` already contains transport cache identity, so deriving job IDs with one provider and then replacing its response-tape identity creates a circular key dependency.

```python
from termfinder.fault_provider import (
    KeyedFakeProvider, FaultTapeProvider, FaultAction, request_fingerprint,
)
from termfinder.providers import ProviderError, Response, FakeProvider

# request is a planned engine request from an independent planning project.
key = request_fingerprint(request)
responses = KeyedFakeProvider(
    {(key, 1): Response('{"candidates":[]}', 20, 5, "length", "fixture-v1")},
    key_scheme="request",
    fallback_provider=FakeProvider(explicit_synthetic_expectations),
)
faults = FaultTapeProvider(
    responses,
    {(key, 2): FaultAction(error=ProviderError("fixture_timeout", uncertain=True), delay_seconds=0.01)},
    key_scheme="request",
)
```

The response tape hash and offline fallback identity participate in cache identity. A missing response-tape entry rejects before work unless an explicit offline fallback was supplied. Runtime fault tape identity is recorded separately and leaves the base extraction identity unchanged by default: a previously completed cache hit will not replay a scheduled transport failure. Set `cache_faults=True` only when the experimental design intentionally treats runtime faults as a distinct extraction identity. Use fresh independent projects for cold comparisons; report warm-cache recovery as a separate arm.

These helpers are trusted in-process tests, not production deadlines or real provider cost measurements. Retain the tape hash, key scheme, software revision, policy, cache condition and attempt outcomes with an experiment. [Stress rehearsals](STRESS_TESTS.md) combine keyed faults with real collector SIGKILL, bounded transport processes, frozen exports and local account coordination.
