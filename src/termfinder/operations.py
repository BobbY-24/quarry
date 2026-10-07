"""Durable receipts for explicit controller operation identities.

Same-ID delivery retries return a receipt and never repeat a consequential
callback. This is project-local idempotency, not exactly-once external execution.
"""
from __future__ import annotations

from copy import deepcopy
import os
import re
import socket
import sqlite3

from .agent_setup import _credential_free
from .config import canonical
from .quotas import process_start_identity, process_state
from .store import digest, now


MAX_PARAMETER_BYTES = 32_000_000
MAX_RESULT_BYTES = 262_144
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}\Z")
FAILURE_CATEGORIES = {"validation_failure", "permission_failure", "storage_failure",
                      "local_execution_failure", "cancelled", "result_validation_failure",
                      "controller_interrupted", "confirmed_no_effect", "external_outcome_unknown"}
CONTENT_KEYS = {"text", "prompt", "recipe", "profile", "starter_bundle", "bundle", "context", "locator",
                "path", "out", "workspace", "source", "source_inventory", "manifest", "attributes", "note",
                "sources", "brief", "description", "local_roots", "source_plan", "source_provenance",
                "research_question", "annotation", "content", "meaning", "definition", "translation"}
_DROP = object()


def _metadata_result(value, key=None):
    """Project control metadata; unknown free-form strings remain in artifacts."""
    if isinstance(value, dict):
        projected, omitted = {}, False
        for field, item in value.items():
            if (field.lower() in CONTENT_KEYS or field.lower().endswith(("_path", "_paths", "_root", "_roots"))
                    or not LABEL.fullmatch(field)):
                omitted = True
                continue
            selected, dropped = _metadata_result(item, field)
            omitted |= dropped
            if selected is not _DROP:
                projected[field] = selected
        return (projected if projected or not value else _DROP), omitted
    if isinstance(value, list):
        projected, omitted = [], False
        for item in value:
            selected, dropped = _metadata_result(item, key)
            omitted |= dropped
            if selected is not _DROP:
                projected.append(selected)
        return (projected if projected or not value else _DROP), omitted
    if isinstance(value, str):
        allowed_key = key is not None and (key.endswith(("_id", "_ids", "_sha256", "_hash", "_alias")) or
            key in {"id", "status", "reason", "category", "stop_reason", "mode", "data_type"})
        allowed_top_id = key is None and value.startswith(("annotation_", "version_", "dataset_", "ds_", "run_", "review_"))
        if (allowed_key or allowed_top_id) and LABEL.fullmatch(value):
            return value, False
        return _DROP, True
    if value is None or type(value) in (bool, int, float):
        return value, False
    return _DROP, True


class OperationRejected(Exception):
    """A trusted callback establishes rejection before any external effect."""
    def __init__(self, category="validation_failure"):
        if category not in FAILURE_CATEGORIES:
            raise ValueError("invalid operation rejection category")
        self.category = category
        super().__init__(category)


def _label(value):
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise ValueError("operation identity/kind must be a bounded opaque label")
    _credential_free(value)
    return value


def _failure(error):
    if isinstance(error, OperationRejected): return error.category
    if isinstance(error, (KeyboardInterrupt, SystemExit)): return "controller_interrupted"
    if isinstance(error, sqlite3.Error): return "storage_failure"
    if isinstance(error, PermissionError): return "permission_failure"
    if isinstance(error, (TypeError, ValueError)): return "validation_failure"
    return "local_execution_failure"


