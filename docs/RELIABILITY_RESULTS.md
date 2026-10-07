# Hardened V6.7: verified scope and operating limits

This local release hardens the V6.6 foundation without changing the research
contract: grounded union, distinct senses, exact original evidence, researcher
recipes, reversible annotations and frozen exports. V7.1 carries the foundation
into an isolated research-framework checkout. No existing datasets or primary
version directories were replaced.

## Evidence and fixes

The fresh baseline was commit `7c3ddc7`, package 6.6.0: 382 tests passed inside OS
isolation before changes. Baseline regressions then reproduced request-lane
poisoning, escaped grounding finalization, stranded submission reservations and
partial export publication. Hardening also exposed and reproduced startup
cancellation, eager repeated-match allocation, blocked cache replay, stale
unknown-usage completion, incorrect quota token estimates and lost quota receipts.
The [failure matrix](reliability-matrix.md) maps scenarios to invariants/tests and
remaining boundaries; red receipts are retained locally under `verification/`.

The implementation now provides typed failure scope separate from outcome
uncertainty, an exception-safe finite finalizer, raw receipts before grounding,
reviewed process deadlines/cleanup, durable Slurm dispatch intents, same-host
account admission/retry coordination, durable controller operation IDs and
pre-engine failure records, bounded indexed planning/lazy grounding, and atomic
frozen exports. Cache replay recovers evidence without re-opening provider lanes
or resolving unknown billing. Known terminal quota proof can close a lost
secondary settlement; unknown execution remains reserved.

## Fresh release gates

Final core commits: `cb873295a3c35f556d0d5759792bffad304d8b21` and
`97ec38e7d454bbe56f073e5076b11d842fb897b2`.

| Check | Fresh outcome |
|---|---|
| Complete source suite | 521 tests passed |
| Complete suite against installed wheel, without source imports | 521 tests passed |
| Installed CLI/API/stdio MCP/EOF/assets/credential canary | Passed |
| Real SIGKILL recovery and process cleanup | Passed bounded tests |
| Independent actual V6.6 project fixture | Zero repeat calls; original frozen JSONL hashes preserved |
| Three recipes × Broad/Specialists | Six complete offline demonstrations; exact evidence, reversible review, failures/budgets and all exports |
| Agent workflow: term/idea/opinion/sentence × both modes | Eight scripted demonstrations; no external agent/model; reversible review and frozen export |
| Frozen CSV/JSONL/Parquet/annotation re-export | Byte-identical within each saved version |
| macOS isolation and source drift gates | Network denied, unrelated reads denied, empty credentials; no source drift |

Release wheel at `.ci/release-dist/nlpx_termfinder-6.7.0-py3-none-any.whl`
(the older `.ci/dist` artifact is retained and superseded):

```text
nlpx_termfinder-6.7.0-py3-none-any.whl
SHA256 06b2bdf5ea81acbef98d8d9ca13ab44c7546dc3f927e6090dc5ef2d7e332b99e
```

The committed [machine-readable receipt](reliability-evidence/v6.7-offline.json)
contains relative source hashes, wheel/dependency hashes and hashes of the exact
local invocation receipts. Full local receipts in `verification/final/` contain
commands, exit status, platform, limits and before/after hashes. Historical and
superseded runs are retained with their original failures/status. The source
and installed release receipts are `release-suite-source.json` and
`release-suite-installed.json`; the wheel verification is `release-smoke.json`.

## Measured workload

Measured on macOS 26.7 ARM64/Python 3.12.14 with patched SQLite 3.53.1 and pinned
pyarrow 25.0.1. These are engineering rehearsals on a shared development machine;
other bounded verification tasks ran concurrently. They are not isolated
performance benchmarks or real inference/GPU throughput measurements.

| Final installed workload | 1,000 short synthetic sources |
|---|---|
| Fixture requests / exact observed spans | 2,000 / 1,000 |
| Completed resume extra calls | 0 |
| Wall elapsed | 15.36 s |
| Collector peak RSS | 274,464,768 bytes (261.75 MiB) |
| User/system CPU | 7.51 s / 4.24 s |
| Descriptors before/after; sampled peak | 4 / 4; 9 |
| Measured project + two export copies | 205,370,880 bytes (195.86 MiB) |
| Interruption, reopen, resume and cache checks | Passed |
| Frozen all-format export identity | Passed |

The final run's exact canonical evidence hash is
`5638fc1267522ecc4d17d82e9fa22edb9b282be1e42d80256ab5f1b0ee73e39a`.
Every observed span was compared against original Unicode text and the source
hash. FD peaks are sampled every 20 ms; disk sizes are measured at phase boundaries.
RSS covers this collector/Python/Arrow process, not a model server. CPU, cache
assumptions and workload differences prevent transferring these timings to real
multilingual PDF extraction.

An intermediate 1,000-source run took 45.49 s and revealed a full cache sweep on
every dispatch. The regression observed 14 sweeps for 6 calls. The final scheduler
sweeps saved receipts once per recovery, with bounded batches, and does not
rescan steady new responses. The count regression and fresh load verify that
fix; timing differences are not a controlled speedup experiment.

