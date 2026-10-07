# Controlled recovery experiments

The V7 recovery runner compares actual Quarry `Engine`/`Project` persistence and
recovery against an uninterrupted reference. It uses synthetic frozen documents,
an offline request-keyed provider and a virtual scheduler clock. These are
engineering experiments; they provide no evidence of model extraction quality,
human usability, infrastructure throughput or provider billing.

```bash
quarry-study faults --out results/recovery-c2 --concurrency 2
quarry-study faults --out results/recovery-c1 --concurrency 1
quarry-study faults --out results/recovery-c4 --concurrency 4
```

The Python API is:

```python
from termfinder.fault_experiments import run_fault_suite

report = run_fault_suite("results/recovery", concurrency=2)
```

The destination must be new. Each arm owns a fresh database, response cache and
fake endpoint dispatch journal. The reference and fault arms share identical
frozen text and the same deterministic logical response function. Configuration
uses a fake profile with an explicit synthetic reservation rate. No credential,
network connection or paid transport is used.

## Falsifiable contrasts

1. After a settled response/cache transaction commits, interruption before
   grounding or job completion should preserve all reference evidence after
   resume, with no additional endpoint dispatch for that logical request.
2. If a request outcome has no durable response/cache settlement, resume should
   preserve its reservation as uncertain. Recovery may dispatch it again; this
   is reported as a repeated dispatch and potential duplicate billing exposure.
3. Truncation, malformed output and refusal should preserve any grounded partial
   discoveries and attempt bounded split recovery. Exhausted calls, reservations
   and deadlines should expose missing work using the full reference denominator.
4. Changing a model revision should invalidate the affected engine cache identity
   while leaving the logical response/evidence contract constant.
5. Exporting the same frozen dataset after live review and resume should produce
   identical JSONL/CSV and manifest bytes.

The report contains the observed quantities for each contrast. A failing contrast
must remain visible; the runner does not remove unsuccessful sources or enlarge
call/spending caps to complete an arm. The scheduler deadline is per run, as in
the existing engine; reopening gets that same bounded per-run allowance. A partial
arm receives no extra warm run merely to check export identity.

## Schedule and interruption boundaries

`logical_request_key` hashes source identity/hash, expert configuration, prompt
hash, window and output limit. Each schedule maps that key to local-attempt
actions. Other requests and thread completion order cannot consume its fault.
The journal records dispatches with a schedule hash and is reloaded on resume;
the provider's in-memory counters are discarded along with the collector.
Model revision is excluded only from the logical response key so the invalidation
contrast can keep outputs constant. Quarry's actual job/cache keys still bind
the model revision and all existing identity fields.

| Condition | Controlled intervention |
| --- | --- |
| Before dispatch | Interrupt after planning, before admission; no call or reservation |
| During uncertain request | Fake endpoint observes a request; collector loses its outcome before durable settlement |
| Before cache persistence | Returned response is lost before the settlement/cache transaction |
| Cache transaction rollback | Interrupt after cache insertion inside the settlement transaction; both cache and settlement roll back |
| After cache persistence | Interrupt after committed cache/settlement and before grounding |
| Grounding transaction rollback | Interrupt after occurrence insertion inside its transaction; grounding rolls back, committed response remains |
| After grounding before completion | Evidence commits; interrupt before marking the job done |
| Truncation | One complete candidate followed by truncated JSON, `length` finish reason |
| Timeout | Uncertain retryable timeout on one request's first attempt |
| Transient failure | Rejected retryable HTTP 503 on one request's first attempt |
| Malformed response | Invalid JSON on one request's first attempt |
| Refusal | Refusal text with `content_filter` finish reason on one request's first attempt |
| Call exhaustion | Eight planned requests, an injected timeout, and an eight-call cap |
| Budget exhaustion | One uncertain dispatch consumes the full reservation envelope |
| Deadline exhaustion | Retry becomes eligible after the one-second virtual run deadline |
| Cancellation | Researcher cancellation during retry cooldown, then explicit clear/resume |
| Cache invalidation | Change the GLM alias's synthetic model revision after initial completion |

Boundary experiments stage one target request through the real engine methods
and real SQLite transactions, inject a local exception, then reopen the database.
This keeps the boundary constant across concurrency settings. It is a controlled
interruption model, not an OS process-kill test of arbitrary simultaneous failures.
The timeout/transient/malformed/refusal/truncation arms run the actual concurrent
engine scheduler. Its per-model concurrency is one, and global concurrency is
configurable from one to eight. The tests compare dispatch assignment, responses,
evidence and reservations at concurrency one and four. Wall-clock timing and
thread ordering are intentionally outside that reproducibility claim.

## Outputs and interpretation

`report.json` holds the reference and all 17 fault arms. `corpus.json` records all
four frozen sources. Each arm includes its `schedule.json`, `report.json`, SQLite
project, provider dispatch journal and two exports of the same frozen version.

Evidence comparisons count both unique source-span records and unique
source-span/expert support. A healthy extractor can retain every source span while
another extractor leaves work incomplete; union evidence alone cannot establish
complete coverage. `missing_work` compares all eight reference root requests,
with recursive split completion and explicit unplanned/incomplete keys.

Recovery effort records post-reopen dispatches, automatic retry attempts, split
children, explicit cancellation clears and virtual scheduler waits. Human active
recovery time is unavailable with an explicit reason. Unknown reservations remain
in the ledger with simulated amounts; a retry does not settle the earlier unknown
attempt. The endpoint journal records observable dispatches, not successful
billing. No provider-side exactly-once promise follows from these experiments.

Cache invalidation repeats logical inputs intentionally and is labeled separately
from retries. A completed arm also gets a labeled warm resume check. Frozen export
identity is checked within each dataset version after a reversible live annotation
change and, for completed arms, warm resume. Independent runs have different UUIDs
and timestamps, so full snapshot byte equality across arms is not an asserted goal.

The checked-in [schedule](../examples/v7/faults/schedule.json) is an inert protocol
description. Generated schedules bind the actual target request hash. Run reviewed
code in the [offline verification sandbox](../tools/verify_offline.py) with an empty
credential environment and denied network; a subprocess timeout alone is not
filesystem or network isolation.
