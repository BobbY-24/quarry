# Shared account admission

Use one **local** registry file and one operator-chosen opaque scope for every
participating model alias and study using the same account. Scope labels do not
contain keys, key hashes or credential values. Trusted project configuration
selects this registry; recipes, source text and extraction output cannot select
an account or invoke this API.

```python
from pathlib import Path
from termfinder.quotas import QuotaCoordinator, QuotaLimits

registry = Path("operator-state/account-quotas.sqlite").absolute()
gate = QuotaCoordinator(registry, "lab-extraction-account", QuotaLimits(
    max_inflight=4, requests_per_window=30, tokens_per_window=120_000,
    window_seconds=60, retry_requests_per_window=10,
    retry_window_seconds=3600, max_queue=128, max_queue_per_study=16,
))
print(gate.diagnostics())
```

The collector integration acquires before a paid attempt is created, commits
`mark_dispatched` immediately before invoking the provider, then records a known
settlement or an uncertain outcome. Queue and cooldown waits produce no quota
execution event and no paid attempt. Within a study, requests remain FIFO;
eligible study heads alternate when another study waits. Queues have explicit
account and per-study bounds. A permanently blocked retry does not prevent an
eligible request from another study.

Request and total-token reservations use rolling windows. Token estimates must
include the complete input and maximum output reserve. Settlement retains the
larger estimate; a reported overrun raises the reservation. These conservative
dispatch bounds do not meter unrelated clients or reproduce provider invoices.
Retry reservations have a separate shared rolling budget. Account cooldowns
persist and cannot shorten an existing provider minimum. A Retry-After larger
than the finite configured scheduling envelope requires operator resolution.

Conflicting registrations tighten existing limits and set `config_conflict` in
admission and diagnostics. Request/token counts use the smaller limit; windows
use the longer duration. Configuration does not silently widen an active scope.
Widening requires an explicitly reviewed idle registry migration.

Lease expiry alone never releases live or uninspectable workers. Only an expired
**pre-dispatch** lease from a verified dead process can be reclaimed. OS PID,
boot generation and start identity distinguish PID reuse/reboot. A dispatched or uncertain request remains
occupied even after its local process dies: remote inference may continue.
Inspect and resolve it only with a provider/operator receipt establishing that
execution ended:

```python
lease = gate.lease("ql_saved_lease_identifier")
# Run only after actually obtaining the stated execution-ending receipt.
gate.resolve_uncertain(lease, evidence="operator-receipt-reference")
```

Unknown usage remains reserved. The resolution reference is retained in the
registry. Diagnostics report states, queue depth, expired unresolved leases,
cooldown, effective limits and configuration conflict. Unresolved work remains
pending/deferred until capacity is available; a deadline is not permission to
forget a lease. Cancellation removes the caller's queued entries.

Resume also reconciles a lost quota settlement when the project already has a
durable `settled`, `rejected` or `not_sent` attempt. Its lease, study, job and
attempt identities must match; known completion can resolve an uncertain lease
using a reference to that local terminal proof. This makes a temporary registry
failure recoverable without repeating inference. Unknown execution or usage is
never automatically resolved. Each pass has the planning work/time bounds,
records completed reconciliation locally, and blocks inference if more receipt
work remains. Missing pruned terminal history is harmless only alongside the
compatible known local outcome; an identity mismatch stops for inspection.

This coordinates **same-host processes** using local SQLite transactions and
DELETE journal mode (an existing WAL registry is rejected). It
requires an owned regular registry file with mode `0600`, resolved local
directories and a filesystem with reliable locking. NFS/shared live registries,
copied registries and multiple hosts are unsupported. Different Linux PID
namespaces cannot share one registry: a container cannot verify another
container's process death. Host/PID-namespace identity conflicts
are rejected, but hostnames alone cannot attest physical identity or detect all
network mounts. GT jobs on different nodes need a separately deployed operator
gateway implementing atomic global admission, or disjoint account/quota
allocations. The gateway is an integration point, not an implemented service.
Only participating collectors are covered.

Terminal quota receipts are retained up to `max_history`; unresolved leases are
never pruned. Complete request/accounting history and durable controller
idempotency remain in the project journal. Do not reuse historical attempt
tokens or delete/reset a registry to make uncertain work disappear.