The final installed mixed rehearsal processed 120 shared sources in two studies:
24 HTML, 24 Markdown, 48 text (including 24 long documents), and 24 two-page
PDFs. Languages were English, Arabic and Chinese; document lengths reached
20,883 characters. Broad and Specialists used the same frozen corpus.

| Mixed-source check | Final installed result |
|---|---|
| Wall elapsed | 123.53 s |
| Attempts | 1,985 settled, 4 rejected, 1 uncertain; 1,990 total |
| Shared-account simultaneous calls | Maximum 2 |
| Exact spans/source hashes; healthy-counterfactual identity | 144 checks; matched in both faulted studies |
| Final state | Broad complete; Specialists visibly degraded; unknown reservation/lease retained |
| Repeating final collection | 0 additional calls |
| Re-exporting both saved versions | All four formats byte-identical |
| Collector peak RSS; user/system CPU | 369,115,136 bytes (352.02 MiB); 20.91 / 16.23 s |
| Descriptors before/after; sampled peak | 4 / 4; 17 |
| Projects/counterfactual/checkpoint/export disk | 181,517,214 bytes (173.11 MiB) |
| Cancel to drained return; local consistent backup | 0.136 s / 0.023 s |
| Direct paginated inspection | 594 samples; 0 errors; 24.3 ms p95; maximum payload 10,687 bytes |

The first-capacity-wait-to-dispatch interval was 0.479 s p95, with a 20.76 s
maximum; it includes cancellation/resume pauses and is not pure queue residency.
Fixture request p95 was 10.05 ms. Two retry gaps were 31.5–717.2 ms. These
small deterministic fake delays do not model real service/network latency.
Inspection called the browser data API directly rather than measuring HTTP or
browser rendering. The consistent local backup is not a real GT shared-storage
checkpoint experiment.

The mixed canonical evidence hash is
`84e039255e3c54aacb35a3618e19137dac3e38c2825497093ef5f2d006501b5f`.
Final receipts are `mixed-120.json` and `mixed-120-isolation.json`; both report
zero paid calls, correct isolation and no source drift. Earlier failed,
time-limited and superseded rehearsals remain separately identifiable. All
monetary rates in this stress test were synthetic; actual API and GT costs are
unavailable and unmeasured.

## Capacity and persistence boundaries

The measured release workload is 1,000 short sources. The separate mixed stress
uses two studies, long text, HTML/Markdown, Arabic/CJK and PDFs. Neither tests
maximum theoretical capacities. Start larger live work with an authorized small
canary and measure actual document/window distributions before expanding.

Enforced safety caps include 100,000 planned roots per invocation, bounded
concurrency and per-attempt transport limits, a 5-second transient account-capacity
wait, 30-second response drain plus finite process cleanup, 8 MB response bodies,
4-source/16-million-character source cache, 100,000 audit rows, 10,000 incident and
controller-operation records, 2 GiB active store/WAL stop, 64 MiB materialized
inventory and 128 MiB serialized snapshots. Snapshot/export remains materialized
within these limits; it is not an immutable chunk store or a peak-RSS guarantee.
Planning caps require partitioning the study; repeatedly resuming does not
advance a hidden unlimited plan cursor. Disk headroom checks cannot reserve
space against other writers.

Invariants A–J are exercised by the mapped tests within the
[contract](reliability-contract.md). They are not a formal proof or an
availability percentage. Supported local recovery uses committed SQLite state.
Complete node loss recovers evidence only from the last verified checkpoint;
the durable journal restores later accounting identities, not lost text.
Unknown remote outcomes can remain charged/reserved even after local transport
termination. Arbitrary in-process notebook threads cannot promise bounded
interpreter exit; production deadlines require reviewed process adapters.

## Remaining release and publication steps

Linux/Python-matrix/GitHub CI, real provider invoices/network behavior, real GT
Slurm signals/node loss/OOM/throughput, shared-filesystem durability and actual
student harness usability have not been validated here. Same-host quotas do not
cover outside clients or multiple nodes; those require a reviewed external
account gateway or disjoint operator allocations. Public multi-user hosting,
remote model attestation and exactly-once billing remain unsupported.

The prepared [GT pilot procedure](STRESS_TESTS.md#georgia-tech-stress-pilot-plan-only)
requires explicit authorization and operator-confirmed resources before any live
allocation or collection. The pinned CI workflow is checked in but has not run
remotely. A patched SQLite runtime is required; the gate must not be disabled.
No paid collection, real GT jobs, publication, contacts or pushes occurred.
There was no remaining local approval/environment blocker.

These tests do not establish extraction precision/recall or support H1–H4
publication claims. V7 retains complete-source gold separation, semantic review,
matched/native baseline adapters, keyed recovery experiments and student/compute
measurement scaffolds. Qualified humans must annotate full independent sources,
freeze hypotheses/contrasts and then conduct authorized real experiments.
Candidate counts and agreement remain separate from recall.

[Installation and notebook rehearsal](RELIABILITY_REHEARSAL.md) ·
[Recovery/runbook](RECOVERY.md) · [Compatibility/rollback](COMPATIBILITY.md) ·
[Source-linked design](RELIABILITY_DESIGN.md) · [CI](CI.md)
