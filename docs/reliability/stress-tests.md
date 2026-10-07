# Reliability stress rehearsals and a future compute pilot

The offline rehearsals measure software behavior on bounded synthetic fixtures. They do not measure extraction precision/recall, provider latency, Georgia Tech GPU throughput, or real fees. Use [source-level evaluation](../research/evaluation.md) for extraction quality and complete held-out source annotations; reviewing only emitted candidates cannot measure false negatives.

## Run the offline rehearsals

Review the helper code first and use the real OS isolation workflow in [verification](../development/reproduce.md) or [CI](../development/ci.md). A virtual environment, clean environment, or subprocess timeout alone is not a security sandbox. The build verification uses macOS Seatbelt with network denied, unrelated user-data reads denied, clean environment, CPU/descriptor/file bounds, and a finite outer wall deadline. Each wrapper report records whether both isolation probes passed.

Inside that reviewed isolated runtime:

```sh
python tools/reliability_load.py --sources 1000 --report verification/reliability-load-1000.json
python tools/reliability_mixed.py --sources 120 --report verification/reliability-mixed-120.json
python -m unittest discover -s tests -p test_provider_boundary.py -v
python -m unittest discover -s tests -p test_process_recovery.py -v
```

The standard load helper accepts 1–5,000 sources. It ingests bounded short synthetic English sources, interrupts at a finite job limit, resumes from the durable project, repeats a completed run to check cache reuse, checks every exact expression span and source hash, inspects a bounded inventory page, freezes one version, and exports the same version twice in CSV/JSONL/Parquet/annotation formats. The report contains per-stage timings, process RSS and CPU, sampled descriptor count, measured disk sizes, evidence hashes, export hashes and simulated stage costs. Disk measurements include the project and both export copies. FD sampling is every 20 ms, so the reported peak is sampled; phase-boundary disk sizes are not a continuous high-water measurement. RSS covers the collector process and Python/Arrow threads, not a real model server.

The mixed helper accepts 10–120 sources and uses two independent projects sharing one actual same-host SQLite account registry. It combines HTML headings/table text, Markdown, CJK/Arabic text, 20,000-character documents, and the packaged two-page PDF fixture. Broad and Specialists process the same frozen sources. Faults are assigned to logical extraction requests and attempt numbers: known request rejection, known throttling/retry, finite variable delays, a truncated response, and one grounded response with unavailable token usage. These are explicit synthetic provider contracts, not assumptions about real HTTP billing.

During collection the helper reads paginated inspection payloads concurrently, cancels Broad, drains its returned responses, creates a consistent local backup, and uses finite concurrent resume rounds for transient quota stops. It checks the shared in-flight cap, preserves the unknown attempt's nonzero synthetic reserve and account lease, compares the final grounded inventory against a fresh healthy counterfactual on the same sources, repeats the final degraded/completed state without further fixture calls, and double-exports frozen versions. Both the unknown failure and known rejected request remain visible; inventory equivalence does not imply operational completion or measured recall.

The inspection measurement calls the browser's data-pagination API directly. It does not start a server or measure browser/HTTP rendering throughput. The local backup does not validate shared-filesystem checkpoint generations or scheduler preemption; separate cluster recovery tests cover those boundaries. All fake calls are trusted in-process and intentionally finite. Real never-returning, crashed and oversized adapters are tested separately through the reviewed process boundary.

## What must survive a crash

`tests/test_process_recovery.py` kills an actual collector process with SIGKILL at three boundaries and reopens the project:

1. After dispatch, before a response receipt: the job and attempted cost remain uncertain, with no invented settlement or automatic repeat under the test's conservative retry policy.
2. After known-usage receipt commit, before grounding: the saved response is replayed once without repeating inference; offsets are inspected and all frozen exports reproduce byte for byte.
3. After unknown-usage receipt commit, before grounding: the saved response's original job provenance is recovered, while usage uncertainty and its full reservation remain unresolved.

The third regression failed during hardening because uncertain jobs were never selected for receipt replay. The fix separates replaying source-backed evidence from resolving billing. The first two are retained regression coverage for established behavior. The process transport tests additionally kill the owner, run a never-returning child, create a descendant, overflow stdout, cancel running work and validate selected credential routing. Process-group escape/daemonization and arbitrary in-process SDK hangs remain unsupported; see [reviewed adapters](process-adapters.md).

