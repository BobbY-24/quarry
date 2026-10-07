# Design rationale

The planning agent drafts a reviewed study. The collector treats extracted
content as inert proposals, validates exact occurrence, and keeps the grounded
union. Local reliability changes preserve that research boundary.

| Design | Reason and primary contract |
|---|---|
| SQLite locally; closed backups durably published | WAL requires same-host shared memory; it is unsuitable for network filesystems. FULL synchronization and explicit backups identify the commit boundary. [SQLite WAL](https://www.sqlite.org/wal.html) |
| Separate process boundary for transport | Thread futures cannot kill arbitrary Python code, and interpreter exit joins outstanding executor threads. A process guardian and finite group cleanup provide the supported deadline. [Python futures](https://docs.python.org/3.12/library/concurrent.futures.html) |
| Fsynced intents and staged artifacts | Atomic rename is a publication boundary; flushing and fsync are separate persistence steps. Shared filesystem guarantees must be site-reviewed. [Python OS interfaces](https://docs.python.org/3/library/os.html#os.fsync) |
| No automatic Slurm requeue | Requeue starts the batch script again; a generation/reconciliation contract is needed before restart can be safe. Site ForceRequeueOnFail can override a request, so the worker also rejects restart generations. [Slurm sbatch](https://slurm.schedmd.com/sbatch.html) |
| Conservative provider accounting | Compatible API syntax does not prove rejected inference, idempotency or cancellation. HTTP status scope and billing uncertainty remain distinct. A reviewed rejection contract is explicit trusted configuration. |
| Opaque shared quota scope | Model aliases and studies can share an account. The coordinator is local admission control, never a credential-derived identity or a multi-host service. |
| Local operation receipts | An atomic SQLite effect can be delivered idempotently; network/filesystem side effects can be uncertain after a crash. An operation receipt does not establish collection completeness. |
| Separate processing cache/version | A response can be re-grounded after a software change without repeating inference. Frozen dataset records remain immutable. |

The code implementing these boundaries is in
[`engine.py`](../src/termfinder/engine.py),
[`process_transport.py`](../src/termfinder/process_transport.py),
[`dispatch_journal.py`](../src/termfinder/dispatch_journal.py),
[`quotas.py`](../src/termfinder/quotas.py),
[`operations.py`](../src/termfinder/operations.py), and
[`exports.py`](../src/termfinder/exports.py).

[Contract](reliability-contract.md) · [Failure matrix](reliability-matrix.md) ·
[Recovery](RECOVERY.md) · [Compatibility](COMPATIBILITY.md) · [CI](CI.md)
