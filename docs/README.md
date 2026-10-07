# Quarry documentation

Start with the [student workflow](guides/student-workflow.md), or ask your own
agent to follow [installation and connection](guides/agent-setup.md).

| Need | Read |
|---|---|
| Configure a study | [Recipes](guides/recipes.md) · [Sources and discovery](guides/sources.md) |
| Choose execution | [Your API/local model](guides/compute.md) · [GT compute](guides/gt-compute.md) |
| Rehearse without credentials | [Offline workflow and notebook](guides/offline-rehearsal.md) |
| Adapt existing research | [NLPx examples](guides/nlpx-students.md) · [Collection protocol](research/collection-protocol.md) |
| Use the engine directly | [CLI/Python reference](reference/cli-python.md) · [Browser-chat fallback](guides/browser-agent-workflow.md) |
| Understand the system | [Architecture](reference/architecture.md) · [Workflow diagrams](reference/diagrams.md) |
| Recover interrupted work | [Runbook](reliability/recovery.md) · [Compatibility](reliability/compatibility.md) · [Long runs](reliability/long-runs.md) |
| Inspect reliability boundaries | [Contract](reliability/contract.md) · [Failure matrix](reliability/failure-matrix.md) · [Process adapters](reliability/process-adapters.md) · [Quotas](reliability/quotas.md) · [Operation receipts](reliability/operations.md) |
| Prepare a research release | [Publication protocol](research/publication-protocol.md) · [Evaluation](research/evaluation.md) · [Experiment plan](research/experiment-plan.md) · [Pilot limits](research/pilot.md) |
| Reproduce or contribute | [Reproduction procedure](development/reproduce.md) · [CI](development/ci.md) · [Visual design](development/design.md) |

The [V6.7 measurement report](reliability/results-v6.7.md) and its
[receipt](reliability/evidence/v6.7-offline.json) identify the earlier **6.7.0**
artifact. They remain prior-release evidence, not rolling verification of this
checkout. Fresh reproduction writes new receipts under ignored `verification/`.

Build outputs, environments, collected datasets, and historical workbench
checkouts do not belong in the source repository. Studies live in a research
workspace selected by the researcher. See [contribution instructions](../CONTRIBUTING.md).