The mixed rehearsal exposed a second reliability issue: when a model became disabled or entered probe cooldown, its queued head could remain in the account FIFO and obstruct a healthy extractor. The engine now relinquishes those obsolete waiters promptly. A direct regression checks that a queued healthy alias can proceed after the disabled head is removed. Brief finite waiting handles transient local contention; capacity held by unresolved remotely accepted work is preserved instead of silently released.

## Review the reports

Keep wrapper and workload reports together. Confirm isolation probes, source count, software revision, source/tape hashes, configuration, cold versus warm cache condition, complete attempt statuses and unresolved reservations before interpreting timing. A tiny smoke run validates mechanics; a larger rehearsal exercises scale. Neither establishes statistical power, generalization to real source distributions, or a model-quality claim.

Useful review questions include:

- Were returned evidence and raw response receipts durable before downstream processing?
- Did failures affect the correct request/source/model/provider scope, while billing uncertainty remained independent?
- Did cancellation and shutdown finish within finite bounds, and were every dispatched attempt and every pending source visible?
- Were source offsets and hashes verified against frozen parsed text, including Unicode and PDF page locations?
- Were concurrent studies coordinated through the same local registry, and were outside clients excluded from that claim?
- Did unknown outcomes retain account capacity and spending/time reserves across resume?
- Did the frozen dataset export the same bytes without another model call?
- Are latency, memory, disk and invoice quantities measured, estimated, simulated or unavailable, with scope disclosed?

## Georgia Tech stress pilot: plan only

No API collection, GPU allocation, scheduler submission, model download or real compute stress was launched during this build. A researcher must explicitly authorize the real pilot. [Georgia Tech setup](../guides/gt-compute.md), [compute configuration](../guides/compute.md), and the verified local cluster adapter explain available interfaces without asserting a particular student's allocation or permissions.

After authorization, proceed in small bounded phases:

1. **Resolve operator facts.** Confirm the student's actual account/allocation, permitted partition/QOS, approved storage, data-use policy, approved model-serving environment, reviewed model/tokenizer revisions, and installed scheduler commands with the relevant administrators. Preserve SSH/TLS verification. Do not infer GPU type, module name, host, account or scheduling entitlement from these docs.
2. **Approve a pilot sheet.** Freeze a small source list and recipe, set finite request/token/spending/cumulative-time limits, concurrency and shutdown deadlines, and an allocation/GPU-hour cap. Record API rates separately from scheduler/accounting costs. If allocation charges are unavailable, record null with a reason; zero local per-token service fees do not imply free GPU time. Use only the student's own credential environment or their authorized local serving endpoint.
3. **Test one allocation path.** Run the offline fixtures inside the assigned allocation before any real inference. Validate local scratch SQLite, a trusted shared checkpoint/journal location, source hashes, environment allow-list, model-serving receipts and cancellation. The account registry currently coordinates one host; copied registries or SQLite on an arbitrary shared filesystem are not a multi-host coordinator.
4. **Measure one cold study.** Use fresh independent projects and fixed parsed sources. Record source languages/formats/window sizes, actual token usage, per-stage timings, peak collector and server RSS/VRAM, CPU and GPU utilization, queue wait, throughput, and provider/scheduler cost evidence. Track unavailable quantities explicitly. Operator model declarations and provider response metadata are evidence, not automatic attestation of loaded weights.
5. **Exercise one controlled interruption.** With approval for that failure experiment, stop a finite worker at a checkpoint/response boundary, verify that already returned evidence and attempts survive, reopen/import only a verified generation, and compare canonical source/evidence records against an uninterrupted reference. An expired or lost allocation does not prove accepted remote API calls were not billed.
6. **Test bounded contention.** Run two authorized studies through the same supported account coordinator, with different priorities/source lengths and explicit finite budgets. Measure fairness, queue pressure, retries, cancellation/drain time, dashboard pagination, and checkpoint latency. Do not claim account-wide coordination over independent student clients that bypass the registry, or institution-wide GPU fairness.
7. **Close the pilot.** Freeze/re-export the dataset, retain failure/tape/configuration hashes and all unresolved attempts, reconcile invoices/scheduler records where available, and compare observed resource use with the approved caps. Broaden workload or scope only through a new explicit pilot authorization and recorded protocol.

For publication, run separate matched and native extraction comparisons with complete source gold, source-family splits, domain/language breakdowns, and declared cold/warm conditions. Fault-recovery evidence and operational coverage strengthen the method's auditability; they cannot replace semantic annotation or false-negative measurement.
