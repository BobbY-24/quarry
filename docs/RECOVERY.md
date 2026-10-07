# Recover a collection without guessing

Start by reading saved progress. A lost browser or agent reply does not mean a
request failed, and a finished controller operation does not mean the corpus is
fully collected. Quarry keeps job outcomes, source coverage, provider attempts
and controller delivery receipts separately.

```sh
quarry --project ./study status
quarry --project ./study doctor
```

`doctor` presents bounded metadata: stopped work, uncertain attempts, retained
cost reservations, local incidents and recovery limits. It does not call a
model, retry a job, erase unknown charges or widen a budget. Continue to inspect
complete held-out sources when assessing recall; operational completion does not
establish research completeness.

## When the agent or browser loses its reply

Give each consequential action an opaque `operation_id`. Reuse that ID and the
same arguments when asking for its outcome. Quarry returns the saved receipt;
it does not run the action again. Reusing an ID with changed arguments is an
error. JSON-RPC request IDs identify transport messages and are separate.

```sh
quarry --project ./study --operation-id collect-batch-001 \
  run-review REVIEW_ID --offline --max-jobs 1
quarry --project ./study operation collect-batch-001
```

For an agent connection, include `operation_id` in a selected-study mutation such
as `collect`, `annotate`, `approve_review`, `release` or `submit_cluster`. Read
`operation_status` with that ID after reconnecting. An asynchronous `collect`
receipt describes starting collection; poll `status` for its eventual run result.
The browser creates these IDs automatically and retains only a payload hash and
the ID in its session storage while a reply is unresolved. It retains the same
ID after a transport timeout, rather than silently creating a new operation.

| Receipt | Researcher procedure |
|---|---|
| `succeeded` | Inspect the returned IDs and saved run, annotation or version. Do not repeat the effect. |
| `pending` | The original process may still be working. Read progress and wait for its bounded execution. |
| `uncertain` | Inspect actual project effects, scheduler history or provider accounting before declaring an outcome. |
| `failed` | Read the safe failure category and whether a short transaction rolled back. A corrected action needs a new explicit ID. |

Durable operation receipts store parameter/result hashes and bounded control
metadata. They do not retain another copy of prompts, research text, bundles,
notes or filesystem paths. A successful first reply can include a
`transient_result`; it is not saved in the operation ledger. Replays return
metadata and a reason if content was omitted. Recover the content through
controlled project views: `study_setup_text` for the saved agent prompt and
starter bundle, `inspect_plan`/`review_text` for the concrete review,
`inspect_record` for evidence, and saved version exports for a dataset. These
tools remain bound to the selected study and its hashes.

Controller receipts are local to a project. Workspace creation/opening retains
the existing safe-folder rules; receipt IDs described here apply to mutations in
a selected study. The default operation inventory stops at 10,000 receipts.
There is no automatic pruning of unresolved receipts.

## Resume extraction and preserve earlier charges

```sh
quarry --project ./study resume --offline
quarry --project ./study resolve-uncertain JOB_ID --retry \
  --acknowledge-possible-duplicate-billing
```

Use the second command only after deciding that another request is warranted.
An uncertain earlier attempt remains in the ledger, with its cost and request-time
reservation. A retry creates a distinct attempt. Provider-compatible endpoints
do not necessarily support idempotent billing, so Quarry does not promise
exactly-once inference or exactly-once charges.

A committed raw response is cached before candidate grounding. If later local
processing fails, resume replays that response without inference. A known
response lacking usage can retain grounded evidence while its billing remains
uncertain. Rate limiting, provider/model failures, source-specific failures and
local processing failures remain distinguishable in safe diagnostics.

For multiple studies sharing one provider account on the **same host**, an
operator can configure one private local registry and the same opaque scope:

```sh
quarry --project ./study-a configure-quota \
  --registry ./local-control/provider-quota.sqlite3 --scope-id lab-account-a
quarry --project ./study-b configure-quota \
  --registry ./local-control/provider-quota.sqlite3 --scope-id lab-account-a
```

