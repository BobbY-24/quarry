# Failure evidence and remaining boundaries

`verification/` contains fresh local receipts, source hashes and commands.
Earlier V6 reports describe their earlier artifacts. These cases run without
credentials, network inference or scheduler submissions.

| Scenario / baseline evidence | Invariant | Mechanism | Executable verification | Remaining boundary |
|---|---|---|---|---|
| 422 poisons a model lane; reproduced on 7c3ddc7 | I | Scope and execution uncertainty are separate; request-local quarantine | `test_reliability_engine.test_poisoned_request_does_not_disable_healthy_requests_same_model` | Adapter rejection contract required to release unknown billing |
| Grounding error escapes while another response returns; reproduced | A–D | Cache/accounting commit before processing; one bounded finalizer | `test_reliability_engine.test_grounding_failure_retains_cache_and_drains_other_success` | Storage failure may prevent incident/cache persistence |
| Executor rejects after reservation; reproduced | C–E | `not_sent` receipt, zero request count, known unused reserve release | `test_reliability_engine.test_executor_rejection_is_not_dispatched_or_billed` | Durable intent followed by hard death is conservatively uncertain |
| Unknown usage response dies before grounding; real SIGKILL regression | A–D | Replay receipt for grounding; retain usage/time uncertainty | `test_process_recovery` | Returned-but-uncommitted body can be lost |
| Never returning/crashed/oversized process adapter; missing boundary on baseline | C,E | Reviewed process group, guardian, capped pipes, hard deadline | `test_provider_boundary` | Daemonized/escaped groups and arbitrary notebook threads unsupported |
| Node-local checkpoint predates an accepted request | C,D,J | Fsynced durable intent before invocation, terminal metadata, idempotent reconciliation | `test_dispatch_journal`, `test_cluster_journal` | Evidence since last durable checkpoint can be lost with node storage |
| Shared-storage final checkpoint fails | A,J | Retain original private node workspace; explicit recovery receipt | `test_cluster_journal` | Original node must survive; storage outage duration has no guarantee |
| Concurrent projects exceed account quota | E,I | Same-host atomic admission, fair finite queue, aggregate retries/cooldown | `test_quotas`, `test_reliability_artifacts` | All clients must participate; no multi-host enforcement |
| Dead/stale lease or old worker may still execute | C–E | PID/start/boot/namespace fencing; dispatched/unknown capacity never expires into reuse | `test_quotas` | Explicit provider/operator evidence needed to release remote uncertainty |
| Lost controller reply duplicates annotation/start/release | H | Operation ID + parameter hash + durable receipt; atomic short DB effects | `test_operations`, `test_operation_interfaces` | External effects can remain uncertain; workspace creation has separate folder guards |
| Slurm unknown submit/query/requeue/worker replacement | B,C,E,J | Retained allocation reservation, generation identity, cleanup fence, no requeue | `test_cluster`, `test_cluster_journal` | Fake scheduler fixtures; real site signals/accounting unverified |
| Cache storage/full/read-only/receipt publication failure | A–D | Safe local incident where possible, partial state and retained attempt | `test_reliability_engine`, `test_dispatch_journal` | Simulated I/O failures do not prove real storage-controller behavior |
| Planning/inventory/export materialization grows | A,E,G | Indexed planning/membership, streamed occurrence persistence, page views, explicit caps | `test_resilience`, load helpers | Snapshot/export still materialize bounded versions; no immutable chunk store |
| Export interrupted midway; baseline exposes destination | G | Fsynced staged directory and atomic fresh-directory publication | `test_reliability_artifacts`, `test_exports` | POSIX semantics and working fsync assumed; orphan staging may need review after SIGKILL |
| New grounding semantics/real old project | A,G | Separate processing version and hash-bound progress; frozen dataset untouched | `test_release_compatibility`, `test_reliability_artifacts` | Supported schema 1 only; rollback uses pre-upgrade backup |
| Receipt/diagnostics capture private payload or credentials | C,H | Fixed categories, identifiers/hashes, metadata-only receipts, canary checks | `test_operations`, `test_reliability_artifacts`, installed smoke | Evidence store itself is controlled research data |
| Unicode, senses, singleton union, complete-source failure denominator | A,F,G | Exact code-point evidence; reversible annotations; source-level scoring | Existing engine/collection/evaluation/experiment tests | Occurrence does not establish semantic correctness or recall |
| Single cancel arrives between controller start reply and worker entry; reproduced | B,E,H | Clear old cancellation synchronously; worker preserves subsequent cancel | `test_cancel_startup` | Accepted remote work may continue and be billed |
| Repeated context/expression causes eager Cartesian allocation; bounded-consumption regression | A,E | Lazy context/occurrence iteration, hash-bound cursor and processing allowance | `test_grounding_stream` | Dense evidence still consumes finite CPU/disk; saved receipt remains resumable |
| Disabled model blocks already saved raw evidence; reproduced | A,I | Separate bounded cache-replay queue bypasses inference health/quota gates | `test_reliability_engine` | Cache corruption stops replay; no invented evidence |
| Token gate ignores registered counts / multilingual fallback; reproduced | E | Use recorded input token count or conservative UTF-8/template reserve | `test_reliability_engine` | Unusual tokenizer contracts require reviewed counting callback |
| Health write fails after admission but before submission; reproduced | C,E | Settle known unused admission and release reserved capacity | `test_admission_failure` | Failed local receipt write leaves last durable reservation conservative |

The full suite is a regression gate. Counts, model agreement and successful
request completion do not measure research recall. The deterministic fault tape
and canonical evidence projection compare interrupted work with known fixtures;
timestamps, incidents and attempt manifests legitimately differ.

## Known unsupported or unverified deployments

- Live SQLite/WAL or the same-host quota registry on NFS/shared network storage.
- Multiple hosts/PID namespaces claiming one host-local account registry.
- Unbounded in-process custom Python providers; hostile adapters without an OS
  sandbox; process-group escape/daemonization.
- Public multi-user UI/MCP, authenticated human identity or RBAC.
- Exactly-once inference/billing; assumed endpoint idempotency or model attestation.
- Real GT node loss, GPU OOM, network outages, scheduler policy and filesystem
  durability. Use the separately authorized pilot procedure.
- Arbitrary-size datasets; limits stop with retained evidence/receipts. There is
  no automatic deletion of unresolved work to make room.
- Remote CI and Linux runtime results until those jobs actually execute.
