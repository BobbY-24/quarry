# Long-run reliability and operating procedure

The collector provides persistent model-specific backoff and failover, indexed scheduling,
bounded source residency, paginated inspection, staged exports, and consistent
local backups. It retains all grounded discoveries and records incomplete model
coverage. Source count alone does not establish capacity: lengths, windows,
specialist passes, output density, provider quotas, and available resources matter.

## Retry policy and the research behind it

The design follows [AWS's bounded retry guidance](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_mitigate_interaction_failure_limit_retries.html),
[Microsoft's transient fault guidance](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults),
and [the circuit breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker):
classify transient errors, use increasing delays with jitter, honor server timing,
limit retries at one layer, preserve failed work, and isolate an unavailable
dependency. The numeric schedule below is this project's requested policy, not
a universal industry default. The transport uses direct HTTP, so hidden SDK
retries cannot multiply the coordinator's attempts.

| Attempt | Minimum delay after the preceding failure | Default delay with jitter |
| --- | --- | --- |
| 1 | Initial request | No recovery delay |
| 2 | 30 seconds | 30–36 seconds |
| 3 | 120 seconds | 120–144 seconds |
| 4 | 240 seconds | 240–288 seconds |
| 5 | 480 seconds | 480–576 seconds |

A longer valid `Retry-After` takes precedence; both delta seconds and HTTP dates
are supported. Positive jitter avoids retrying before the requested minimum.
Invalid timing hints are ignored. A server delay over the configured finite
ceiling disables that model for this campaign rather than retrying early.

On the first transient failure, the model enters cooldown. Its other queued jobs
wait while **other models keep collecting**. One probe runs after the saved
delay. A successful probe closes the circuit and resets the consecutive-failure
count. After five consecutive failed attempts under the default policy, that
model is disabled across resumes; its unfinished jobs and evidence remain.
No automatic switch introduces an unapproved provider, model, or source.

HTTP 408, 429, 500, 502, 503, and 504 and network/wall timeouts are retryable.
Authentication, permission, configuration, and TLS identity failures fail fast.
HTTP 413 triggers bounded smaller-window recovery; exhausting that recovery
leaves a partial job rather than discarding its source. Missing usage retains
grounded results and disables that model to avoid unmetered additional calls.

The built-in transport has a process wall deadline and a worker alarm: a hung
DNS/TLS/read cannot occupy its lane indefinitely, including after the parent
process disappears. With 180-second request timeouts, five full timeouts and the
four base waits take up to 29.5 minutes before disabling a model; maximum default
jitter raises that to about 32.4 minutes. Server delays can increase this. Healthy
lanes continue throughout. Cancellation and overall deadlines stop new dispatch.
The engine drains returned results for at most 30 seconds, then cancels supported
process transports with their finite cleanup allowance and records unresolved
attempts. A provider may continue remote generation after transport cancellation.
Browser and MCP startup preserve a stop request delivered after the start reply.

The cumulative request-time budget persists across resumes and charges measured
request latency or the full timeout reservation for an unknown outcome. Queue
waits and source planning are excluded from that accounting; the separate finite
invocation deadline includes both. Attempts saved before `recovery-2` have no
historical request-time measurement, so their earlier usage is unknown.

When every configured model is unavailable, or the Gemini-only profile fails,
the run ends visibly partial. A remaining model cannot imply complete paired
coverage. Specialist lenses sharing an alias share its circuit.

## Capacity defaults and finite limits

New starter recipes use these execution defaults:

| Setting | Default | Validated ceiling |
| --- | ---: | ---: |
| Requests across the recipe/transport budget scope | 1,000,000 | 10,000,000 |
| Invocation deadline, including job planning | 7 days | 30 days |
| Timeout per model request | 180 seconds | 1,800 seconds |
| Global active workers | 4 | 64 |
| Active requests per model | 1 | 32 |
| Minimum start interval per model | 0.5 seconds | 3,600 seconds |
| Retries after initial attempt | 4 | 8 |
| Aggregate retries across the scope | 20,000 | 10,000,000 |
| Accepted `Retry-After` ceiling | 1 day | 7 days |
| Agent-planned sources | Up to 50,000 when requested | 50,000 |
| Recipe/agent JSON input | 32 MB | 32 MB |

Actual concurrency also respects file-descriptor headroom. These ceilings permit
large finite work; they are not throughput or memory guarantees. A researcher
still chooses the permitted sources and monetary budget. The upgrade command
does **not** raise spending, discovery scope, source limits, or hop limits.
Keep hops deliberately small. Discovery has its own persisted finite queue,
source/request/cost limits, and explicit adapters.

The aggregate call and retry counters persist across resume. Raising an
invocation's deadline does not reset charges. Job planning stops visibly partial
when the finite root-job cap is reached; stored sources remain available for a
larger explicitly configured run. Default extraction signatures exclude runtime
caps, so changing backoff/deadline does not repeat already completed extraction.

## What happens to billing and evidence

Automatic retry of unknown API outcomes is enabled in new recipes because it is
the requested long-run behavior. A timeout does not establish that the provider
rejected or did not bill the request. Each retry gets a separate persistent
attempt and reservation; unknown earlier reserves remain charged to the budget.
There is no exactly-once billing promise. Set
`execution.resilience.automatic_uncertain_retries=false` to disable automatic
retry of unknown outcomes; the model then disables for explicit review.

Spending admission checks total and stage reservations before dispatch, including
in-flight calls and unknown outcomes. If a reserve cannot fit, work stays pending.
Provider-reported usage settles known responses; cost is a token-price estimate,
not an invoice. An overrun of the reviewed provider token contract stops further
dispatch. Successful responses are cached atomically with cost settlement before
grounding, so interruption between those steps replays cached evidence.

Failover never removes single-model candidates, invents agreement, or marks an
unprocessed source complete. Saved runs include model circuits, attempt counts,
timing samples, retry decisions, aggregate counters, stop reasons, and coverage
by model. Audit/deferred queues and raw response proposals remain exportable.

## Researcher procedure

1. Install this directory independently with Python 3.11–3.13 and patched
   SQLite as in the README. Upgrade in a fresh environment, preserving the old
   runtime and a consistent project backup. Follow the
   [compatibility procedure](compatibility.md) before changing an existing study.

2. New starter recipes already include recovery. To upgrade a saved project,
   create a consistent backup first, then explicitly apply the new execution
   defaults. Original frozen versions and their prompts remain unchanged:

   ```sh
   termfinder --project my-study backup backups/my-study-before-upgrade.sqlite3
   termfinder --project my-study large-run
   termfinder --project my-study status
   ```

3. In the browser, choose the actual source cap (up to 50,000), languages,
   domains/folders, Broad or Specialists, and finite spending in the brief before
   creating the request for your personal agent. Validate and review its returned
   plan. Alternatively use a reviewed URL list and recipe:

   ```sh
   termfinder --project my-study ingest --url-list sources.txt --metadata metadata.json
   termfinder --project my-study estimate
   ```

   URLs still require recipe-approved domains. Manual URL-list ingestion is a
   sequential import, not a complete automatic fetch-retry campaign. For durable
   bounded website discovery use `discover` / `discover --resume`; applied agent
   plans also record imported source IDs and skip successful repeated imports.

4. Rehearse with fixtures offline. After separate explicit authorization for a
   real pilot, use the selected profile's credential **environment variables**,
   then `collect --allow-paid` or `serve --allow-paid`. No key goes in arguments.
   Before the large run, verify model availability, account RPM/TPM quotas,
   provider rates, source-use permissions, and the largest request reserve.
   Lower per-model concurrency or increase its interval if account quotas require
   it. Quotas shared by several projects/accounts are not coordinated globally.

5. Watch progress. The browser shows cooldown countdowns, disabled aliases,
   remaining models, costs, and incomplete coverage. Records, evidence, and
   recovery jobs are paginated in groups of 50. Whole source text loads on demand.
   `status` is compact; `inspect` and frozen exports retain the complete inventory.
   Cancellation stops new work; `resume` keeps completed/cached work:

   ```sh
   termfinder --project my-study cancel
   termfinder --project my-study status
   termfinder --project my-study resume --offline
   ```

   The last command is an offline rehearsal. A previously authorized live pilot
   must use `resume --allow-paid` and its original live transport; switching to
   the fake transport creates a distinct simulation scope and is not live resume.

6. After resolving an outage/configuration problem, explicitly re-enable that
   alias. Resuming alone does not silently reset a disabled circuit:

   ```sh
   termfinder --project my-study reset-model glm
   termfinder --project my-study resume --offline
   ```

   In the browser use **Re-enable glm**, then Collect / resume. Reset retains old
   unknown charges, historical model failures, and dataset versions. Jobs with
   unknown usage or older manually unresolved outcomes require the existing
   `resolve-uncertain` workflow; resetting a model does not erase them.

7. Save a version after collection stops and export twice if checking reproduction:

   ```sh
   termfinder --project my-study snapshot collection-v1
   termfinder --project my-study export VERSION_ID exports/v1
   termfinder --project my-study backup backups/my-study-after-v1.sqlite3
   ```

   Exports stage on disk, check every existing destination, publish whole files
   atomically, and publish the manifest last. Never treat an export directory
   without its final manifest as complete. If a process is killed during staging,
   rerun the same frozen-version export; abandoned `.termfinder-export-*` folders
   may be removed manually after ensuring no export is active.

Notebook controls use the same persistent project:

```python
from termfinder import Project
project = Project("my-study")
project.configure_large_run()             # preserves money and source scope
project.status()["model_health"]
project.page_inventory(limit=50)         # bounded inspectable view
project.reset_model("glm")               # explicit recovery after investigation
project.store.backup("backups/study.sqlite3")
```

## Failure inventory and practical limits

| Failure mode | Protection / remaining operating requirement |
| --- | --- |
| Slow API, DNS/TLS stall, slow response read | Built-in transport subprocess deadline plus worker alarm; timeout becomes an auditable unknown attempt. |
| Repeated 429/5xx, retry storm | Saved exponential schedule, positive jitter, `Retry-After`, one probe per alias, finite aggregate retry budget, per-model concurrency/pacing. |
| One unavailable extractor | Healthy lanes continue; failed alias stays disabled; all grounded discoveries retained; per-model incomplete coverage. |
| Shared provider/account outage | Each model can fail; all-unavailable run ends partial. GLM and DeepSeek may share a provider/account, so this is not independent-provider availability. |
| Crash, forced kill, laptop sleep | Durable jobs/costs/circuits; cached responses replay; unsolved dispatches retain reserves; resume checks wall-clock cooldown and monotonic invocation deadline. OS sleep can delay scheduling and invalid wall-clock adjustments can delay cooldown. |
| Truncated output / oversized request | Retain parsed grounded objects; bounded overlapping smaller windows; terminal partial jobs and audit when recovery is exhausted. |
| Millions of per-job rereads | Indexed ready queues, run membership index, connection reuse, incremental scoped ledger; old scheduler indexes pruned while history remains. |
| Large source text in RAM | Source LRU at most four entries and a 16-million-character target; at least one accepted source must fit. Estimates retain metadata/lengths, not all source text. |
| Browser overload | Compact counts and paginated inventory/evidence/recovery, lazy full sources, Unicode-aware search/excerpts, no overlapping polls, finite browser request deadlines. Explicit full source/CLI inventory can still be large. |
| Slow or excessive local HTTP clients | At most 16 request threads and 30-second socket I/O timeouts; excess clients close promptly. Collection uses its independent bounded worker pool. |
| Disk exhaustion | Stop dispatch below 256 MiB free; SQLite durable transactions; export staging prevents half-written final files. This cannot stop another process exhausting disk between checks. Maintain substantial spare storage. |
| WAL growth, competing readers/writers | Short transactions, 30-second bounded busy wait, passive checkpoint, one collection lock per project. Keep projects on local disks, not network/sync filesystems. |
| Backup during WAL writes | SQLite online backup with bounded progress and integrity check; never copy just the active database file. Restore the backup as `project.sqlite3` in a new directory. |
| Large freeze/export | On-disk export staging, streamed JSONL/CSV/dataset serialization, Parquet batches. Inventory is limited to 64 MiB serialized table data and a frozen dataset to 128 MiB. Snapshot creation and Python dataset/export views still materialize the frozen dataset in RAM; these serialized limits are not peak-RSS limits. Partition larger collections into finite studies. |
| Bad source, inaccessible page, OCR needed | Existing source/page limits, bounded fetch/PDF parsing, explicit failures and pending discovery; OCR remains an extension. Extraction retries do not make blocked websites accessible. |
| Custom Python provider never returns | Trusted notebook/test Python providers must return cooperatively. A Python thread cannot forcibly stop arbitrary running code or guarantee process shutdown. Production custom transports must use the reviewed process-adapter boundary with finite request/response sizes and deadlines. |
| Unknown provider invoice / service quota changes | Preserve reservations and safe categories; verify current account quotas/rates before an authorized pilot; do not infer an invoice from token estimates. |
| Publication overclaims | Export failures, degradation and model coverage; audit exact provenance; use complete held-out source labels for measured recall. Candidate counts and successful retries are not extraction-quality evidence. |

WAL/checkpoint and backup choices follow [SQLite's WAL guidance](https://www.sqlite.org/wal.html)
and [online backup documentation](https://www.sqlite.org/backup.html).
The custom-thread limitation follows [Python's executor cancellation semantics](https://docs.python.org/3/library/concurrent.futures.html).

The extraction engine remains a single-machine collector. The separate cluster
controller submits a reviewed worker to Slurm; it does not turn one SQLite
project into a live distributed database or a hosted multi-user service.
No real API outage/load test, paid pilot, live website crawl, GT job, or
publication was performed during this build. A pilot should begin with a small
authorized sample to calibrate latency, quotas, reservations, and quality before
enlarging the run.

## Durable GT jobs and reconnecting an agent

For a job that must outlive a laptop or MCP session, follow
[the GT procedure](../guides/gt-compute.md). The ordinary local `collect` worker is tied
to its connection and requests cancellation on disconnect. A submitted cluster
worker is owned by Slurm: reconnect, open the same study and inspect its saved
job before considering resume. A missing chat connection is not evidence of a
missing scheduler job.

Keep the live worker database on its node-local scratch filesystem. Only
consistent checkpoints/results belong on approved durable shared storage.
Do not open the same WAL database from two nodes or point job arrays at it.
SQLite's online backup includes committed WAL state; copying only the live
database file does not. [SQLite WAL](https://www.sqlite.org/wal.html),
[online backup](https://www.sqlite.org/backup.html).

Periodic backups do not accumulate once per interval indefinitely. After a
successful receipt, the worker retains its latest/previous generations and all
saved job references, pruning only its own unreferenced generations. Published
checkpoint generations are conservatively bounded by four times the finite
submission cap. Prior-worker checkpoints and immutable source/review files stay
intact. Hard-crash orphan files require operator inspection; no blanket physical
disk cap is promised after storage failure. The first checkpoint/control failure
stops dispatch, with only bounded final/recovery backup attempts.

Set a finite checkpoint interval and shutdown grace greater than the longest
model request plus settlement time. The cluster profile validates those limits
against the recipe. The worker stops dispatch before its walltime and responds
to shutdown signals. A lost node or forced kill can still lose work since the
last completed durable checkpoint. Resume retains checkpointed jobs, cached
replies, coverage, failures and cost reservations; uncheckpointed work may repeat.

Submission timeout is an uncertain scheduler outcome, separate from an uncertain
inference request. Preserve its full allocation reservation. Explicitly
reconcile the saved submission with Slurm's job ID, or obtain a verified-absence
decision, before submitting a replacement. Do not wrap submissions in a second
retry loop or silently reset cumulative GPU-hour/submission limits.

Cancelled, walltime-limited and failed jobs remain visible. Inspect their saved
checkpoint/result before restarting unfinished work. Complete the intended
bounded resumes before importing into the control inventory; import validates
the stopped job's available checkpoint. An explicit resume requests another
finite allocation within the saved caps;
it does not authorize infinite resubmission or a changed model/source plan.

See [cluster command and Python examples](../../examples/gt-compute/README.md).
Pinned runtimes, checkpoint staging, institution access and any SSH control
connection are operator-provided resources. Select either an existing approved
gateway with a CPU collector or the fixed reviewed vLLM launcher using pre-staged
safe files inside the GPU allocation. Server choices and file digests are bound
to the concrete resource review. Resume cannot download a model or switch to an
unapproved launcher; it preserves the fixed configuration and finite startup.

## Offline verification

`tests/test_resilience.py` injects timeouts, permanent failures, budget stops,
crashes, long server hints, both-model and single-model outages, cached probe
recovery, cancellation/resume, mode changes, paging, disk pressure, and backup
restore. Timed backoff uses a fake clock, not 15-minute test sleeps.

`tools/soak_resilience.py` rehearses 2,500 synthetic sources, 10,000 extraction
roots, intermittent outages, interruption/reopen, cache reuse, compact browsing,
double export in all formats, and backup restoration in the reviewed no-network
OS sandbox. Write each new result to a fresh ignored `verification/` directory.
The [reproduction procedure](../development/reproduce.md) and
[stress-test guide](stress-tests.md) describe current bounded checks. The
[prior V6.7 report](results-v6.7.md) records its original measured artifact.
