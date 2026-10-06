# V6.2 resilience verification — October 5, 2026

V6.2.0 was built and installed independently in `.venv-6.2`. The earlier
V6.0/V6.1 wheels and environments remain available. A copy of the pre-change
V6.1 source, tests, tools, and documentation is preserved in
`verification/resilience-original-6.1/`. This change did not run or modify V3,
V4, V5, or their collection outputs.

The final wheel is `dist/nlpx_termfinder-6.2.0-py3-none-any.whl`, SHA-256:

```text
986c6dd6bbfc4ee4987b446b1f3c8a03f1e8a2b062a84d0e57d29211d34bf6f9
```

The preserved V6.1 wheel still has SHA-256:

```text
1fa19cce60266c2eb0fcc9ef5cd30dd5bfea32018cd99ff9d4e81d8d50513eca
```

## Release checks

| Check | Observed result | Evidence |
| --- | --- | --- |
| Final source suite | **173 tests passed**, 16.886 seconds | `../verification/resilience-final-suite-sandbox.json` (local artifact) |
| Final installed-wheel suite | **173 tests passed**, 17.349 seconds; installed package rather than source imports | `../verification/resilience-final-installed-suite-sandbox.json` (local artifact) |
| Independent build and install | Pinned local dependencies, fresh environment, denied network and empty credential environment | `../verification/resilience-final-build-sandbox.json` (local artifact), `../verification/resilience-final-install-sandbox.json` (local artifact) |
| Installed CLI and notebook | Init, ingest, estimate, interruption, resume, inspect, freeze, all exports, large-run settings, model reset, consistent backup; **8 notebook code cells** executed | `../verification/resilience-final-installed-cli-report.json` (local artifact), `../verification/resilience-final-installed-cli-sandbox.json` (local artifact) |
| Installed agent workflow | Five research-inspired briefs configured: neologisms, cultural entities, cultural opinions, legal ideas, medical sentences; **9 notebook code cells** executed | `../verification/resilience-final-installed-agent-report.json` (local artifact), `../verification/resilience-final-installed-agent-sandbox.json` (local artifact) |
| Large synthetic campaign | **2,500 sources, 10,000 extraction roots**; interrupted, reopened, resumed, cached, frozen, exported twice, backed up and restored | `../verification/resilience-final-soak-2500.json` (local artifact), `../verification/resilience-final-soak-sandbox.json` (local artifact) |
| Actual installed browser | Pagination, search outside the first page, exact evidence, lazy source loading, annotation/undo, visible disabled-model recovery, explicit model reset | `../verification/resilience-final-browser-report.json` (local artifact), `../verification/resilience-final-browser-sandbox.json` (local artifact) |

The unit suite includes all three starter term policies in Broad and Specialists
modes. Added failure injection checks saved retry timing and jitter,
`Retry-After` seconds/dates, invalid or excessive hints, transient versus
permanent errors, one-model and all-model outages, per-alias circuit isolation,
cached probe replay, retry and spending admission, cancellation, process
deadlines, interrupted recovery, missing usage, disk pressure, backup restoration,
paginated inspection, bounded HTTP service threads, and interrupted export
publication. Backoff tests advance a fake clock; they do not sleep for the
real recovery schedule. Existing grounding, Unicode offsets, sense preservation,
schema validation, provenance, annotation, and reproducible export checks remain.

## What the 2,500-source test establishes

The installed package processed **9,921,390 parsed characters**. Both model lanes
finished their 5,000 roots. Two injected unknown-outcome failures produced two
extra attempts: GLM 5,002 and DeepSeek 5,000. Those earlier unknown attempts
remained in the audit/cost inventory. A deliberate job-limit interruption was
followed by reopening the persistent project and resuming it. Resuming again
after completion issued **zero additional calls**.

The test froze one dataset and exported in all supported formats twice, with
the requested format order reversed. **43 exported files were byte-identical**.
The consistent SQLite backup reopened with matching inventory counts. The
paginated browser response was 237,564 bytes; the database was 139,411,456 bytes.
The parsed-length estimator forecast 11,500 requests, including its recovery
allowance; the scripted campaign made 10,002 attempts.

Measured on this macOS machine, the entire synthetic rehearsal took **59.283
seconds**, with peak RSS **646,578,176 bytes** (about 616.6 MiB). Ingestion took
5.615 seconds, collection/resume/cache checks 39.642 seconds, estimate/paging
1.750 seconds, and snapshot plus both exports 10.527 seconds. These numbers are
local synthetic software measurements. They are **not real API throughput,
website crawling capacity, or worst-case PDF memory estimates**.

## Browser observations

A fresh synthetic project with 70 sources/records/evidence occurrences was
copied into a separate verification workspace. Its deliberately disabled GLM
lane displayed five failures, partial coverage of 70/140 extraction roots, and
an explicit deferred-job recovery card. The remaining lane was shown as healthy.

The first inventory page displayed 50 of 70 records. Searching for
`moonstep001`, absent from that page, returned only that matching record while
the previously selected `moonstep000` remained inspectable separately. Selecting
the result showed the literal context in `synthetic-1.txt`, offsets `[0, 11)`.
Opening the stored source loaded its complete synthetic text. Approving the
record and then undoing the annotation restored `unreviewed` while retaining the
reversed annotation in history. Clicking **Re-enable glm** restored its pending
job and closed its circuit; all 70 records and evidence occurrences remained.
Browser warning/error logs were empty at inspection. The temporary tab was
closed, the finite test server stopped, and no listener remained on port 8766.

## Isolation and limits

Executed application checks used the reviewed macOS Seatbelt launcher, bounded
CPU/file/process limits, an empty credential environment, denied outbound
network, and denied unrelated file reads. Probe reports confirm those denials.
The browser alone allowed inbound access at `127.0.0.1:8766` for a finite
five-minute session. **No paid provider calls, external agent calls, live
collection campaign, publishing, or contact with anyone occurred.**

This verifies failure-handling mechanics against controlled fixtures. It does
not measure provider billing after a real timeout, account-wide RPM/TPM limits,
real network failures, model accuracy, complete-source recall, or live Linux
load. Unknown requests can have been billed; retries preserve their reserves and
can incur another charge. GLM and DeepSeek can share a provider/account outage.
Very large frozen datasets still need adequate RAM or finite study batches.
Custom Python providers must honor their timeout contract. Projects are intended
for one machine on a local filesystem.

See [the operating procedure](LONG_RUNS.md) for the exact retry schedule, finite
caps, failure inventory, CLI/notebook controls, and the small explicitly
authorized pilot needed to calibrate live quotas, costs, and research quality.
