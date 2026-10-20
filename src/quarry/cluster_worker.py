"""Reviewed single-node worker for frozen Quarry cluster bundles.

Run only through a resource-approved generated script. Use an existing approved
endpoint or the reviewed fixed server launcher. Active SQLite state stays on node-local scratch and
durable checkpoints are made with SQLite's online backup API.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import threading
import time
import uuid
import re

from .cluster import (ACTIVE, JOB_ID, VERSION, ClusterController, file_sha256,
    metadata_lock, package_fingerprint, read_json, status_summary, verify_bundle, write_json)
from .project import Project
from .store import now
from .workflow import run_review


def _job(root, submission):
    state = read_json(root / "state.json")
    if not isinstance(state, dict) or not isinstance(state.get("jobs"), list):
        raise ValueError("Cluster submission state is missing")
    matches = [job for job in state["jobs"] if job.get("job_id") == submission]
    if len(matches) != 1:
        raise ValueError("Cluster submission is not registered")
    return state, matches[0]


def _retain_checkpoints(bundle, state, owned):
    """Prune only this worker's old, unreferenced immutable generations.

    Call while holding the durable metadata lock, after publishing a new
    checkpoint receipt. Keep latest+previous plus every saved checkpoint or
    resume reference. Other allocations' generations and frozen input bundles
    are never candidates. Returning the compact ownership list bounds memory.
    """
    bundle = Path(bundle)
    references = set()
    for job in state["jobs"]:
        for field in ("checkpoint", "resume_checkpoint"):
            receipt = job.get(field)
            if isinstance(receipt, dict) and isinstance(receipt.get("file"), str):
                references.add(receipt["file"])
    keep = references | set(owned[-2:])
    retained = []
    for relative in owned:
        if not isinstance(relative, str) or not re.fullmatch(r"checkpoints/checkpoint_[0-9a-f]{32}\.sqlite3", relative):
            raise ValueError("Unsafe owned checkpoint generation")
        if relative in keep:
            retained.append(relative)
            continue
        path = bundle / relative
        if bundle.is_symlink() or path.parent.is_symlink() or path.is_symlink():
            raise ValueError("Checkpoint retention cannot traverse symlinks")
        if path.exists():
            if not path.is_file():
                raise ValueError("Checkpoint generation is not a regular file")
            path.unlink()
    return retained


def run_bundle(bundle, submission, *, execute=False, provider=None, max_jobs=None,
               scratch_root=None, install_signals=False, serving_factory=None):
    """Complete/resume reviewed extraction, independent of any MCP connection.

    provider/max_jobs/scratch_root are notebook/offline verification hooks. The
    fixed production command supplies none of them and cannot select a model,
    execute generated code, or alter the frozen recipe.
    """
    if type(execute) is not bool or not execute:
        raise ValueError("The trusted worker execution gate is required")
    if not isinstance(submission, str) or not JOB_ID.fullmatch(submission):
        raise ValueError("Invalid Quarry submission identifier")
    allocated_started = time.monotonic()
    if Path(bundle).is_symlink():
        raise ValueError("Cluster bundle cannot be a symlink")
    bundle = Path(bundle).resolve()
    manifest = verify_bundle(bundle)
    profile = manifest["binding"]["profile"]
    root = bundle.parent.parent
    with metadata_lock(root):
        state, job = _job(root, submission)
        if job["state"] not in {"submitted", "pending", "running", "submitting"} or job.get("started_at"):
            raise ValueError("Submission cannot start again; use an explicit resumed allocation")
        if (job["cluster_review_id"] != manifest["cluster_review_id"]
                or job["approval"]["binding_sha256"] != manifest["binding_sha256"]
                or job["approval"].get("human_approved") is not True):
            raise ValueError("Cluster approval does not match the frozen bundle")
        try:
            runtime = profile["runtime"]
            if file_sha256(Path(runtime["python_executable"]).resolve()) != runtime["python_sha256"]:
                raise ValueError("Reviewed runtime binary hash changed")
            if Path(sys.executable).resolve() != Path(runtime["python_executable"]).resolve():
                raise ValueError("Worker is not using the reviewed Python runtime")
            if package_fingerprint() != manifest["binding"]["collector_package"]:
                raise ValueError("Collector package code or resources changed after review")
        except Exception:
            job.update(state="failed", reason="reviewed_runtime_integrity_failed", finished_at=now())
            write_json(root / "state.json", state)
            raise
        job.update(state="running", started_at=now())
        write_json(root / "state.json", state)
        allow_paid = job["allow_paid"]
        checkpoint = job.get("resume_checkpoint")
    selected_scratch = scratch_root or os.environ.get(profile["scratch_env"])
    active_parent = None
    try:
        if not selected_scratch:
            raise ValueError("Approved node-local scratch environment is unavailable")
        scratch = Path(selected_scratch).resolve()
        if not scratch.is_dir() or scratch == bundle or scratch.is_relative_to(root) or root.is_relative_to(scratch):
            raise ValueError("Node-local scratch must be separate from durable cluster storage")
        active_parent = tempfile.mkdtemp(prefix="quarry-active-", dir=scratch)
        os.chmod(active_parent, 0o700)
        active = Path(active_parent) / "study"
        active.mkdir(mode=0o700)
        input_path = ClusterController._verify_checkpoint(checkpoint, bundle) if checkpoint else bundle / "input.sqlite3"
        shutil.copyfile(input_path, active / "project.sqlite3")
        shutil.copytree(bundle / "human-review", active / "human-review")
        project = Project(active)
    except Exception:
        if active_parent:
            shutil.rmtree(active_parent)
        with metadata_lock(root):
            latest, record = _job(root, submission)
            record.update(state="failed", reason="node_local_staging_failed", finished_at=now())
            write_json(root / "state.json", latest)
        raise
    started = allocated_started
    stop = threading.Event()
    monitor_done = threading.Event()
    reason = {"value": None}
    checkpoint_lock = threading.Lock()
    owned_checkpoints = []
    old_handlers = {}
    server = None

    def request_stop(label):
        reason["value"] = reason["value"] or label
        stop.set()

    def handler(signum, frame):
        # Signal handlers do not perform SQLite or other blocking operations.
        request_stop("scheduler_signal_" + signal.Signals(signum).name)

    def checkpoint_now(final=False, result=None):
        with checkpoint_lock:
            directory = bundle / "checkpoints"
            directory.mkdir(mode=0o700, exist_ok=True)
            path = directory / ("checkpoint_" + uuid.uuid4().hex + ".sqlite3")
            project.store.backup(path)
            owned_checkpoints.append(path.relative_to(bundle).as_posix())
            receipt = {"file": path.relative_to(bundle).as_posix(), "sha256": file_sha256(path),
                "created_at": now(), "consistency": "sqlite_online_backup", "final": final}
            with metadata_lock(root):
                latest, record = _job(root, submission)
                record["checkpoint"] = receipt
                record["worker_elapsed_seconds"] = round(time.monotonic() - started, 6)
                record["worker_gpu_hours_lower_bound"] = record["worker_elapsed_seconds"] * profile["gpus"] / 3600
                if final:
                    record.update(state="completed" if result and result.get("status") == "complete" else "partial",
                        finished_at=now(), result=status_summary(result), stop_reason=reason["value"])
                    if record.get("cancel_requested") or reason["value"]:
                        record["state"] = "cancelled" if reason["value"] == "researcher_cancel" else "partial"
                write_json(root / "state.json", latest)
                # Only after publication: a crash during pruning leaves the
                # new authoritative generation intact. Import/status/other
                # workers take this same lock before acquiring references.
                owned_checkpoints[:] = _retain_checkpoints(bundle, latest, owned_checkpoints)
            return receipt

    def monitor():
        next_checkpoint = started + profile["checkpoint_seconds"]
        while not monitor_done.wait(0.2):
            elapsed = time.monotonic() - started
            if elapsed >= profile["walltime_seconds"] - profile["shutdown_grace_seconds"]:
                request_stop("allocation_deadline_checkpoint")
            try:
                with metadata_lock(root):
                    _, latest = _job(root, submission)
                    if latest.get("cancel_requested"):
                        request_stop("researcher_cancel")
                if stop.is_set():
                    project.cancel()
                if time.monotonic() >= next_checkpoint:
                    checkpoint_now()
                    next_checkpoint = time.monotonic() + profile["checkpoint_seconds"]
            except Exception:
                request_stop("durable_checkpoint_or_control_failure")
                project.cancel()
                # A failing storage backend must not create another full
                # orphan backup on every monitor tick. Stop admission and
                # leave the last published generation authoritative; the
                # outer worker performs at most its bounded final attempt.
                return

    try:
        if install_signals:
            if threading.current_thread() is not threading.main_thread():
                raise ValueError("Signal-aware worker must run on its main thread")
            for signum in (signal.SIGUSR1, signal.SIGTERM, signal.SIGINT):
                old_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, handler)
            old_handlers[signal.SIGALRM] = signal.getsignal(signal.SIGALRM)
            # The durable periodic receipt survives even an unresponsive
            # endpoint or storage operation. Slurm independently bounds time.
            signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
            signal.alarm(max(1, profile["walltime_seconds"] - int(time.monotonic() - started)))
        project.store.setting("cluster_execution", {"version": VERSION,
            "cluster_review_id": manifest["cluster_review_id"], "binding_sha256": manifest["binding_sha256"],
            "job_id": submission, "runtime": deepcopy(profile["runtime"]),
            "collector_package": deepcopy(manifest["binding"]["collector_package"]),
            "model_artifacts": deepcopy(profile["model_artifacts"]), "resources": deepcopy(profile),
            "artifact_identity_note": "Checkpoint hashes are operator declarations for the existing endpoint, not remote attestation",
            "started_at": now(), "active_database": "private_node_local_scratch",
            "durable_backup": "sqlite_online_backup", "reproducibility": "Frozen exports reproducible; new inference can vary"})
        # Establish a durable receipt before issuing any extractor requests.
        checkpoint_now()
        watcher = threading.Thread(target=monitor, name="quarry-cluster-checkpoint", daemon=True)
        watcher.start()
        try:
            if profile.get("server") is not None:
                from .serving import VLLMServer
                server = (serving_factory or VLLMServer)(profile, project.profile)
                server.cancelled = stop.is_set
                receipt = server.start()
                execution = project.store.read_setting("cluster_execution")
                execution["server"] = receipt
                project.store.setting("cluster_execution", execution)
                checkpoint_now()
                if stop.is_set():
                    raise RuntimeError("Allocation stopped during model startup")
            result = run_review(project, manifest["binding"]["collection_review_id"],
                provider=provider, allow_paid=allow_paid, max_jobs=max_jobs, _cluster_worker=True)
        finally:
            monitor_done.set()
            watcher.join(timeout=min(profile["shutdown_grace_seconds"], 30))
        elapsed = time.monotonic() - started
        execution = project.store.read_setting("cluster_execution")
        execution.update(finished_at=now(), worker_elapsed_seconds=round(elapsed, 6),
            worker_gpu_hours_lower_bound=elapsed * profile["gpus"] / 3600, stop_reason=reason["value"])
        project.store.setting("cluster_execution", execution)
        checkpoint_now(final=True, result=result)
        return {"job_id": submission, "result": result, "worker_gpu_hours_lower_bound": execution["worker_gpu_hours_lower_bound"],
            "runtime": deepcopy(profile["runtime"])}
    except BaseException:
        monitor_done.set()
        try:
            checkpoint_now()
        except Exception:
            pass
        with metadata_lock(root):
            latest, record = _job(root, submission)
            record.update(state="failed", finished_at=now(), reason="worker_processing_failed_details_not_logged")
            write_json(root / "state.json", latest)
        raise
    finally:
        monitor_done.set()
        if server is not None:
            server.close()
        if install_signals:
            signal.alarm(0)
            for signum, old in old_handlers.items():
                signal.signal(signum, old)
        shutil.rmtree(active_parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--submission", required=True)
    parser.add_argument("--execute", action="store_true", help="Trusted resource execution gate")
    args = parser.parse_args(argv)
    try:
        run_bundle(args.bundle, args.submission, execute=args.execute, install_signals=True)
    except BaseException:
        # Provider/scheduler exception bodies may include credentials or source
        # text. Detailed structured job/audit state remains in the checkpoint.
        print("Quarry cluster worker stopped; inspect structured job state and checkpoints.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
