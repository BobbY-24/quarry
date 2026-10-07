# Upgrade, cache and rollback

V6.7 keeps recipe/database schema 1 and export schema 1.1. The new incident and
operation tables are additive; existing evidence and frozen JSON are not
rewritten. Unsupported database schemas and unpatched SQLite stop before model
admission. The runtime must use SQLite >=3.51.3, or the documented fixed
backports 3.44.6/3.50.7. Use a current supported Python 3.11–3.13 build.

## Independent version boundaries

| Boundary | Binding / upgrade behavior |
|---|---|
| Provider response | Source/parser, policy/prompt, model/provider/runtime and transport identities remain the immutable response-cache key. |
| Grounding/normalization | `grounding-2` is recorded separately. A changed processing version replays a committed response instead of making a new request. |
| Processing progress | Candidate and occurrence cursors bind response hash and processing version. A changed response cannot reuse an earlier cursor. |
| Execution/recovery | `recovery-2` preserves earlier attempts; known unused dispatches are `not_sent`. Unknown attempts retain reservations. |
| Request-time budget | New attempts reserve bounded transport seconds before dispatch, settle measured latency where known, and retain unknown time across resume. Pre-upgrade attempts have no historical request-time measurement; it is not fabricated. |
| Dataset serialization | Saved version hash and original records remain authoritative; exports perform no inference. Parquet bytes depend on pinned pyarrow. |
| Reviewed adapter code | Process adapters need a pinned `adapter_version` for cross-instance cache reuse. Unversioned prototypes get instance-local cache identities. |
| Reviewed cluster bundle | Package/configuration/runtime fingerprints are checked. A changed package needs a fresh reviewed bundle; integrity checks are not bypassed. |

## Before upgrading

1. Stop collection and inspect unresolved provider/allocation outcomes.
2. Create a closed consistent backup using `project.store.backup(new_path)`;
   do not copy a live SQLite file without its transaction boundary.
3. Save the installed wheel/runtime and backup hashes. Keep existing frozen
   exports and response receipts.
4. Install the new wheel in a fresh environment. Run `quarry doctor`, then
   rehearse on a copy before changing the original.

Opening a schema-1 project creates only additive tables/indexes. There is no
destructive data migration in this release. Future schema changes must use a
backed-up transactional migration, rather than opportunistic rewriting.

The checked-in `tests/fixtures/legacy-6.6` database was built by the actual
7c3ddc7 / V6.6 implementation using synthetic text. Its receipt records the
database and old JSONL export hashes. Compatibility tests open that database,
reprocess cached responses with zero new calls, and compare the old frozen
export hashes. It is not a fixture constructed by the new engine.

## Rollback and cluster recovery

Rollback means restoring the **pre-upgrade backup** in a separate directory and
its old reviewed runtime. Do not run an older collector against a newly
configured quota registry, operation ledger or execution contract: it cannot
enforce rules it does not implement. New frozen exports remain usable as saved
artifacts; restoring an old backup does not recover later evidence.

A restored cluster checkpoint is imported only into its unchanged origin and
matching reviewed runtime/configuration. Journal reconciliation restores missing
accounting and explicitly unresolved jobs. Metadata cannot reconstruct response
text lost with node scratch. Current uncertain-job human resolutions change the
origin fingerprint, so they cannot silently modify an older frozen worker
bundle. Create a newly reviewed recovery study/checkpoint after preserving and
reconciling the earlier allocation; automatic uncertainty-resolution staging is
outside this release.

See [recovery](recovery.md) for operator procedures and
[SQLite's WAL documentation](https://www.sqlite.org/wal.html) for the runtime
patch and local-filesystem requirements.
