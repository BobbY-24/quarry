# Controller delivery receipts

The optional `operation_id` gives a controller command a durable identity inside
one project. Use a new opaque UUID for a new action; reuse that UUID only when
redelivering the same command after a lost reply. Do not derive it from a
JSON-RPC request number, which can repeat across sessions.

```python
from uuid import uuid4
from termfinder.operations import OperationManager

manager = OperationManager(project)
operation_id = str(uuid4())
receipt = manager.execute(
    operation_id, "api:annotate",
    {"term_id": term_id, "status": "approved"},
    lambda: project.annotate(term_id, "approved"),
    atomic=True,
)
# Redelivery returns the saved receipt; the annotation is not repeated.
print(manager.receipt(operation_id))
```

The pending receipt commits before the effect. Changed parameters, command kind
or transaction mode with the same ID are rejected. Parameters are hashed rather
than copied into operational records. Results persist only safe control
metadata, such as IDs, counts, status and bounded categories. Source text,
prompts, recipes, bundles, local paths, manifests and unknown free-form strings
remain in controlled research artifacts. A result hash ties the receipt to its
original response. The first successful live response can carry
`transient_result`; it is never stored in the operational table. Redelivery gets
safe routing metadata and an explicit reason to inspect the controlled artifact.
Oversized results are hash-only. Exceptions never copy raw error/provider text.

Use `atomic=True` only for short changes entirely inside the project's SQLite
transaction. Callback changes and terminal receipt commit together; a failure
rolls back those DB effects. Callbacks use existing Project locks; the manager
does not hold a project flock around a nested callback. Independently committing,
writing files, starting background work, inference and scheduler operations are
outside this atomic contract.

Collection, async start acknowledgments, exports, backups, filesystem changes
and scheduler operations use `atomic=False`. They run without holding a SQLite
writer lock. The durable pending identity precedes the effect, but the effect and
its receipt cannot commit atomically across a provider/filesystem/scheduler.
If a worker dies or the outcome is ambiguous, the receipt stays `uncertain` and
redelivery never silently repeats the effect. An async start receipt describes
the start acknowledgment; its collection run has independent progress/failure
state. Operational success is not measured research recall.

Pending owners are identified by an opaque host fingerprint, PID and OS start
identity. A live or uninspectable owner remains pending. A verified dead/reused
PID or a changed host makes the unresolved receipt visibly uncertain. Expiry is
not a reason to repeat an effect. Inspect actual run, dataset, annotation or
scheduler state before explicitly recording a resolution:

```python
# Only after actually checking the named artifact/provider outcome.
manager.resolve(operation_id, evidence="inspected-run-receipt", result={"run_id": run_id})
# Or confirm no effect after inspection; a genuinely new action gets a new ID.
# manager.resolve(operation_id, evidence="operator-check", confirmed_no_effect=True)
```

`OperationRejected` lets a trusted callback declare a known rejection before any
external effect. Other long-callback exceptions remain conservatively uncertain.
Storage failure can prevent terminal diagnostics from committing; the last
committed pending intent remains the restart boundary. There is no exactly-once
execution or billing promise. Receipts are bounded to 10,000 by default and are
never silently pruned; new actions stop at capacity while existing-ID inspection
and redelivery remain available. Archive/review before planning a new project.