Optional `--limits quota-limits.json` supplies finite concurrency, request/token
windows, retry windows and queue limits. An account label is not an API key or a
key hash. Every participating study must use the same registry and scope; copied
registries do not coordinate. Conflicting configurations can tighten admission
and remain visible. Never put this registry on NFS/shared storage. Multi-host
account admission requires an approved gateway or another reviewed coordinator.

## GT worker durability

The control project and active worker SQLite databases use supported local
storage. The worker creates consistent, closed SQLite backups on approved durable
storage. A published checkpoint becomes authoritative only after the backup file
and its directory are fsynced and its atomic JSON receipt is published.

The worker also writes a small, private dispatch journal on durable storage.
Its intent is fsynced **before** starting a provider call. Each record binds a
stable logical job, a distinct attempt, the submission/execution generation,
known scheduler ID, frozen configuration/profile/review hashes, model identity,
stage, monetary reservation and cumulative request-time reservation. Terminal
receipts record known usage or explicit uncertainty. The journal has no source
text, prompt, raw response, secret, provider exception body or live SQLite WAL.

| Failure boundary | Recovery meaning |
|---|---|
| Local reservation succeeds; intent publication fails | Transport is not started. The local attempt is `not_sent`; known unused reservation is released. |
| Intent exists; process dies before or during dispatch | Treat it as potentially executed. Retain the attempt and reservations as unknown. |
| Provider accepts; node dies | The journal preserves accounting identity. A stale checkpoint cannot prove which response or evidence was returned. |
| Response arrives; node dies before checkpoint | A terminal receipt can restore known usage. It cannot reconstruct raw responses or source evidence lost with node-local storage. The job stays explicitly unresolved. |
| Local response/accounting commit succeeds; terminal publication fails | Stop new admission. If local storage survives, retain and replay the committed response; otherwise preserve the durable intent as uncertainty. |
| Checkpoint publication or pruning is interrupted | Use the last verified published checkpoint. Unpublished files may remain for operator inspection. |
| Journal/checkpoint disagree, or journal is corrupt/unavailable | Stop and investigate. Do not replace missing accounting with a fresh budget. |

Reconciliation on worker resume and checkpoint import is transactional and
idempotent. Missing costs are restored, duplicate attempt identities cannot be
counted twice, and terminal metadata does not invent a cached response. Records
with known usage but no durable response are explicitly marked
`cluster_response_missing_from_durable_checkpoint`.

**Evidence durability has a concrete boundary:** ordinary process recovery can
use committed local SQLite state while its storage survives. Recovery after
complete node/scratch loss can use evidence in the last published checkpoint.
The dispatch journal restores accounting after that boundary, not missing
evidence. If a final/recovery checkpoint fails, the worker preserves its private
node-local workspace and records `node_local_recovery`; it remains recoverable
only while that original node storage survives. Do not discard it before an
operator has verified a replacement checkpoint or accepted the explicit loss.

The journal stops admission when its bound is reached: the smaller of the frozen
request cap and 100,000 intent slots, with at most one 16 KiB intent and one
16 KiB terminal per slot. Capacity reservations interrupted before intent
publication remain conservative holes. There is no receipt deletion to make
room. Filesystem failure/hard crashes can leave unpublished temporary files;
review those separately without deleting unresolved published receipts.

The storage contract requires private owned directories, coherent advisory
locks, atomic same-directory replacement and working file/directory `fsync`.
Permissions and hashes do not prove these properties for a particular shared
filesystem. Validate them with the site operator before a live GT pilot.

## Export after recovery

Release the same saved version to reproduce its records without inference:

```sh
quarry --project ./study release pilot-v1
quarry --project ./study release pilot-v1
```

If a release operation reply was lost, reuse its operation ID or inspect the
saved version before creating a new release. Retain unfinished sources,
failures, reservations and runtime/source-use limitations in the manifest. New
collection runs can change attempts and timestamps; frozen version exports
reproduce the stored dataset.
