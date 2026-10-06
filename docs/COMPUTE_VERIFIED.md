# Researcher-owned compute verification — 6.5.0

Recorded on 2026-10-06 with Python 3.12.14 on macOS. The source was built as an
independent wheel and installed into a fresh environment using only the existing
pinned pypdf 6.19.0 and pyarrow 25.0.1 wheels. No sibling package or source
PYTHONPATH was used by the installed checks. Existing V3/V4/V5, older V6
environments, study data, outputs and personal harness settings were preserved.

| Check | Result |
| --- | --- |
| Full installed-wheel test suite | 296 tests passed in 25.347 seconds |
| New compute/transport/operator-interface tests | 19 passed as part of the full suite |
| Three starter recipes × Broad/Specialists | Six acceptance projects passed |
| Fresh Codex, Claude and generic connection files | Created and checked only in synthetic workspaces |
| Actual installed stdio MCP workflow | Broad and Specialists passed; reconnect/resume, evidence, reversible annotations and frozen exports |
| Failed local and pending URL source plans | Visible in the harness; zero extraction jobs |
| Verification environment | Seatbelt network denied, unrelated personal file reads denied, empty credential environment; finite CPU/file/wall limits |
| Paid requests / external agent calls / cluster allocations | Zero |

The new tests verify authenticated API configuration, unauthenticated loopback
inference, remote plaintext and credential-bearing URL rejection, TLS-preserving
transport, selected-service credential isolation, optional response-format
compatibility, active-credential echo rejection before caching, operator-profile
protection against research-plan/manual overrides, finite zero-token-fee runs,
stale approval after compute changes, and byte-identical saved exports. Mocked
transport envelopes and synthetic markers stand in for APIs and credentials.

Wheel SHA-256:

```text
c7c461f9ed88a2aecc4c19781ab2dcbc3ac8279e751569459598278f7b966322
```

Local verification receipts are intentionally ignored rather than published:
`verification/compute-wheel-final.json`, `compute-build-final-sandbox.json`,
`compute-final-installed-suite-sandbox.json`, `compute-final-demo-sandbox.json`,
`compute-final-demo/acceptance_report.json`, `compute-final-harness-sandbox.json`, and
`compute-final-harness/acceptance_report.json`. Reproduce checks using
[VERIFICATION.md](VERIFICATION.md) with fresh output paths and the reviewed 6.5
installed environment. Earlier version receipts remain historical records.

## Credential audit scope

Before this change, published main
`950c34612bd10185c21e25fedb8d4a5675d4bde3` was audited across all five locally
reachable commits: 174 distinct historical blobs, 1,893,022 bytes. No API keys,
private keys or sensitive credential filenames were found by the rules. Eight
matches were confirmed synthetic test markers or deliberately invalid
example-domain credential URLs. All 17 ignore probes for credential, local
configuration and research-output paths passed. No personal credential files or
environment values were read or published.

The audit is a bounded pattern check, not proof against arbitrary unrecognized
secrets, remote-only refs, deleted unreachable objects or unrelated repositories.
Only credential variable names belong in saved profiles. Values are supplied to
the runtime by its operator and are not exported. Model responses echoing the
active transport credential are rejected with a safe error category before they
can enter the cache, inventory or exports.

## Remaining pilot verification

Local/GPU inference, current hosted-model availability/prices, live Claude/Codex
client activation, Linux execution, and Georgia Tech authentication/allocation
access were not tested. No benchmark accuracy or recall claim follows from these
software tests. An explicitly authorized pilot must pin the actual service and
model artifacts, establish source-use rights and account/allocation limits,
verify endpoint compatibility, and evaluate complete held-out sources. Native
Anthropic Messages, SSO/mTLS, allocation scheduling, model installation and OCR
remain external setup or adapter extensions. See [COMPUTE.md](COMPUTE.md).
