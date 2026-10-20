"""SQLite transactions and explicit separate record tables."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from .config import canonical

TABLES = ("sources", "terms", "occurrences", "runs", "jobs", "audit", "annotations",
          "relations", "discovery", "costs", "cache", "versions")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def digest(value):
    raw = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ident(prefix, value):
    return prefix + "_" + digest(value)[:24]


class Store:
    def __init__(self, path, *, path_guard=None):
        self.path = Path(path)
        if path_guard is not None and not callable(path_guard):
            raise ValueError("Invalid store path guard")
        self._path_guard = path_guard
        self._session = ContextVar("termfinder_sqlite_session", default=None)
        self._depth = ContextVar("termfinder_sqlite_depth", default=0)
        self._guard_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for table in TABLES:
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS run_jobs (run_id TEXT NOT NULL, job_id TEXT NOT NULL, is_root INTEGER NOT NULL, PRIMARY KEY(run_id,job_id))")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_ready_v2 ON jobs(json_extract(data,'$.model_key'),json_extract(data,'$.status'),json_extract(data,'$.not_before'),id)")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_ready_v3 ON jobs(json_extract(data,'$.model_key'),json_extract(data,'$.status'),coalesce(json_extract(data,'$.not_before'),0),id)")
            db.execute("CREATE INDEX IF NOT EXISTS costs_scope_v2 ON costs(json_extract(data,'$.policy_hash'),json_extract(data,'$.budget_scope'))")
            db.execute("CREATE INDEX IF NOT EXISTS evidence_record_v2 ON occurrences(json_extract(data,'$.term_id'),id)")
            db.execute("CREATE INDEX IF NOT EXISTS annotation_record_v2 ON annotations(json_extract(data,'$.term_id'),id)")
            db.execute("CREATE INDEX IF NOT EXISTS versions_catalog_v2 ON versions(json_extract(data,'$.dataset.version_id'),json_extract(data,'$.dataset.name'),json_extract(data,'$.dataset.created_at'))")
            row = db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
            if row and json.loads(row[0]) != 1:
                raise ValueError("unsupported project database schema")
            self.setting("schema_version", 1, db)

    @contextmanager
    def connection(self):
        self._guard_path()
        db = self._session.get()
        owned = db is None
        connection_token = None
        if owned:
            db = self._connect()
            connection_token = self._session.set(db)
        depth = self._depth.get()
        token = self._depth.set(depth + 1)
        try:
            yield db
            if depth == 0: db.commit()
        except BaseException:
            if depth == 0: db.rollback()
            raise
        finally:
            self._depth.reset(token)
            if owned:
                self._session.reset(connection_token)
                db.close()

    def _connect(self):
        self._guard_path()
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA synchronous=FULL")
        db.create_function("unicode_fold",1,lambda value:(value or "").casefold(),deterministic=True)
        return db

    @contextmanager
    def session(self):
        """Reuse a thread-local connection; individual transactions still commit."""
        self._guard_path()
        if self._session.get() is not None:
            yield
            return
        db = self._connect()
        token = self._session.set(db)
        try: yield
        finally:
            self._session.reset(token)
            db.close()

    def _guard_path(self):
        if self._path_guard is not None:
            self._path_guard()

    def rows(self, table, *, where="1", params=(), limit=None, offset=0, db=None):
        """Internal parameterized query. SQL predicates are never user inputs."""
        if table not in TABLES: raise ValueError("unknown table")
        if db is None:
            with self.connection() as conn:
                return self.rows(table, where=where, params=params, limit=limit, offset=offset, db=conn)
        sql = f"SELECT data FROM {table} WHERE {where} ORDER BY id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (*params, limit, offset)
        return [json.loads(row[0]) for row in db.execute(sql, params)]

    def iter_rows(self, table, *, where="1", params=(), batch_size=64):
        if table not in TABLES: raise ValueError("unknown table")
        last = ""
        while True:
            with self.connection() as db:
                rows = db.execute(f"SELECT id,data FROM {table} WHERE ({where}) AND id>? ORDER BY id LIMIT ?", (*params,last,batch_size)).fetchall()
            if not rows: return
            for key,data in rows:
                last = key
                yield json.loads(data)

    def count(self, table, *, where="1", params=(), db=None):
        if table not in TABLES: raise ValueError("unknown table")
        if db is None:
            with self.connection() as conn: return self.count(table, where=where, params=params, db=conn)
        return db.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]

    def register_jobs(self, run_id, ids, *, root=False, db=None):
        if db is None:
            with self.connection() as conn: return self.register_jobs(run_id, ids, root=root, db=conn)
        db.executemany("INSERT INTO run_jobs(run_id,job_id,is_root) VALUES(?,?,?) ON CONFLICT(run_id,job_id) DO UPDATE SET is_root=max(is_root,excluded.is_root)",
                       ((run_id,key,int(root)) for key in ids))

    def run_job_rows(self, run_id, *, status=None, model_key=None, ready_at=None, limit=None):
        index = " INDEXED BY jobs_ready_v3" if model_key and status else ""
        sql = "SELECT j.data FROM jobs j" + index + " JOIN run_jobs m ON m.job_id=j.id WHERE m.run_id=?"
        args = [run_id]
        if status:
            sql += " AND json_extract(j.data,'$.status')=?"; args.append(status)
        if model_key:
            sql += " AND json_extract(j.data,'$.model_key')=?"; args.append(model_key)
        if ready_at is not None:
            sql += " AND coalesce(json_extract(j.data,'$.not_before'),0)<=?"; args.append(ready_at)
        sql += " ORDER BY coalesce(json_extract(j.data,'$.not_before'),0),j.id"
        if limit is not None: sql += " LIMIT ?"; args.append(limit)
        with self.connection() as db: return [json.loads(row[0]) for row in db.execute(sql,args)]

    def prune_run_index(self, current_run):
        # These are disposable scheduler memberships; historical runs/jobs stay.
        with self.connection() as db:
            db.execute("DELETE FROM run_jobs WHERE run_id!=?", (current_run,))

    def checkpoint(self):
        # PASSIVE does not wait for browser readers or hold a long writer lock.
        with self.connection() as db:
            return tuple(db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone())

    def backup(self, target):
        """Consistent WAL-aware local backup, with a finite wall deadline."""
        target=Path(target).expanduser().absolute()
        if target.exists() or target.is_symlink(): raise FileExistsError("Backup destination already exists")
        target.parent.mkdir(parents=True,exist_ok=True)
        handle,temporary=tempfile.mkstemp(prefix=".termfinder-backup-",dir=target.parent)
        os.close(handle)
        try:
            deadline=time.monotonic()+300
            def progress(status,remaining,total):
                if time.monotonic()>=deadline: raise ValueError("Backup time limit exceeded; original project is intact")
            with sqlite3.connect(temporary) as destination, self.connection() as source:
                source.backup(destination,pages=256,progress=progress,sleep=0.05)
                # The active database stays WAL. A durable backup is a closed
                # standalone generation, safe to stage without WAL/SHM siblings.
                destination.execute("PRAGMA journal_mode=DELETE")
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok": raise ValueError("Backup integrity check failed")
            os.link(temporary,target)
        finally:
            os.unlink(temporary)
        return {"path":str(target),"bytes":target.stat().st_size,"consistency":"sqlite_online_backup","integrity":"quick_check_passed"}

    def version_catalog(self):
        # Expression index provides metadata without deserializing frozen blobs.
        with self.connection() as db:
            rows=db.execute("SELECT json_extract(data,'$.dataset.version_id'),json_extract(data,'$.dataset.name'),json_extract(data,'$.dataset.created_at') FROM versions INDEXED BY versions_catalog_v2 ORDER BY json_extract(data,'$.dataset.version_id')").fetchall()
        return [dict(zip(("version_id","name","created_at"),row)) for row in rows]

    def status_counts(self, table):
        if table not in TABLES: raise ValueError("unknown table")
        with self.connection() as db:
            return dict(db.execute(f"SELECT json_extract(data,'$.status'),count(*) FROM {table} GROUP BY 1"))

    def stage_costs(self, stages):
        result = {stage:{"estimated_actual_usd":0.0,"simulated_usd":0.0,"reserved_unknown_usd":0.0,
                         "pending_reservations_usd":0.0,"calls":0} for stage in stages}
        sql = """SELECT json_extract(data,'$.stage'),
            sum(coalesce(json_extract(data,'$.request_count'),0)),
            sum(CASE WHEN json_extract(data,'$.billing_kind')!='simulated' THEN coalesce(json_extract(data,'$.settled_usd'),0) ELSE 0 END),
            sum(CASE WHEN json_extract(data,'$.billing_kind')='simulated' THEN coalesce(json_extract(data,'$.settled_usd'),0) ELSE 0 END),
            sum(CASE WHEN json_extract(data,'$.status')='uncertain' AND json_type(data,'$.settled_usd') IS NULL THEN coalesce(json_extract(data,'$.reserved_usd'),0) ELSE 0 END),
            sum(CASE WHEN json_extract(data,'$.status')!='uncertain' AND json_type(data,'$.settled_usd') IS NULL THEN coalesce(json_extract(data,'$.reserved_usd'),0) ELSE 0 END)
            FROM costs GROUP BY 1"""
        with self.connection() as db:
            for stage,calls,actual,simulated,unknown,pending in db.execute(sql):
                if stage in result:
                    result[stage].update(calls=calls,estimated_actual_usd=actual,simulated_usd=simulated,
                                         reserved_unknown_usd=unknown,pending_reservations_usd=pending)
        return result

    def put(self, table, key, value, db=None):
        if table not in TABLES:
            raise ValueError("unknown table")
        if db is None:
            with self.connection() as conn:
                self.put(table, key, value, conn)
        else:
            db.execute(f"INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                       (key, canonical(value)))

    def get(self, table, key, db=None):
        if table not in TABLES:
            raise ValueError("unknown table")
        if db is None:
            with self.connection() as conn:
                return self.get(table, key, conn)
        row = db.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, table, db=None):
        if table not in TABLES:
            raise ValueError("unknown table")
        if db is None:
            with self.connection() as conn:
                return self.all(table, conn)
        return [json.loads(row[0]) for row in db.execute(f"SELECT data FROM {table} ORDER BY id")]

    def setting(self, key, value=None, db=None, *, write=True):
        if db is None:
            with self.connection() as conn:
                return self.setting(key, value, conn, write=write)
        if write:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, canonical(value)))
            return value
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def read_setting(self, key):
        return self.setting(key, write=False)
