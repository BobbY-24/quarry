"""Small durable metadata receipts bridging node-local checkpoints.

The filesystem must provide atomic same-directory rename, durable fsync and
coherent advisory locks. This is not SQLite on a shared filesystem. Intent is
published before transport dispatch. Missing terminal receipts mean unknown
execution, never absence. Receipts contain hashes/IDs/usage, never prompts,
responses, source text, credentials or provider exception bodies. Unresolved
receipts are never pruned; reaching the finite capacity stops dispatch.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time

from .store import digest, now

VERSION = "quarry-dispatch-journal-v1"
MAX_RECORD_BYTES = 16384
MAX_RECORDS = 100000
ATTEMPT = re.compile(r"attempt_[0-9a-f]{32}")
JOB = re.compile(r"job_[0-9a-f]{24}")
HASH = re.compile(r"[0-9a-f]{64}")
SAFE = re.compile(r"[A-Za-z0-9_.:+-]{1,256}")
TERMINAL = {"settled", "uncertain", "rejected", "not_sent"}


class JournalError(RuntimeError):
    """Sanitized durable-storage failure; provider admission must stop."""


def _fail():
    raise JournalError("Durable dispatch journal unavailable, corrupt, conflicting or full; dispatch stopped") from None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        _fail()
    return value


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        _fail()
    try:
        date = datetime.fromisoformat(value)
    except ValueError:
        _fail()
    if date.tzinfo is None:
        _fail()
    return value


def _cost(attempt):
    required = {"attempt_id", "job_id", "run_id", "stage", "policy_hash", "budget_scope",
        "reserved_usd", "status", "request_count", "created_at", "is_retry", "billing_kind"}
    optional = {"finished_at", "settled_usd", "input_tokens", "output_tokens", "reservation_overrun",
        "latency_seconds", "invoice_usd", "invoice_usd_reason", "failure_reason", "failure_scope",
        "retryable", "outcome_uncertain", "reserved_seconds", "settled_seconds", "time_accounting_version"}
    if not isinstance(attempt, dict) or required - set(attempt):
        _fail()
    value = {key: deepcopy(attempt[key]) for key in required | optional if key in attempt}
    if (not ATTEMPT.fullmatch(str(value["attempt_id"])) or not JOB.fullmatch(str(value["job_id"]))
            or not re.fullmatch(r"run_[0-9a-f]{32}", str(value["run_id"]))
            or not HASH.fullmatch(str(value["policy_hash"]))
            or value["stage"] not in {"extraction", "specialist", "translation", "discovery", "parsing"}
            or not SAFE.fullmatch(str(value["budget_scope"]))
            or value["status"] not in TERMINAL | {"dispatched"}
            or type(value["request_count"]) is not int or value["request_count"] != (0 if value["status"] == "not_sent" else 1)
            or type(value["is_retry"]) is not bool
            or value["billing_kind"] not in {"simulated", "provider_reported_token_estimate"}):
        _fail()
    _timestamp(value["created_at"])
    _number(value["reserved_usd"])
    for key in ("settled_usd", "latency_seconds", "reserved_seconds", "settled_seconds"):
        if key in value:
            _number(value[key])
    for key in ("input_tokens", "output_tokens"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= 1000000000):
            _fail()
    if "finished_at" in value:
        _timestamp(value["finished_at"])
    if "reservation_overrun" in value and type(value["reservation_overrun"]) is not bool:
        _fail()
    if value.get("invoice_usd") is not None:
        _fail()
    if value.get("invoice_usd_reason", "provider_invoice_not_available") != "provider_invoice_not_available":
        _fail()
    if value["status"] in {"rejected", "not_sent"} and value.get("settled_usd") != 0:
        _fail()
    if value["status"] == "settled" and not {"settled_usd", "input_tokens", "output_tokens"} <= set(value):
        _fail()
    if "failure_reason" in value and not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", str(value["failure_reason"])):
        _fail()
    if "failure_scope" in value and value["failure_scope"] not in {"request", "source", "model", "provider", "account", "local", "uncertain"}:
        _fail()
    for key in ("retryable", "outcome_uncertain"):
        if key in value and type(value[key]) is not bool:
            _fail()
    if "time_accounting_version" in value and value["time_accounting_version"] != 2:
        _fail()
    return value


def _descriptor(job):
    try:
        value = {key: deepcopy(job[key]) for key in ("job_id", "source_id", "model_key", "start", "end",
            "depth", "parent", "max_output_tokens")}
        value.update(expert_id=job["expert"]["id"], model_alias=job["expert"]["model"],
            provider_id=job["model"]["provider"], model_sha256=digest(job["model"]))
    except (KeyError, TypeError):
        _fail()
    return _validate_descriptor(value)


def _validate_descriptor(value):
    required = {"job_id", "source_id", "model_key", "start", "end", "depth", "parent", "max_output_tokens",
        "expert_id", "model_alias", "provider_id", "model_sha256"}
    if (not isinstance(value, dict) or set(value) != required
            or not JOB.fullmatch(str(value["job_id"]))
            or not re.fullmatch(r"(?:src|source)_[0-9a-f]{24}", str(value["source_id"]))
            or not re.fullmatch(r"model_[0-9a-f]{24}", str(value["model_key"]))
            or not HASH.fullmatch(str(value["model_sha256"]))):
        _fail()
    for key in ("expert_id", "model_alias", "provider_id"):
        if not SAFE.fullmatch(str(value[key])):
            _fail()
    for key in ("start", "end", "depth", "max_output_tokens"):
        if type(value[key]) is not int or not 0 <= value[key] <= 1000000000:
            _fail()
    if value["end"] <= value["start"] or value["depth"] > 100 or value["max_output_tokens"] < 1:
        _fail()
    if value["parent"] is not None and not JOB.fullmatch(str(value["parent"])):
        _fail()
    return value


class DispatchJournal:
    """One binding's append-only intents and immutable terminal receipts.

    Constructor without submission/generation is reconciliation-only. Capacity
    counts reserved slots, including a crash after slot reservation and before
    intent publication. No automatic deletion can discard an uncertain attempt.
    """
    def __init__(self, root, binding, *, submission_id=None, generation=None,
                 scheduler_job_id=None, max_records=MAX_RECORDS):
        self.root = Path(root).absolute()
        self.binding = deepcopy(binding)
        if (not isinstance(binding, dict) or set(binding) != {"cluster_review_id", "binding_sha256",
                "profile_sha256", "configuration_sha256"}
                or not re.fullmatch(r"cluster_review_[0-9a-f]{24}", str(binding["cluster_review_id"]))
                or any(not HASH.fullmatch(str(binding[k])) for k in binding if k != "cluster_review_id")
                or type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS):
            _fail()
        if bool(submission_id) != bool(generation):
            _fail()
        if submission_id and (not re.fullmatch(r"cluster_job_[0-9a-f]{32}", str(submission_id))
                or not re.fullmatch(r"execution_[0-9a-f]{32}", str(generation))):
            _fail()
        if scheduler_job_id is not None and not re.fullmatch(r"[1-9][0-9]{0,17}", str(scheduler_job_id)):
            _fail()
        self.execution = {"submission_id": submission_id, "generation": generation,
            "scheduler_job_id": scheduler_job_id}
        self.max_records, self._thread_lock = max_records, threading.RLock()
        try:
            if any(path.is_symlink() for path in (self.root, *self.root.parents)):
                _fail()
            if not self.root.exists():
                self.root.mkdir(mode=0o700)
                self._sync_directory(self.root.parent)
            metadata = self.root.stat()
            if not self.root.is_dir() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                _fail()
            with self._lock():
                self._index()
        except (OSError, ValueError):
            _fail()

    @staticmethod
    def _sync_directory(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def _lock(self):
        with self._thread_lock:
            handle = None
            try:
                if self.root.is_symlink() or self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
                    _fail()
                handle = os.open(self.root / ".journal.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                info = os.fstat(handle)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
                    _fail()
                deadline = time.monotonic() + 10
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            _fail()
                        time.sleep(.05)
                yield
            except (OSError, ValueError, TypeError, RecursionError):
                _fail()
            finally:
                if handle is not None:
                    os.close(handle)

    def _read(self, path):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES
                    or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077):
                _fail()
            def pairs(items):
                result = {}
                for key, item in items:
                    if key in result:
                        _fail()
                    result[key] = item
                return result
            def nonfinite(value):
                _fail()
            return json.loads(stream.read(MAX_RECORD_BYTES + 1), object_pairs_hook=pairs, parse_constant=nonfinite)

    def _write(self, path, value):
        raw = (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()
        if len(raw) > MAX_RECORD_BYTES or path.is_symlink():
            _fail()
        handle, temporary = tempfile.mkstemp(prefix=".receipt-", dir=self.root)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory(self.root)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _index(self):
        path = self.root / "index.json"
        if path.exists() or path.is_symlink():
            value = self._read(path)
            if (not isinstance(value, dict) or set(value) != {"version", "binding", "max_records", "reserved_slots"}
                    or value["version"] != VERSION or value["binding"] != self.binding
                    or value["max_records"] != self.max_records or type(value["reserved_slots"]) is not int
                    or not 0 <= value["reserved_slots"] <= self.max_records):
                _fail()
            return value
        # A missing index beside receipts is a storage/integrity failure.
        if any(self.root.glob("attempt_*.json")):
            _fail()
        value = {"version": VERSION, "binding": self.binding, "max_records": self.max_records, "reserved_slots": 0}
        self._write(path, value)
        return value

    def _validate_record(self, value, terminal=False):
        fields = {"version", "binding", "execution", "job", "attempt", "recorded_at", "sha256"}
        if terminal:
            fields.add("intent_sha256")
        if (not isinstance(value, dict) or set(value) != fields or value["version"] != VERSION
                or value["binding"] != self.binding
                or digest({k: v for k, v in value.items() if k != "sha256"}) != value["sha256"]):
            _fail()
        execution = value["execution"]
        if (not isinstance(execution, dict) or set(execution) != {"submission_id", "generation", "scheduler_job_id"}
                or not re.fullmatch(r"cluster_job_[0-9a-f]{32}", str(execution["submission_id"]))
                or not re.fullmatch(r"execution_[0-9a-f]{32}", str(execution["generation"]))
                or execution["scheduler_job_id"] is not None and not re.fullmatch(r"[1-9][0-9]{0,17}", str(execution["scheduler_job_id"]))):
            _fail()
        _timestamp(value["recorded_at"])
        _validate_descriptor(value["job"])
        cost = _cost(value["attempt"])
        if cost != value["attempt"] or cost["job_id"] != value["job"]["job_id"]:
            _fail()
        if cost["status"] not in (TERMINAL if terminal else {"dispatched"}):
            _fail()
        return value

    def intent(self, job, attempt):
        with self._lock():
            if not self.execution["generation"]:
                _fail()
            cost = _cost(attempt)
            if cost["status"] != "dispatched":
                _fail()
            record = {"version": VERSION, "binding": self.binding, "execution": self.execution,
                "job": _descriptor(job), "attempt": cost, "recorded_at": now()}
            if cost["job_id"] != record["job"]["job_id"]:
                _fail()
            path = self.root / (cost["attempt_id"] + ".intent.json")
            if path.exists() or path.is_symlink():
                existing = self._validate_record(self._read(path))
                if any(existing[k] != record[k] for k in ("binding", "execution", "job", "attempt")):
                    _fail()
                return existing["sha256"]
            index = self._index()
            if index["reserved_slots"] >= self.max_records:
                _fail()
            index["reserved_slots"] += 1
            self._write(self.root / "index.json", index)
            record["sha256"] = digest(record)
            self._write(path, record)
            return record["sha256"]

    def terminal(self, job, attempt):
        with self._lock():
            cost = _cost(attempt)
            intent = self._validate_record(self._read(self.root / (cost["attempt_id"] + ".intent.json")))
            if intent["job"] != _descriptor(job) or intent["execution"] != self.execution or cost["status"] not in TERMINAL:
                _fail()
            immutable = set(intent["attempt"]) - {"status", "request_count"}
            if any(cost.get(k) != intent["attempt"][k] for k in immutable):
                _fail()
            path = self.root / (cost["attempt_id"] + ".terminal.json")
            value = {"version": VERSION, "binding": self.binding, "execution": self.execution,
                "job": intent["job"], "attempt": cost, "recorded_at": now(), "intent_sha256": intent["sha256"]}
            if path.exists() or path.is_symlink():
                existing = self._validate_record(self._read(path), terminal=True)
                if any(existing[k] != value[k] for k in ("binding", "execution", "job", "attempt", "intent_sha256")):
                    _fail()
                return existing["sha256"]
            value["sha256"] = digest(value)
            self._write(path, value)
            return value["sha256"]

    def check(self):
        """Bounded read-only integrity gate before reserving another allocation."""
        intents = terminals = 0
        with self._lock(), os.scandir(self.root) as entries:
            index = self._index()
            for entry in entries:
                if entry.name.startswith(".") or entry.name == "index.json":
                    continue
                match = re.fullmatch(r"(attempt_[0-9a-f]{32})\.(intent|terminal)\.json", entry.name)
                if not match or not entry.is_file(follow_symlinks=False):
                    _fail()
                value = self._validate_record(self._read(Path(entry.path)), terminal=match[2] == "terminal")
                if value["attempt"]["attempt_id"] != match[1]:
                    _fail()
                if match[2] == "intent":
                    intents += 1
                else:
                    terminals += 1
                    intent = self._validate_record(self._read(self.root / (match[1] + ".intent.json")))
                    if (value["intent_sha256"] != intent["sha256"] or value["job"] != intent["job"]
                            or value["execution"] != intent["execution"]):
                        _fail()
                if intents > index["reserved_slots"] or terminals > index["reserved_slots"]:
                    _fail()
        return {"intent_records": intents, "terminal_records": terminals}

    def reconcile(self, store, *, restore_job=None):
        """Restore metadata conservatively inside caller's local transaction.

        `restore_job(descriptor)` may reconstruct missing planned/continuation
        jobs from the frozen recipe/source inventory. It must verify the exact
        stable job ID. No raw response is synthesized from usage receipts.
        """
        result = {"records": 0, "unresolved_attempts": 0, "missing_jobs": 0, "restored_costs": 0}
        with self._lock(), store.connection() as db, os.scandir(self.root) as entries:
            index = self._index()
            for entry in entries:
                if entry.name.startswith(".") or entry.name == "index.json":
                    continue
                match = re.fullmatch(r"(attempt_[0-9a-f]{32})\.(intent|terminal)\.json", entry.name)
                if not match or not entry.is_file(follow_symlinks=False):
                    _fail()
                if match[2] == "terminal":
                    if not (self.root / (match[1] + ".intent.json")).is_file():
                        _fail()
                    continue
                intent = self._validate_record(self._read(Path(entry.path)))
                if intent["attempt"]["attempt_id"] != match[1]:
                    _fail()
                result["records"] += 1
                if result["records"] > index["reserved_slots"]:
                    _fail()
                terminal_path = self.root / (match[1] + ".terminal.json")
                terminal = self._validate_record(self._read(terminal_path), terminal=True) if terminal_path.exists() or terminal_path.is_symlink() else None
                if terminal and (terminal["intent_sha256"] != intent["sha256"] or terminal["job"] != intent["job"]
                        or terminal["execution"] != intent["execution"]):
                    _fail()
                cost = deepcopy((terminal or intent)["attempt"])
                existing = store.get("costs", cost["attempt_id"], db)
                if existing:
                    for key in ("job_id", "run_id", "stage", "policy_hash", "budget_scope", "reserved_usd",
                            "reserved_seconds", "time_accounting_version"):
                        if existing.get(key) != cost.get(key):
                            _fail()
                    if existing.get("status") in {"settled", "rejected", "not_sent"}:
                        if terminal and any(existing.get(k) != cost.get(k) for k in ("status", "settled_usd", "input_tokens", "output_tokens")):
                            _fail()
                        cost = existing
                    elif existing.get("status") == "uncertain" and terminal is None:
                        cost = existing
                if cost["status"] == "dispatched":
                    cost.update(status="uncertain", finished_at=now())
                if cost["status"] == "uncertain":
                    result["unresolved_attempts"] += 1
                cost["dispatch_journal"] = {"version": VERSION, "intent_sha256": intent["sha256"],
                    "terminal_sha256": terminal["sha256"] if terminal else None, "execution": intent["execution"],
                    "binding_sha256": self.binding["binding_sha256"]}
                store.put("costs", cost["attempt_id"], cost, db)
                result["restored_costs"] += int(existing is None)
                job = store.get("jobs", cost["job_id"], db)
                if job is None and restore_job:
                    job = restore_job(deepcopy(intent["job"]))
                    if not isinstance(job, dict) or _descriptor(job) != intent["job"]:
                        _fail()
                if job is None:
                    result["missing_jobs"] += 1
                    continue
                cache = store.get("cache", cost["job_id"], db)
                recovered_response = bool(cache and cache.get("attempt_id") == cost["attempt_id"])
                # Do not downgrade a completed later attempt for an earlier
                # uncertain/rejected receipt. Attempt counts are restored below.
                current_cost = store.get("costs", job.get("attempt_id"), db) if job.get("attempt_id") else None
                current_is_later = bool(current_cost and current_cost.get("created_at", "") > cost["created_at"])
                if not current_is_later and cost["status"] not in {"rejected", "not_sent"} and not recovered_response:
                    job.update(status="uncertain", reason="cluster_response_missing_from_durable_checkpoint" if cost["status"] == "settled"
                        else "cluster_dispatch_outcome_unknown_after_checkpoint", coverage_complete=False,
                        attempt_id=cost["attempt_id"], run_id=cost["run_id"])
                    store.put("jobs", cost["job_id"], job, db)
            # Count attempts by stable job, using a bounded SQLite query instead
            # of materializing every receipt/source in memory.
            rows = db.execute("SELECT json_extract(data,'$.job_id'),sum(coalesce(json_extract(data,'$.request_count'),1)) FROM costs GROUP BY json_extract(data,'$.job_id')")
            for job_id, count in rows:
                job = store.get("jobs", job_id, db)
                if job and job.get("attempts", 0) < count:
                    job["attempts"] = count
                    store.put("jobs", job_id, job, db)
            store.setting("cluster_dispatch_reconciliation", dict(result, version=VERSION,
                binding_sha256=self.binding["binding_sha256"], reconciled_at=now(),
                lost_response_note="Metadata restores accounting; source evidence after last checkpoint may require reviewed recollection"), db)
        return result