class OperationManager:
    """Bounded, project-local durable control delivery.

    `atomic=True` is reserved for short effects entirely inside this project's
    SQLite transaction. Callbacks must not commit independently, write files,
    start threads, submit jobs, fetch, or invoke inference in that mode. Long or
    filesystem/external effects use `atomic=False`, with pending intent committed
    before callback execution and no writer lock held while it runs.
    """
    def __init__(self, project, *, max_operations=10_000, process_probe=None, host_id=None):
        if type(max_operations) is not int or not 1 <= max_operations <= 100_000:
            raise ValueError("operation receipt inventory must have a finite bound")
        self.project, self.store = project, project.store
        self.max_operations = max_operations
        self.process_probe = process_probe or process_state
        self.host_id = host_id or "host_" + digest(socket.gethostname())[:24]
        self.pid, self.start_identity = os.getpid(), process_start_identity(os.getpid())

    def _top_level(self):
        # A caller's outer transaction would delay the dispatch-intent commit.
        if self.store._depth.get() != 0:
            raise ValueError("controller operations require a top-level store boundary")

    def _reconcile(self, receipt, db):
        if receipt["status"] != "pending":
            return receipt
        owner = receipt["owner"]
        if owner["host_id"] != self.host_id:
            reason = "original_owner_host_unavailable"
        elif self.process_probe(owner["pid"], owner["start_identity"]) == "dead":
            reason = "original_owner_process_ended"
        else:
            return receipt
        receipt = dict(receipt, status="uncertain", reason=reason, updated_at=now(), result=None,
                       result_reason="operation_effect_requires_reconciliation")
        self.store.put("operations", receipt["operation_id"], receipt, db)
        return receipt

    def receipt(self, operation_id):
        """Inspect/reconcile one bounded receipt; never rerun its callback."""
        operation_id = _label(operation_id)
        self._top_level()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = self.store.get("operations", operation_id, db)
            return deepcopy(self._reconcile(receipt, db)) if receipt else None

    def execute(self, operation_id, kind, params, callback, *, atomic=False):
        """Return a receipt, including safe failure/uncertainty information.

        Parameters are validated and hashed, never copied into the receipt.
        No identifier is implicitly derived from a JSON-RPC request/session ID.
        A known failed receipt also remains terminal; a new explicit operation
        identity is needed for a genuinely new action after reviewing the failure.
        """
        operation_id, kind = _label(operation_id), _label(kind)
        if not isinstance(params, dict) or not callable(callback) or type(atomic) is not bool:
            raise ValueError("invalid trusted operation registration")
        _credential_free(params)
        raw_params = canonical(params)
        if len(raw_params.encode()) > MAX_PARAMETER_BYTES:
            raise ValueError("operation parameters exceed finite bounds")
        parameter_sha256 = digest(raw_params)
        self._top_level()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self.store.get("operations", operation_id, db)
            if existing:
                if (existing["kind"], existing["parameter_sha256"], existing["atomic"]) != (kind, parameter_sha256, atomic):
                    raise ValueError("operation identity was already bound to different parameters or effects")
                return deepcopy(self._reconcile(existing, db))
            if self.store.count("operations", db=db) >= self.max_operations:
                raise ValueError("operation receipt capacity reached; archive/review the project before new actions")
            created = now()
            receipt = {"schema_version": 1, "operation_id": operation_id, "kind": kind,
                       "parameter_sha256": parameter_sha256, "atomic": atomic, "status": "pending",
                       "created_at": created, "updated_at": created, "reason": None,
                       "owner": {"host_id": self.host_id, "pid": self.pid, "start_identity": self.start_identity},
                       "result": None, "result_sha256": None, "result_reason": "operation_in_progress",
                       "effect_rolled_back": None, "resolution_reference": None}
            self.store.put("operations", operation_id, receipt, db)
        # The preceding transaction is fully committed before any effect.
        try:
            if atomic:
                with self.store.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    result = callback()
                    receipt = self._completed(receipt, result)
                    self.store.put("operations", operation_id, receipt, db)
            else:
                result = callback()
                receipt = self.complete(operation_id, result)
            response = deepcopy(receipt)
            if (receipt["status"] == "succeeded" and receipt["result_reason"] ==
                    "content_result_not_captured_inspect_controlled_project_artifact"):
                # The first response may deliver the authorized live content;
                # the durable operation row never contains this transient field.
                response["transient_result"] = deepcopy(result)
            return response
        except BaseException as error:
            # Atomic DB effects rolled back together with their terminal receipt.
            # An external callback can have applied an effect before raising.
            uncertain = not atomic and not isinstance(error, OperationRejected)
            try:
                receipt = self.fail(operation_id, _failure(error), uncertain=uncertain,
                                    effect_rolled_back=atomic)
            except BaseException:
                # Storage may be unavailable; committed pending intent remains
                # the restart boundary and the original exception must surface.
                raise error from None
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            return receipt

    def _owned_pending(self, operation_id, db):
        receipt = self.store.get("operations", _label(operation_id), db)
        if receipt is None:
            raise ValueError("operation receipt is unavailable")
        if receipt["status"] != "pending":
            return receipt
        owner = receipt["owner"]
        if (owner["host_id"], owner["pid"], owner["start_identity"]) != (self.host_id, self.pid, self.start_identity):
            raise ValueError("only the original operation owner can settle a pending effect")
        return receipt

    @staticmethod
    def _completed(receipt, result):
        _credential_free(result)
        serialized = canonical(result)
        result_sha256 = digest(serialized)
        oversized = len(serialized.encode()) > MAX_RESULT_BYTES
        projected, omitted = _metadata_result(result)
        projected = None if projected is _DROP else projected
        return dict(receipt, status="succeeded", reason=None, updated_at=now(),
                    result=None if oversized else projected, result_sha256=result_sha256,
                    result_reason=("result_exceeds_receipt_limit_inspect_outputs" if oversized else
                        "content_result_not_captured_inspect_controlled_project_artifact" if omitted else None),
                    effect_rolled_back=False)

    def complete(self, operation_id, result):
        """Complete a pending same-process effect (including reviewed async work)."""
        self._top_level()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = self._owned_pending(operation_id, db)
            completed = self._completed(receipt, result)
            if receipt["status"] != "pending":
                if receipt["status"] == "succeeded" and receipt["result_sha256"] == completed["result_sha256"]:
                    return deepcopy(receipt)
                raise ValueError("operation terminal/uncertain receipt cannot be replaced")
            self.store.put("operations", operation_id, completed, db)
            return deepcopy(completed)

    def fail(self, operation_id, category, *, uncertain=True, effect_rolled_back=None):
        """Persist a bounded category; exception messages/payloads are excluded."""
        if category not in FAILURE_CATEGORIES or type(uncertain) is not bool or effect_rolled_back not in (None, True, False):
            raise ValueError("invalid operation failure declaration")
        self._top_level()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = self._owned_pending(operation_id, db)
            if receipt["status"] != "pending":
                return deepcopy(receipt)
            failed = dict(receipt, status="uncertain" if uncertain else "failed", reason=category,
                          updated_at=now(), result=None, result_sha256=None,
                          result_reason="operation_effect_requires_reconciliation" if uncertain else "operation_failed",
                          effect_rolled_back=effect_rolled_back)
            self.store.put("operations", operation_id, failed, db)
            return deepcopy(failed)

    def resolve(self, operation_id, *, evidence, result=None, confirmed_no_effect=False):
        """Record an explicit inspected outcome; this method never repeats it.

        Use a receipt reference after checking actual effects. Local trust/real
        researcher authorization remains the interface's responsibility.
        """
        evidence = _label(evidence)
        if type(confirmed_no_effect) is not bool:
            raise ValueError("invalid operation resolution declaration")
        self._top_level()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = self.store.get("operations", _label(operation_id), db)
            if not receipt or receipt["status"] not in {"pending", "uncertain"}:
                raise ValueError("only a pending or uncertain operation can be explicitly resolved")
            if confirmed_no_effect:
                if result is not None:
                    raise ValueError("no-effect resolution cannot have a completed result")
                resolved = dict(receipt, status="failed", reason="confirmed_no_effect", updated_at=now(),
                                result=None, result_reason="operator_confirmed_no_effect", effect_rolled_back=None)
            else:
                resolved = self._completed(receipt, result)
            resolved["resolution_reference"] = evidence
            self.store.put("operations", operation_id, resolved, db)
            return deepcopy(resolved)
