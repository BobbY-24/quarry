"""Same-host, cross-process admission for an operator-selected account scope.

This is a local dispatch gate, not a provider billing or multi-host service.
Every participating collector must use the same local registry and opaque scope.
Unknown remotely accepted work retains its lease until explicitly resolved.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import ctypes
import errno
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import stat
import sys
import time
import uuid


@dataclass(frozen=True)
class QuotaLimits:
    max_inflight: int = 4
    requests_per_window: int = 60
    tokens_per_window: int = 120_000
    window_seconds: float = 60.0
    retry_requests_per_window: int = 20
    retry_window_seconds: float = 3600.0
    max_queue: int = 128
    max_queue_per_study: int = 16
    lease_seconds: float = 300.0
    max_cooldown_seconds: float = 86400.0
    max_history: int = 2048

    def __post_init__(self):
        for name in ("max_inflight", "requests_per_window", "tokens_per_window", "max_queue",
                     "max_queue_per_study", "max_history"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise ValueError(f"invalid quota limit: {name}")
        if type(self.retry_requests_per_window) is not int or not 0 <= self.retry_requests_per_window <= 1_000_000:
            raise ValueError("invalid quota limit: retry_requests_per_window")
        for name in ("window_seconds", "retry_window_seconds", "lease_seconds", "max_cooldown_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0.01 <= value <= 604800:
                raise ValueError(f"invalid quota limit: {name}")
        if self.max_queue_per_study > self.max_queue:
            raise ValueError("per-study queue limit exceeds account queue limit")


@dataclass(frozen=True)
class QuotaLease:
    lease_id: str
    scope_id: str
    study_id: str
    job_id: str
    attempt_token: str
    estimated_tokens: int
    retry: bool


@dataclass(frozen=True)
class Admission:
    lease: QuotaLease | None
    reason: str | None
    retry_after: float | None
    effective_limits: dict
    config_conflict: bool = False

    @property
    def admitted(self):
        return self.lease is not None


def _label(value, name):
    # Scope is an opaque operator label, never a credential or a key digest.
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid quota {name}")
    return value


def _pid_namespace():
    if sys.platform.startswith("linux"):
        try: return os.readlink("/proc/self/ns/pid")
        except OSError: return None
    return "darwin-host-pid-space" if sys.platform == "darwin" else None


@lru_cache(maxsize=1)
def _boot_identity():
    """Public kernel generation; not machine credentials or environments."""
    try:
        if sys.platform.startswith("linux"):
            return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        if sys.platform == "darwin":
            class Timeval(ctypes.Structure):
                _fields_ = [("sec", ctypes.c_long), ("usec", ctypes.c_long)]
            value, length = Timeval(), ctypes.c_size_t(ctypes.sizeof(Timeval))
            if ctypes.CDLL(None).sysctlbyname(b"kern.boottime", ctypes.byref(value), ctypes.byref(length), None, 0) == 0:
                return f"{value.sec}:{value.usec}"
    except (OSError, ValueError):
        pass
    return None


def process_start_identity(pid: int) -> str | None:
    """Read OS process-start metadata without reading a process environment."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        boot = _boot_identity()
        if boot is None:
            return None
        if sys.platform.startswith("linux"):
            # /proc/stat field 22; comm may contain spaces and parentheses.
            text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            return "linux:" + boot + ":" + text[text.rfind(")") + 2:].split()[19]
        if sys.platform == "darwin":
            class BSDInfo(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint32) for name in (
                    "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid",
                    "svuid", "svgid", "rfu")] + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)] + [
                    (name, ctypes.c_uint32) for name in ("nfiles", "pgid", "pjobc", "e_tdev", "e_tpgid")
                ] + [("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
            info = BSDInfo()
            size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if size == ctypes.sizeof(info) and info.pid == pid:
                return f"darwin:{boot}:{info.start_sec}:{info.start_usec}"
    except (OSError, ValueError, IndexError):
        pass
    return None


def process_state(pid: int, identity: str | None) -> str:
    """'dead' requires OS evidence; inability to inspect is never death."""
    try:
        os.kill(pid, 0)
    except OSError as error:
        return "dead" if error.errno == errno.ESRCH else "unknown"
    observed = process_start_identity(pid)
    if identity is not None and observed is not None:
        return "alive" if identity == observed else "dead"
    return "unknown"


class QuotaCoordinator:
    """Nonblocking admission with bounded FIFO queues and study round-robin.

    Limits are a trusted operator configuration. Conflicting registrations only
    tighten a scope; widening it requires an explicit registry migration while
    idle. The registry must live on one host's local filesystem. Shared/NFS or
    independently copied registries do not provide cross-host coordination.
    """
    def __init__(self, registry_path, scope_id, limits=None, *, clock=None,
                 host_id=None, process_probe=None):
        self.path = Path(registry_path).expanduser().absolute()
        self.scope_id = _label(scope_id, "scope_id")
        self.requested_limits = limits if isinstance(limits, QuotaLimits) else QuotaLimits(**(limits or {}))
        self.clock = clock or time.time
        self.host_id = host_id or "host_" + hashlib.sha256(socket.gethostname().encode()).hexdigest()[:24]
        self.pid_namespace = _pid_namespace()
        if self.pid_namespace is None:
            raise ValueError("same-host quota coordination requires inspectable OS PID namespace metadata")
        self.process_probe = process_probe or process_state
        self.pid, self.start_identity = os.getpid(), process_start_identity(os.getpid())
        self._guard_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._guard_path()
        # Create without following an existing symbolic link. SQLite checks are
        # repeated before each connection; the registry directory is trusted.
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        with self._transaction() as db:
            existing_tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing_tables - {"registry_meta", "quota_scopes", "quota_waiters", "quota_leases", "quota_events", "sqlite_sequence"}:
                raise ValueError("quota registry path contains unrelated data; select a dedicated local registry")
            if "registry_meta" in existing_tables:
                version = db.execute("SELECT value FROM registry_meta WHERE key='schema_version'").fetchone()
                if version and version[0] != "1":
                    raise ValueError("unsupported quota registry schema version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS registry_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quota_scopes(scope TEXT PRIMARY KEY,limits TEXT NOT NULL,
                    conflict INTEGER NOT NULL DEFAULT 0,cooldown REAL NOT NULL DEFAULT 0,last_study TEXT);
                CREATE TABLE IF NOT EXISTS quota_waiters(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,attempt TEXT NOT NULL,study TEXT NOT NULL,job TEXT NOT NULL,
                    tokens INTEGER NOT NULL,retry INTEGER NOT NULL,pid INTEGER NOT NULL,start TEXT,
                    queued REAL NOT NULL, UNIQUE(scope,attempt));
                CREATE TABLE IF NOT EXISTS quota_leases(id TEXT PRIMARY KEY,scope TEXT NOT NULL,
                    attempt TEXT NOT NULL,study TEXT NOT NULL,job TEXT NOT NULL,tokens INTEGER NOT NULL,
                    retry INTEGER NOT NULL,pid INTEGER NOT NULL,start TEXT,state TEXT NOT NULL,
                    acquired REAL NOT NULL,expires REAL NOT NULL,settled REAL,actual_tokens INTEGER,resolution TEXT,
                    UNIQUE(scope,attempt));
                CREATE TABLE IF NOT EXISTS quota_events(scope TEXT NOT NULL,attempt TEXT NOT NULL,
                    at REAL NOT NULL,tokens INTEGER NOT NULL,retry INTEGER NOT NULL, PRIMARY KEY(scope,attempt));
                CREATE INDEX IF NOT EXISTS quota_active ON quota_leases(scope,state);
                CREATE INDEX IF NOT EXISTS quota_waiting ON quota_waiters(scope,study,seq);
                CREATE INDEX IF NOT EXISTS quota_rate ON quota_events(scope,at);
            """)
            # executescript ends a transaction; start a new serialized one.
            db.execute("BEGIN IMMEDIATE")
            if "resolution" not in {row[1] for row in db.execute("PRAGMA table_info(quota_leases)")}:
                db.execute("ALTER TABLE quota_leases ADD COLUMN resolution TEXT")
            row = db.execute("SELECT value FROM registry_meta WHERE key='host'").fetchone()
            if row and row[0] != self.host_id:
                raise ValueError("quota registry belongs to another host; use a shared gateway for multi-host admission")
            db.execute("INSERT OR IGNORE INTO registry_meta VALUES('host',?)", (self.host_id,))
            db.execute("INSERT OR IGNORE INTO registry_meta VALUES('schema_version','1')")
            row = db.execute("SELECT value FROM registry_meta WHERE key='pid_namespace'").fetchone()
            if row and row[0] != self.pid_namespace:
                raise ValueError("quota registry uses another PID namespace; containers require a shared gateway")
            db.execute("INSERT OR IGNORE INTO registry_meta VALUES('pid_namespace',?)", (self.pid_namespace,))
            row = db.execute("SELECT limits FROM quota_scopes WHERE scope=?", (self.scope_id,)).fetchone()
            requested = asdict(self.requested_limits)
            if row:
                original = json.loads(row[0])
                # A longer rolling window or lease duration is more restrictive.
                maximum = {"window_seconds", "retry_window_seconds", "lease_seconds"}
                effective = {key: (max(original[key], value) if key in maximum else min(original[key], value))
                             for key, value in requested.items()}
                effective["max_queue_per_study"] = min(effective["max_queue_per_study"], effective["max_queue"])
                db.execute("UPDATE quota_scopes SET limits=?, conflict=max(conflict,?) WHERE scope=?",
                           (json.dumps(effective, sort_keys=True), int(original != requested), self.scope_id))
            else:
                db.execute("INSERT INTO quota_scopes(scope,limits) VALUES(?,?)",
                           (self.scope_id, json.dumps(requested, sort_keys=True)))

    def _guard_path(self):
        # Refuse symbolic links below the caller's resolved parent directory.
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError("quota registry must be a private, owned regular file")
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError("quota registry permissions must exclude other users")
        for parent in (self.path.parent, *self.path.parent.parents):
            if parent.is_symlink():
                raise ValueError("quota registry ancestors cannot be symbolic links; use a resolved local directory")

    @contextmanager
    def _transaction(self):
        self._guard_path()
        db = sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("quota registry requires DELETE journal mode on local storage; review an idle migration")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=250")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _scope(self, db):
        row = db.execute("SELECT * FROM quota_scopes WHERE scope=?", (self.scope_id,)).fetchone()
        return row, json.loads(row["limits"])

    def _maintain(self, db, now, limits):
        # Queue participants may exit, but a living/unknown process never loses
        # its place just because a wall-clock deadline has elapsed.
        for row in db.execute("SELECT seq,pid,start FROM quota_waiters WHERE scope=?", (self.scope_id,)).fetchall():
            if self.process_probe(row["pid"], row["start"]) == "dead":
                db.execute("DELETE FROM quota_waiters WHERE seq=?", (row["seq"],))
        for row in db.execute("SELECT * FROM quota_leases WHERE scope=? AND state='reserved' AND expires<=?",
                              (self.scope_id, now)).fetchall():
            if self.process_probe(row["pid"], row["start"]) == "dead":
                # Protocol: mark_dispatched commits BEFORE invoking a provider.
                db.execute("UPDATE quota_leases SET state='not_sent',settled=? WHERE id=?", (now, row["id"]))
                db.execute("DELETE FROM quota_events WHERE scope=? AND attempt=?", (self.scope_id, row["attempt"]))
        horizon = max(limits["window_seconds"], limits["retry_window_seconds"])
        db.execute("DELETE FROM quota_events WHERE scope=? AND at<=?", (self.scope_id, now - horizon))
        # Terminal quota receipts are bounded; the collector's durable attempt
        # journal remains the complete accounting/idempotency authority.
        db.execute("DELETE FROM quota_leases WHERE id IN (SELECT id FROM quota_leases WHERE scope=? "
                   "AND state IN ('settled','not_sent') ORDER BY settled DESC,id DESC LIMIT -1 OFFSET ?)",
                   (self.scope_id, limits["max_history"]))

    @staticmethod
    def _lease(row):
        return QuotaLease(row["id"], row["scope"], row["study"], row["job"], row["attempt"], row["tokens"], bool(row["retry"]))

    def try_acquire(self, study_id, job_id, attempt_token=None, estimated_tokens=0, retry=False):
        study_id, job_id = _label(study_id, "study_id"), _label(job_id, "job_id")
        attempt_token = _label(attempt_token or job_id, "attempt_token")
        if type(estimated_tokens) is not int or not 0 <= estimated_tokens <= 100_000_000 or type(retry) is not bool:
            raise ValueError("invalid quota token estimate or retry flag")
        now = float(self.clock())
        if not math.isfinite(now):
            raise ValueError("quota clock must be finite")
        try:
            with self._transaction() as db:
                scope, limits = self._scope(db)
                conflict = bool(scope["conflict"])
                def denied(reason, delay=None):
                    return Admission(None, reason, delay, limits, conflict)
                self._maintain(db, now, limits)
                existing = db.execute("SELECT * FROM quota_leases WHERE scope=? AND attempt=?",
                                      (self.scope_id, attempt_token)).fetchone()
                if existing:
                    if (existing["study"], existing["job"], existing["tokens"], bool(existing["retry"])) != (study_id, job_id, estimated_tokens, retry):
                        raise ValueError("attempt token reused with different quota request")
                    if existing["state"] == "reserved" and existing["pid"] == self.pid and existing["start"] == self.start_identity:
                        return Admission(self._lease(existing), None, None, limits, conflict)
                    return denied("attempt_already_dispatched" if existing["state"] in ("dispatched", "uncertain") else "attempt_already_settled")
                if estimated_tokens > limits["tokens_per_window"]:
                    return denied("request_exceeds_account_token_window")
                waiter = db.execute("SELECT * FROM quota_waiters WHERE scope=? AND attempt=?",
                                    (self.scope_id, attempt_token)).fetchone()
                if waiter:
                    if (waiter["study"], waiter["job"], waiter["tokens"], bool(waiter["retry"]), waiter["pid"], waiter["start"]) != (
                            study_id, job_id, estimated_tokens, retry, self.pid, self.start_identity):
                        raise ValueError("queued attempt token reused by another request or process")
                else:
                    count = db.execute("SELECT count(*) FROM quota_waiters WHERE scope=?", (self.scope_id,)).fetchone()[0]
                    per_study = db.execute("SELECT count(*) FROM quota_waiters WHERE scope=? AND study=?", (self.scope_id, study_id)).fetchone()[0]
                    if count >= limits["max_queue"] or per_study >= limits["max_queue_per_study"]:
                        return denied("account_queue_full")
                    db.execute("INSERT INTO quota_waiters(scope,attempt,study,job,tokens,retry,pid,start,queued) VALUES(?,?,?,?,?,?,?,?,?)",
                               (self.scope_id, attempt_token, study_id, job_id, estimated_tokens, int(retry), self.pid, self.start_identity, now))
                if scope["cooldown"] > now:
                    return denied("account_cooldown", scope["cooldown"] - now)
                active = db.execute("SELECT count(*) FROM quota_leases WHERE scope=? AND state IN ('reserved','dispatched','uncertain')",
                                    (self.scope_id,)).fetchone()[0]
                if active >= limits["max_inflight"]:
                    return denied("account_inflight_limit")
                events = db.execute("SELECT at,tokens,retry FROM quota_events WHERE scope=?", (self.scope_id,)).fetchall()
                recent = [row for row in events if row["at"] > now - limits["window_seconds"]]
                if len(recent) >= limits["requests_per_window"]:
                    return denied("account_request_rate", min(row["at"] for row in recent) + limits["window_seconds"] - now)
                if sum(row["tokens"] for row in recent) + estimated_tokens > limits["tokens_per_window"]:
                    return denied("account_token_rate", min(row["at"] for row in recent) + limits["window_seconds"] - now)
                retries = [row for row in events if row["retry"] and row["at"] > now - limits["retry_window_seconds"]]
                if retry and len(retries) >= limits["retry_requests_per_window"]:
                    return denied("account_retry_budget", min((row["at"] for row in retries), default=now) + limits["retry_window_seconds"] - now)
                # FIFO within a study; alternate studies when another study is
                # queued. A full study cannot fill every subsequent free slot.
                heads = db.execute("SELECT * FROM quota_waiters WHERE seq IN (SELECT min(seq) FROM quota_waiters "
                                   "WHERE scope=? GROUP BY study) ORDER BY seq", (self.scope_id,)).fetchall()
                headroom = limits["tokens_per_window"] - sum(row["tokens"] for row in recent)
                heads = [row for row in heads if row["tokens"] <= headroom and
                         (not row["retry"] or len(retries) < limits["retry_requests_per_window"])]
                candidates = [row for row in heads if row["study"] != scope["last_study"]] or heads
                if not candidates or candidates[0]["attempt"] != attempt_token:
                    return denied("account_fair_queue")
                lease_id = "ql_" + uuid.uuid4().hex
                db.execute("INSERT INTO quota_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    lease_id, self.scope_id, attempt_token, study_id, job_id, estimated_tokens, int(retry),
                    self.pid, self.start_identity, "reserved", now, now + limits["lease_seconds"], None, None, None))
                db.execute("INSERT INTO quota_events VALUES(?,?,?,?,?)", (self.scope_id, attempt_token, now, estimated_tokens, int(retry)))
                db.execute("DELETE FROM quota_waiters WHERE scope=? AND attempt=?", (self.scope_id, attempt_token))
                db.execute("UPDATE quota_scopes SET last_study=? WHERE scope=?", (study_id, self.scope_id))
                return Admission(QuotaLease(lease_id, self.scope_id, study_id, job_id, attempt_token, estimated_tokens, retry),
                                 None, None, limits, conflict)
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                return Admission(None, "account_registry_busy", 0.25, asdict(self.requested_limits))
            raise

    def _row_for_lease(self, db, lease):
        if not isinstance(lease, QuotaLease) or lease.scope_id != self.scope_id:
            raise ValueError("invalid quota lease")
        row = db.execute("SELECT * FROM quota_leases WHERE id=? AND scope=? AND attempt=?",
                         (lease.lease_id, self.scope_id, lease.attempt_token)).fetchone()
        if row is None or self._lease(row) != lease:
            raise ValueError("quota lease receipt unavailable or mismatched")
        return row

    def mark_dispatched(self, lease):
        """Commit this immediately before provider invocation; never afterward."""
        with self._transaction() as db:
            row = self._row_for_lease(db, lease)
            if row["state"] != "reserved" or row["pid"] != self.pid or row["start"] != self.start_identity:
                raise ValueError("quota lease is not owned and reserved")
            db.execute("UPDATE quota_leases SET state='dispatched' WHERE id=?", (lease.lease_id,))

    def lease(self, lease_id):
        """Recover a bounded lease receipt after reopening the same registry."""
        with self._transaction() as db:
            row = db.execute("SELECT * FROM quota_leases WHERE scope=? AND id=?",
                             (self.scope_id, _label(lease_id, "lease_id"))).fetchone()
            return self._lease(row) if row else None

    def release(self, lease, *, outcome="settled", actual_tokens=None):
        """Unknown outcomes keep capacity; rate reservations survive settlement.

        'not_sent' requires proof the request never crossed the dispatch boundary.
        An adapter's definitive rejection may be 'settled' with zero actual tokens.
        Unknown usage keeps the larger estimate rather than assigning zero.
        """
        if outcome not in {"settled", "not_sent", "uncertain"}:
            raise ValueError("invalid quota outcome")
        if actual_tokens is not None and (type(actual_tokens) is not int or not 0 <= actual_tokens <= 100_000_000):
            raise ValueError("invalid actual quota tokens")
        with self._transaction() as db:
            row = self._row_for_lease(db, lease)
            if row["state"] in {"settled", "not_sent"}:
                if row["state"] != outcome:
                    raise ValueError("quota settlement cannot be reversed")
                return
            if row["state"] == "uncertain" and outcome != "uncertain":
                raise ValueError("uncertain quota lease requires explicit resolve_uncertain")
            if outcome == "not_sent" and row["state"] != "reserved":
                raise ValueError("dispatched quota lease cannot be declared not_sent")
            db.execute("UPDATE quota_leases SET state=?,settled=?,actual_tokens=? WHERE id=?",
                       (outcome, None if outcome == "uncertain" else self.clock(), actual_tokens, lease.lease_id))
            if outcome == "not_sent":
                db.execute("DELETE FROM quota_events WHERE scope=? AND attempt=?", (self.scope_id, lease.attempt_token))
            elif actual_tokens is not None:
                db.execute("UPDATE quota_events SET tokens=max(tokens,?) WHERE scope=? AND attempt=?",
                           (actual_tokens, self.scope_id, lease.attempt_token))

    def resolve_uncertain(self, lease, *, evidence, actual_tokens=None):
        """Trusted operator/provider evidence must establish execution is over.

        A local worker's death alone does not prove remote inference terminated.
        Evidence is a bounded receipt reference, not arbitrary provider text.
        """
        _label(evidence, "resolution evidence reference")
        if actual_tokens is not None and (type(actual_tokens) is not int or not 0 <= actual_tokens <= 100_000_000):
            raise ValueError("invalid actual quota tokens")
        with self._transaction() as db:
            row = self._row_for_lease(db, lease)
            if row["state"] not in {"uncertain", "dispatched"}:
                raise ValueError("quota lease is not unresolved")
            db.execute("UPDATE quota_leases SET state='settled',settled=?,actual_tokens=?,resolution=? WHERE id=?",
                       (self.clock(), actual_tokens, evidence, lease.lease_id))
            if actual_tokens is not None:
                db.execute("UPDATE quota_events SET tokens=max(tokens,?) WHERE scope=? AND attempt=?",
                           (actual_tokens, self.scope_id, lease.attempt_token))

    def cancel_waiter(self, attempt_token):
        with self._transaction() as db:
            db.execute("DELETE FROM quota_waiters WHERE scope=? AND attempt=? AND pid=? AND start IS ?",
                       (self.scope_id, _label(attempt_token, "attempt_token"), self.pid, self.start_identity))

    def cooldown(self, seconds):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("invalid account cooldown")
        with self._transaction() as db:
            _, limits = self._scope(db)
            # Oversized Retry-After is an explicit bounded scheduling conflict;
            # do not retry earlier by silently clamping a provider minimum.
            if seconds > limits["max_cooldown_seconds"]:
                raise ValueError("provider cooldown exceeds the configured finite scheduling envelope")
            db.execute("UPDATE quota_scopes SET cooldown=max(cooldown,?) WHERE scope=?",
                       (self.clock() + seconds, self.scope_id))

    def diagnostics(self):
        with self._transaction() as db:
            now = self.clock()
            scope, limits = self._scope(db)
            self._maintain(db, now, limits)
            states = {row["state"]: row["n"] for row in db.execute(
                "SELECT state,count(*) AS n FROM quota_leases WHERE scope=? GROUP BY state", (self.scope_id,))}
            expired = db.execute("SELECT count(*) FROM quota_leases WHERE scope=? AND state IN ('reserved','dispatched','uncertain') AND expires<=?",
                                 (self.scope_id, now)).fetchone()[0]
            return {"version": 1, "coordination": "same_host_cross_process", "scope_id": self.scope_id,
                    "host_id": self.host_id, "effective_limits": limits, "config_conflict": bool(scope["conflict"]),
                    "states": states, "inflight": sum(states.get(s, 0) for s in ("reserved", "dispatched", "uncertain")),
                    "expired_unresolved_leases": expired,
                    "queued": db.execute("SELECT count(*) FROM quota_waiters WHERE scope=?", (self.scope_id,)).fetchone()[0],
                    "cooldown_remaining_seconds": max(0, scope["cooldown"] - now),
                    "remote_execution_uncertainty": states.get("uncertain", 0) + states.get("dispatched", 0),
                    "outside_clients_are_uncoordinated": True, "multi_host_supported": False}
