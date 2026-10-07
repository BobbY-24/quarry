# Reliability contract

Quarry separates the researcher's planning agent from bounded extraction.
Operational completion is model-reported window coverage; measured recall
requires independent annotation of complete sources.

## Supported envelope

- macOS/Linux local CLI, API, loopback browser and stdio MCP; one collector
  per project, enforced by a local process lock. The workspace is trusted;
  approval declarations are not authentication or multi-user RBAC.
- Local SQLite with working POSIX locks and durable local storage. Live WAL
  databases are never supported on network storage. Closed checkpoint files
  and immutable dispatch receipts may use an operator-reviewed durable POSIX
  filesystem supporting atomic rename/link, fsync and directory fsync.
- Reviewed single-node Slurm, no automatic requeue; explicit ownership,
  generation and unresolved allocation fences. Declared checkpoint hashes
  identify operator intent, not remote model attestation.
- Built-in HTTP and reviewed process adapters have enforceable transport
  deadlines. Trusted notebook Python providers must return cooperatively;
  arbitrary in-process Python cannot promise bounded process shutdown.
- Shared quota admission is same-host cross-process only. An opaque operator
  scope binds aliases and studies. Multiple hosts sharing an account require
  an external operator gateway or separate account/quota allocations.
- Limits are finite: request/spend/retry caps persist; source cache,
  response/request bodies, planning batches, shutdown and artifact sizes
  have explicit boundaries. Capacity waits create no paid attempts.

## Enforceable invariants

| ID | Contract |
|---|---|
| A | Committed exact evidence survives supported local restart/checkpoint recovery. |
| B | Failed, uncertain or unfinished windows cannot silently become complete. |
| C | Every potentially executed call has a durable attempt or visible accounting uncertainty. |
| D | Retries retain earlier attempts and unknown reservations. |
| E | Admission, retry, time, concurrency, storage and spend limits remain finite. |
| F | Extraction output is inert data; it cannot authorize tools or scope changes. |
| G | Frozen versions export without inference and retain their original records. |
| H | Controller delivery retries with the same operation identity return a receipt. |
| I | Request-local failures leave healthy jobs eligible; broader failures have explicit scope. |
| J | Every recovery claim names its actual persistence boundary. |

## Persistence and recovery boundaries

Local committed SQLite transactions are the boundary for evidence and cache
receipts. Provider responses are committed before grounding. A lost response
before commit remains uncertain; killing transport does not stop remote
generation or guarantee unbilled execution. Storage failure can prevent an
incident from being saved; the last committed attempt remains authoritative.

On Slurm, node-local evidence after the last completed checkpoint can be lost.
A durable dispatch intent written before the call preserves accounting across
that loss. A terminal metadata receipt can restore known usage, not lost
response text or evidence. Missing evidence stays unfinished. Unresolved
receipts are never pruned to meet retention limits.

Shutdown waits a finite allowance for supported process adapters, then records
unresolved attempts. Restart reconciliation is bounded by the configured
inventory/journal limits. Recovery times are measured in the offline rehearsal;
they are not an availability percentage or a guarantee for unavailable storage.

See the operating runbook, compatibility rules and fault matrix for tested
scenarios and deployment assumptions. Real provider billing and GT node loss
require a separately authorized pilot.
