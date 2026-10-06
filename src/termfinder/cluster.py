"""Finite, approval-bound single-node Slurm collection.

The control process may exit after submission. Scheduler configuration is an
operator input, never part of a research recipe or an extraction response.
Bundles contain consistent SQLite backups, not copied live WAL files. This
module never downloads models, starts a server, opens SSH, or executes a shell.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from urllib.parse import quote

from .agent_setup import _credential_free
from .store import TABLES, digest, ident, now
from .workflow import _check_review_unlocked, _approval_unlocked

VERSION = "quarry-cluster-v1"
ACTIVE = {"submitting", "submission_unknown", "submitted", "pending", "running", "completing", "cancel_requested", "unknown"}
TERMINAL = {"completed", "partial", "cancelled", "failed", "timeout", "node_fail", "out_of_memory", "preempted", "absent"}
SLURM_ID = re.compile(r"[1-9][0-9]{0,17}")
JOB_ID = re.compile(r"cluster_job_[0-9a-f]{32}")
HASH = re.compile(r"[0-9a-f]{64}")
MAX_JSON = 4_000_000


def allocation_unresolved(job):
    return job["state"] in ACTIVE or bool(job.get("scheduler_submission_uncertain"))


def status_summary(result):
    """Agent-facing diagnostics omit raw unresolved proposals and contexts."""
    result = deepcopy(result)
    if isinstance(result, dict) and isinstance(result.get("failures"), list):
        allowed = {"audit_id", "stage", "reason", "source_id", "job_id", "created_at", "status"}
        result["failures"] = [{k: v for k, v in item.items() if k in allowed}
            for item in result["failures"] if isinstance(item, dict)]
    return result


def _text(value, label, limit=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(c in value for c in "\x00\r\n"):
        raise ValueError(label + " requires bounded single-line text")
    return value


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label + " is outside the supported finite range")
    return value


def file_sha256(path, *, limit=16_000_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Expected a bounded regular cluster artifact")
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            checksum.update(block)
    return checksum.hexdigest()


def read_json(path, *, default=None):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return deepcopy(default)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError("Cluster metadata must be a bounded regular JSON file")
    try:
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ValueError("Duplicate JSON key")
                result[key] = item
            return result
        def constant(value):
            raise ValueError("Nonfinite JSON number")
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, OSError, RecursionError):
        raise ValueError("Cluster metadata could not be read") from None


def write_json(path, value):
    """Atomic, fsynced metadata generation; never truncate an existing receipt."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe cluster metadata destination")
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_JSON:
        raise ValueError("Cluster metadata size limit exceeded")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".quarry-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def metadata_lock(root):
    root = Path(root)
    if any(parent.is_symlink() for parent in (root, *root.parents)):
        raise ValueError("Cluster metadata cannot use a symlink directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = root / ".control.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe cluster control lock")
    with lock_path.open("a") as stream:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Cluster control lock timed out; retry after the current operation") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def normalize_profile(profile, *, project=None):
    if not isinstance(profile, dict):
        raise ValueError("Cluster profile must be an object")
    profile = deepcopy(profile)
    profile.setdefault("schema_version", VERSION)
    profile.setdefault("qos", None)
    profile.setdefault("scratch_env", "SLURM_TMPDIR")
    profile.setdefault("server", None)
    required = {"schema_version", "name", "account", "partition", "qos", "gpus", "cpus", "memory_gb",
        "walltime_seconds", "checkpoint_seconds", "shutdown_grace_seconds", "max_submissions", "max_gpu_hours",
        "scratch_env", "runtime", "model_artifacts", "configuration_reference", "durable_root", "server"}
    if set(profile) != required or profile["schema_version"] != VERSION:
        raise ValueError("Missing or unsupported cluster profile fields")
    _credential_free(profile)
    for field in ("name", "account", "partition", "qos"):
        value = profile[field]
        if field == "qos" and value is None:
            continue
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise ValueError("Use a safe Slurm name, account, partition or QoS identifier")
    for field, low, high in (("gpus", 0, 64), ("cpus", 1, 1024), ("memory_gb", 1, 8192),
            ("walltime_seconds", 60, 604800), ("checkpoint_seconds", 5, 3600),
            ("shutdown_grace_seconds", 5, 3600), ("max_submissions", 1, 100)):
        _integer(profile[field], low, high, field)
    hours = profile["max_gpu_hours"]
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or not 0 <= hours <= 1_000_000:
        raise ValueError("max_gpu_hours must be a finite nonnegative budget")
    reservation = profile["gpus"] * profile["walltime_seconds"] / 3600
    if hours + 1e-9 < reservation:
        raise ValueError("GPU-hour budget cannot cover one full allocation")
    if profile["shutdown_grace_seconds"] >= profile["walltime_seconds"]:
        raise ValueError("Shutdown grace must fit inside the allocation")
    if profile["walltime_seconds"] % 60:
        raise ValueError("Walltime must be whole minutes so GPU-hour reservations match Slurm")
    if profile["scratch_env"] not in {"SLURM_TMPDIR", "TMPDIR"}:
        raise ValueError("Select SLURM_TMPDIR or TMPDIR for approved node-local scratch")
    declared_root = _text(profile["durable_root"], "Approved durable storage directory", 4000)
    root = Path(declared_root)
    if (not root.is_absolute() or not root.is_dir() or root.is_symlink()
            or root.resolve() in {Path("/"), Path.home(), Path.home().parent}
            or any(part.lower() in {".ssh", ".aws", ".codex", ".git", "keychains"} for part in root.parts)):
        raise ValueError("Choose a specific existing approved durable directory")
    profile["durable_root"] = str(root.resolve())
    runtime = profile["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {"python_executable", "python_sha256", "runtime_id", "runtime_reference"}:
        raise ValueError("Declare a reviewed, preinstalled Python runtime")
    path = _text(runtime["python_executable"], "Python executable", 4000)
    if not Path(path).is_absolute() or path.startswith("-"):
        raise ValueError("Python executable must be an absolute reviewed path")
    if not isinstance(runtime["python_sha256"], str) or not HASH.fullmatch(runtime["python_sha256"]):
        raise ValueError("Declare the reviewed Python binary SHA-256")
    _text(runtime["runtime_id"], "Runtime identifier")
    _text(runtime["runtime_reference"], "Runtime review reference")
    _text(profile["configuration_reference"], "Configuration review reference")
    artifacts = profile["model_artifacts"]
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 64:
        raise ValueError("Declare each pre-reviewed extraction checkpoint")
    aliases = []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"model_alias", "checkpoint_id", "sha256", "quantization"}:
            raise ValueError("Unsupported model artifact declaration")
        aliases.append(_text(artifact["model_alias"], "Model alias", 128))
        _text(artifact["checkpoint_id"], "Checkpoint identifier")
        if not isinstance(artifact["sha256"], str) or not HASH.fullmatch(artifact["sha256"]):
            raise ValueError("Declare a checkpoint artifact SHA-256")
        if artifact["quantization"] is not None:
            _text(artifact["quantization"], "Quantization declaration", 256)
    if len(set(aliases)) != len(aliases):
        raise ValueError("Duplicate model artifact aliases")
    if project is not None:
        if not project.recipe or not project.profile:
            raise ValueError("Configure extraction before configuring the cluster")
        if set(aliases) != set(project.profile["models"]):
            raise ValueError("Model artifact aliases must match the extraction profile")
        if profile["shutdown_grace_seconds"] < project.recipe["execution"]["timeout_seconds"] + 30:
            raise ValueError("Shutdown grace must cover request timeout plus 30 seconds")
        if profile["server"] is None and profile["gpus"] and any(p["adapter"] != "fake" for p in project.profile["providers"].values()):
            raise ValueError("Existing endpoint collection requires zero GPUs; use the reviewed server profile for compute-node GPU serving")
    if profile["server"] is not None:
        from .serving import normalize_server
        profile["server"] = normalize_server(profile["server"], project.profile if project else None, profile)
        if profile["server"]["startup_timeout_seconds"] >= profile["walltime_seconds"] - profile["shutdown_grace_seconds"]:
            raise ValueError("Model startup timeout must fit before the allocation shutdown deadline")
        artifact = next((a for a in artifacts if a["model_alias"] == profile["server"]["model_alias"]), None)
        if artifact is None or artifact["sha256"] != digest(profile["server"]["artifact_files"]):
            raise ValueError("Owned model artifact SHA-256 must identify the complete canonical file/hash inventory")
    return profile


def project_fingerprint(project):
    """Logical snapshot hash; SQLite physical page layout is not an identity."""
    checksum = hashlib.sha256()
    with project.store.connection() as db:
        for row in db.execute("SELECT key,value FROM settings WHERE key!='cluster_import_receipt' ORDER BY key"):
            checksum.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())
        for table in TABLES:
            checksum.update(table.encode())
            for row in db.execute(f"SELECT id,data FROM {table} ORDER BY id"):
                checksum.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())
    return checksum.hexdigest()


def package_fingerprint():
    """Hash installed collector code/resources, excluding mutable bytecode."""
    root = Path(__file__).resolve().parent
    inventory, total = {}, 0
    paths = list(root.glob("*.py"))
    for directory in ("recipes", "profiles", "schemas", "fixtures"):
        paths.extend((root / directory).rglob("*"))
    for path in sorted(paths):
        if not path.is_file():
            continue
        if path.is_symlink() or path.stat().st_size > 16_000_000:
            raise ValueError("Collector package artifact is unsafe or oversized")
        total += path.stat().st_size
        if total > 64_000_000:
            raise ValueError("Collector package inventory limit exceeded")
        inventory[path.relative_to(root).as_posix()] = file_sha256(path)
    return {"sha256": digest(inventory), "files": inventory}


def verify_bundle(bundle):
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Unsafe cluster bundle")
    manifest = read_json(bundle / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("version") != VERSION:
        raise ValueError("Invalid cluster bundle manifest")
    binding = manifest.get("binding")
    if digest(binding) != manifest.get("binding_sha256") or ident("cluster_review", binding) != manifest.get("cluster_review_id"):
        raise ValueError("Cluster review integrity check failed")
    if not isinstance(binding.get("files"), dict) or not 1 <= len(binding["files"]) <= 2000:
        raise ValueError("Cluster bundle inventory is invalid")
    for relative, expected in binding["files"].items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not HASH.fullmatch(expected):
            raise ValueError("Unsafe bundle artifact")
        current = bundle
        for component in path.parts:
            current = current / component
            if current.is_symlink():
                raise ValueError("Bundle artifacts cannot be symlinks")
        if file_sha256(current) != expected:
            raise ValueError("Frozen bundle artifact hash changed")
    normalize_profile(binding["profile"])
    return manifest


class SlurmScheduler:
    """Local Slurm CLI adapter with fixed argv, bounded output and clean env."""
    def __init__(self, *, command_directory=None, timeout=15, credential_names=()):
        self.timeout = _integer(timeout, 1, 60, "Scheduler timeout")
        self.credential_names = tuple(credential_names)
        for name in self.credential_names:
            if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,126}(?:_KEY|_TOKEN|_SECRET)", name):
                raise ValueError("Invalid selected provider credential environment name")
        self.commands = {}
        for name in ("sbatch", "squeue", "sacct", "scancel"):
            value = str(Path(command_directory) / name) if command_directory else shutil.which(name)
            if not value or not Path(value).is_absolute() or not Path(value).is_file():
                raise ValueError("Required local Slurm commands are unavailable")
            self.commands[name] = value

    def _run(self, name, *args):
        # No key-bearing environment or provider response is forwarded/logged.
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
        if name == "sbatch":
            for credential_name in self.credential_names:
                if credential_name not in os.environ:
                    raise ValueError("Selected institutional credential environment is missing")
                env[credential_name] = os.environ[credential_name]
        import resource
        def output_bound():
            resource.setrlimit(resource.RLIMIT_FSIZE, (65_536, 65_536))
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([self.commands[name], *args], env=env,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                start_new_session=True, preexec_fn=output_bound)
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise RuntimeError("Scheduler outcome is uncertain after timeout") from None
            if process.returncode or output.tell() > 65_536:
                raise RuntimeError("Scheduler returned an unsuccessful or oversized response")
            output.seek(0)
            return output.read(65_537).decode("ascii", "replace").strip()

    def submit(self, script_path, job_name):
        value = self._run("sbatch", "--parsable", "--job-name=" + job_name, str(script_path))
        value = value.split(";", 1)[0]
        if not SLURM_ID.fullmatch(value):
            raise RuntimeError("Scheduler submission returned no usable job identifier")
        return value

    def status(self, job_id):
        if not isinstance(job_id, str) or not SLURM_ID.fullmatch(job_id):
            raise ValueError("Invalid scheduler job identifier")
        output = self._run("squeue", "--noheader", "--jobs=" + job_id, "--format=%T")
        if not output:
            output = self._run("sacct", "--noheader", "--parsable2", "--jobs=" + job_id, "--format=State")
        state = output.splitlines()[0].split("|", 1)[0].split("+", 1)[0].split(" ", 1)[0].lower() if output else "unknown"
        return {"state": state if state in ACTIVE | TERMINAL else "unknown"}

    def cancel(self, job_id):
        if not isinstance(job_id, str) or not SLURM_ID.fullmatch(job_id):
            raise ValueError("Invalid scheduler job identifier")
        self._run("scancel", job_id)


def make_script(profile, bundle, submission_id, *, credential_names=()):
    if not JOB_ID.fullmatch(submission_id):
        raise ValueError("Invalid Quarry cluster job identifier")
    bundle = Path(bundle).resolve()
    for path in (str(bundle), profile["runtime"]["python_executable"]):
        _text(path, "Cluster path", 4000)
    # Noninteractive, non-login Bash with no inherited BASH_ENV/startup
    # controls. Multiple shebang options are not portable on Linux kernels.
    lines = ["#!/bin/bash", "# Generated by Quarry from a reviewed operator profile.",
        "#SBATCH --nodes=1", "#SBATCH --ntasks=1", "#SBATCH --account=" + profile["account"],
        "#SBATCH --partition=" + profile["partition"],
        "#SBATCH --cpus-per-task=" + str(profile["cpus"]), "#SBATCH --mem=" + str(profile["memory_gb"]) + "G",
        "#SBATCH --time=" + str(math.ceil(profile["walltime_seconds"] / 60)),
        "#SBATCH --signal=B:USR1@" + str(profile["shutdown_grace_seconds"]),
        "#SBATCH --no-requeue", "#SBATCH --export=" + (",".join(credential_names) if credential_names else "NIL"),
        "#SBATCH --output=/dev/null", "#SBATCH --error=/dev/null"]
    if profile["qos"]:
        lines.append("#SBATCH --qos=" + profile["qos"])
    if profile["gpus"]:
        lines.append("#SBATCH --gpus=" + str(profile["gpus"]))
    # The fixed worker contains the entire action. No source/model text occurs
    # in the script; exec makes the Python process receive Slurm batch signals.
    lines += ["set -eu", "umask 077", "exec " + shlex.join([profile["runtime"]["python_executable"], "-m",
        "termfinder.cluster_worker", "--bundle", str(bundle), "--submission", submission_id, "--execute"])]
    return "\n".join(lines) + "\n"


class ClusterController:
    def __init__(self, project):
        self.project = project
        saved_root = project.store.read_setting("cluster_storage_root")
        self.root = Path(saved_root) if saved_root else project.path / "cluster"
        if not self.root.is_absolute() or self.root.is_symlink():
            raise ValueError("Unsafe cluster durable storage pointer")

    def _state(self):
        if self.project.store.read_setting("cluster_storage_root") and not (self.root / "state.json").is_file():
            raise ValueError("Configured durable cluster state is unavailable; collection cannot assume no allocation exists")
        state = read_json(self.root / "state.json", default={"version": VERSION, "jobs": []})
        if not isinstance(state, dict) or state.get("version") != VERSION or not isinstance(state.get("jobs"), list) or len(state["jobs"]) > 100:
            raise ValueError("Invalid cluster job state")
        seen = set()
        for job in state["jobs"]:
            if (not isinstance(job, dict) or not isinstance(job.get("job_id"), str) or not JOB_ID.fullmatch(job["job_id"])
                    or job["job_id"] in seen or job.get("state") not in ACTIVE | TERMINAL):
                raise ValueError("Invalid cluster job receipt")
            seen.add(job["job_id"])
            hours = job.get("reserved_gpu_hours")
            if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or not 0 <= hours <= 1_000_000:
                raise ValueError("Invalid resource reservation")
            scheduler_id = job.get("scheduler_job_id")
            if scheduler_id is not None and (not isinstance(scheduler_id, str) or not SLURM_ID.fullmatch(scheduler_id)):
                raise ValueError("Invalid saved scheduler identifier")
        return state

    def ensure_control_idle(self):
        """Read atomic receipts under the caller's originating-project lock.

        Submission/configuration admission also takes that project lock before
        dispatch. No scheduler or durable metadata lock is taken here, avoiding
        inversion with worker checkpoint/control operations.
        """
        if any(allocation_unresolved(job) for job in self._state()["jobs"]):
            raise ValueError("A cluster allocation is active or uncertain; local collection and plan changes are blocked")
        return True

    def configure(self, profile):
        profile = normalize_profile(profile, project=self.project)
        previous_root = self.root
        target_root = Path(profile["durable_root"]) / ("quarry-" + ident("study", str(self.project.path)))
        with metadata_lock(previous_root), self.project._lock():
            state = self._state()
            old = read_json(self.root / "profile.json")
            if state["jobs"] and profile != old:
                raise ValueError("Changing cluster resources after submission requires a separate study")
            if target_root != previous_root and target_root.exists():
                existing = read_json(target_root / "state.json", default={"jobs": []})
                if existing.get("jobs"):
                    raise ValueError("Existing durable storage has cluster submissions; reconnect the original study")
            self.root = target_root
            with (metadata_lock(self.root) if self.root != previous_root else nullcontext()):
                write_json(self.root / "profile.json", profile)
                if previous_root != target_root:
                    write_json(self.root / "state.json", {"version": VERSION, "jobs": []})
                elif profile != old:
                    # Source/recipe fingerprints deliberately exclude this
                    # operator file. Resource changes independently revoke
                    # any pending cluster review while keeping its immutable
                    # bundle available for inspection.
                    state.pop("review", None)
                    state["last_submission_decision"] = {"decision": "review_required",
                        "reason": "operator_cluster_profile_changed", "recorded_at": now()}
                    write_json(self.root / "state.json", state)
            self.project.store.setting("cluster_storage_root", str(self.root))
        return {"configured": True, "profile": profile, "profile_sha256": digest(profile), "launch_authorized": False}

    def prepare(self, review_id):
        with metadata_lock(self.root), self.project._lock():
            review, _ = _check_review_unlocked(self.project, review_id)
            _approval_unlocked(self.project, review)
            profile = normalize_profile(read_json(self.root / "profile.json"), project=self.project)
            state = self._state()
            if any(allocation_unresolved(job) for job in state["jobs"]):
                raise ValueError("Wait for or reconcile the existing cluster allocation")
            previous = state.get("review")
            if previous and previous["origin_fingerprint"] == project_fingerprint(self.project) and previous["profile_sha256"] == digest(profile):
                verify_bundle(previous["bundle"])
                return deepcopy(previous)
            if state["jobs"]:
                raise ValueError("Use resume with the frozen cluster review; a changed study requires a separate project")
            directory = self.root / "bundles" / ("bundle_" + uuid.uuid4().hex)
            directory.mkdir(parents=True, mode=0o700)
            self.project.store.backup(directory / "input.sqlite3")
            files = {"input.sqlite3": file_sha256(directory / "input.sqlite3")}
            frozen = Path(review["freeze"]["out"])
            version = review["freeze"]["version_id"]
            for source in sorted(frozen.iterdir()):
                if source.is_symlink() or not source.is_file():
                    raise ValueError("Human-review packet contains an unsafe artifact")
                relative = "human-review/" + version + "/" + source.name
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                files[relative] = file_sha256(target)
            fingerprint = project_fingerprint(self.project)
            binding = {"version": VERSION, "collection_review_id": review_id, "collection_binding": review["binding"],
                "profile": profile, "origin_fingerprint": fingerprint, "files": files,
                "scope": "one_node_reviewed_server_or_existing_endpoint_no_remote_transfer", "budget_accounting": "worst_case_allocation_reservations",
                "collector_package": package_fingerprint()}
            credential_names = tuple(sorted({p["credential_env"] for p in self.project.profile["providers"].values() if p["credential_env"]}))
            template = make_script(profile, directory, "cluster_job_" + "0" * 32, credential_names=credential_names)
            binding.update(script_template=template, script_template_sha256=digest(template))
            manifest = {"version": VERSION, "binding": binding, "binding_sha256": digest(binding),
                "cluster_review_id": ident("cluster_review", binding), "created_at": now()}
            write_json(directory / "manifest.json", manifest)
            prepared = {"cluster_review_id": manifest["cluster_review_id"], "collection_review_id": review_id,
                "bundle": str(directory), "binding_sha256": manifest["binding_sha256"], "origin_fingerprint": fingerprint,
                "profile_sha256": digest(profile), "resources": profile,
                "reservation_gpu_hours": profile["gpus"] * profile["walltime_seconds"] / 3600,
                "max_gpu_hours": profile["max_gpu_hours"], "max_submissions": profile["max_submissions"],
                "script_template": template, "script_template_sha256": digest(template),
                "requires_human_resource_approval": True, "ready": True}
            state["review"] = prepared
            write_json(self.root / "state.json", state)
            return deepcopy(prepared)

    def submit(self, cluster_review_id, *, approval_reference, human_approved=False,
               allow_execution=False, allow_paid=False, scheduler=None, _resume=False):
        if type(human_approved) is not bool or not human_approved:
            raise ValueError("Declare the researcher's explicit resource approval")
        if type(allow_execution) is not bool or not allow_execution:
            raise ValueError("Scheduler submission requires the trusted execution gate")
        if type(allow_paid) is not bool:
            raise ValueError("Transport authorization must be an explicit boolean")
        _text(approval_reference, "Human resource approval reference")
        _credential_free(approval_reference)
        with metadata_lock(self.root), self.project._lock():
            state = self._state()
            review = state.get("review") or {}
            if cluster_review_id != review.get("cluster_review_id"):
                raise ValueError("Cluster review is outdated")
            manifest = verify_bundle(review["bundle"])
            current_profile = normalize_profile(read_json(self.root / "profile.json"), project=self.project)
            if (digest(current_profile) != review["profile_sha256"]
                    or current_profile != manifest["binding"]["profile"]):
                raise ValueError("Operator cluster settings changed; prepare and approve the current resources")
            if project_fingerprint(self.project) != review["origin_fingerprint"]:
                raise ValueError("Origin study changed; preserve it and use a separate study")
            collection, _ = _check_review_unlocked(self.project, review["collection_review_id"])
            _approval_unlocked(self.project, collection)
            if any(p["adapter"] != "fake" for p in self.project.profile["providers"].values()) and not allow_paid:
                raise ValueError("Real extractor transport requires explicit authorization")
            if (any(p["adapter"] != "fake" for p in self.project.profile["providers"].values())
                    and self.project.profile.get("compute", {}).get("backend") not in {"institutional", "local"}):
                raise ValueError("Select an existing local or institutional extraction endpoint for GT collection")
            if any(allocation_unresolved(job) for job in state["jobs"]):
                raise ValueError("An active or uncertain allocation blocks another submission")
            if state["jobs"] and not _resume:
                raise ValueError("Use resume for another allocation of this frozen study")
            profile = manifest["binding"]["profile"]
            reservation = profile["gpus"] * profile["walltime_seconds"] / 3600
            reserved = sum(job["reserved_gpu_hours"] for job in state["jobs"] if job["state"] != "absent")
            if len(state["jobs"]) >= profile["max_submissions"] or reserved + reservation > profile["max_gpu_hours"] + 1e-9:
                state["last_submission_decision"] = {"decision": "blocked", "reason": "cluster_resource_budget_exhausted", "recorded_at": now()}
                write_json(self.root / "state.json", state)
                raise ValueError("Cumulative cluster submission or GPU-hour budget exhausted")
            parent = state["jobs"][-1] if state["jobs"] else None
            checkpoint = (parent.get("checkpoint") or parent.get("resume_checkpoint")) if parent else None
            if checkpoint:
                self._verify_checkpoint(checkpoint, Path(review["bundle"]))
            job_id = "cluster_job_" + uuid.uuid4().hex
            job = {"job_id": job_id, "cluster_review_id": cluster_review_id, "scheduler_job_id": None,
                "state": "submitting", "submitted_at": now(), "reserved_gpu_hours": reservation,
                "approval": {"human_approved": True, "approval_reference": approval_reference,
                    "binding_sha256": manifest["binding_sha256"], "identity_note": "Declared relay; not authenticated human identity"},
                "allow_paid": allow_paid, "resume_checkpoint": checkpoint,
                "previous_job_id": parent["job_id"] if parent else None, "checkpoint": None,
                "result": None, "cancel_requested": False}
            path = Path(review["bundle"]) / (job_id + ".sbatch")
            credential_names = tuple(sorted({p["credential_env"] for p in self.project.profile["providers"].values() if p["credential_env"]}))
            script = make_script(profile, review["bundle"], job_id, credential_names=credential_names)
            expected_script = manifest["binding"]["script_template"].replace("cluster_job_" + "0" * 32, job_id)
            if script != expected_script or digest(manifest["binding"]["script_template"]) != manifest["binding"]["script_template_sha256"]:
                raise ValueError("Generated scheduler script changed after resource review")
            path.write_text(script, encoding="utf-8")
            path.chmod(0o600)
            job["script_sha256"] = digest(script)
            state["jobs"].append(job)
            # Persist before any dispatch. A crash from here is uncertain and
            # cannot trigger an automatic second sbatch call.
            write_json(self.root / "state.json", state)
        # Do not hold the durable metadata lock across sbatch: an allocation
        # can start before sbatch returns and its worker must claim/checkpoint.
        # The persisted reservation excludes all concurrent submissions.
        try:
            scheduler_id = (scheduler or SlurmScheduler(credential_names=credential_names)).submit(path, job_id)
            if not isinstance(scheduler_id, str) or not SLURM_ID.fullmatch(scheduler_id):
                raise RuntimeError("Invalid scheduler receipt")
        except Exception:
            with metadata_lock(self.root):
                state = self._state()
                current = self._job(state, job_id)
                current.update(scheduler_submission_uncertain=True, reason="scheduler_submission_outcome_uncertain")
                if not current.get("started_at"):
                    current["state"] = "submission_unknown"
                write_json(self.root / "state.json", state)
                return deepcopy(current)
        with metadata_lock(self.root):
            state = self._state()
            current = self._job(state, job_id)
            current.update(scheduler_job_id=scheduler_id, scheduler_submission_uncertain=False)
            if current["state"] == "submitting":
                current.update(state="submitted", reason=None)
            write_json(self.root / "state.json", state)
            return deepcopy(current)

    def resume(self, cluster_review_id, **settings):
        return self.submit(cluster_review_id, _resume=True, **settings)

    def _job(self, state, job_id=None):
        if job_id is None and state["jobs"]:
            return state["jobs"][-1]
        for job in state["jobs"]:
            if job["job_id"] == job_id:
                return job
        raise ValueError("Unknown Quarry cluster job")

    def status(self, job_id=None, *, refresh=False, scheduler=None):
        if type(refresh) is not bool:
            raise ValueError("Refresh must be an explicit boolean")
        if refresh and scheduler is None:
            scheduler = SlurmScheduler()
        with metadata_lock(self.root):
            state = self._state()
            profile = read_json(self.root / "profile.json")
            reserved = sum(j["reserved_gpu_hours"] for j in state["jobs"] if j["state"] != "absent")
            remaining = max(0, profile["max_gpu_hours"] - reserved) if profile else None
            submissions_remaining = max(0, profile["max_submissions"] - len(state["jobs"])) if profile else None
            blocked = None
            if any(allocation_unresolved(j) for j in state["jobs"]):
                blocked = "active_or_uncertain_allocation"
            elif profile and (submissions_remaining == 0 or remaining + 1e-9 < profile["gpus"] * profile["walltime_seconds"] / 3600):
                blocked = "cluster_resource_budget_exhausted"
            budget = {"configured": bool(profile), "reserved_gpu_hours": reserved,
                "remaining_gpu_hours": remaining, "submissions_used": len(state["jobs"]),
                "submissions_remaining": submissions_remaining, "blocked_reason": blocked,
                "last_submission_decision": deepcopy(state.get("last_submission_decision"))}
            if not state["jobs"]:
                return {**budget, "review": state.get("review"), "jobs": []}
            job = self._job(state, job_id)
            if scheduler is not None and job["scheduler_job_id"] and job["state"] in ACTIVE:
                try:
                    observed = scheduler.status(job["scheduler_job_id"]).get("state", "unknown")
                except Exception:
                    observed = "unknown"
                job["scheduler_state"] = observed if observed in ACTIVE | TERMINAL else "unknown"
                if observed in TERMINAL:
                    job["state"] = observed
                elif job["state"] != "cancel_requested":
                    job["state"] = observed if observed in ACTIVE else "unknown"
                write_json(self.root / "state.json", state)
                if not any(allocation_unresolved(j) for j in state["jobs"]):
                    budget["blocked_reason"] = "cluster_resource_budget_exhausted" if profile and (
                        submissions_remaining == 0 or remaining + 1e-9 < profile["gpus"] * profile["walltime_seconds"] / 3600) else None
            return {**budget, "job": deepcopy(job), "review": deepcopy(state.get("review")), "jobs": deepcopy(state["jobs"]),
                "accounting_note": "Full allocation reservations retained conservatively; worker GPU-hours include owned server startup but exclude scheduler wait, cleanup and external server allocations, and are a lower bound"}

    def cancel(self, job_id=None, *, scheduler=None):
        with metadata_lock(self.root):
            state = self._state()
            job = self._job(state, job_id)
            if job["state"] in TERMINAL:
                return deepcopy(job)
            job.update(cancel_requested=True, state="cancel_requested")
            write_json(self.root / "state.json", state)
            if job["scheduler_job_id"]:
                try:
                    (scheduler or SlurmScheduler()).cancel(job["scheduler_job_id"])
                    job["cancel_dispatch"] = "accepted"
                except Exception:
                    job["cancel_dispatch"] = "uncertain"
            else:
                job["cancel_dispatch"] = "no_scheduler_identifier_reconcile_submission"
            write_json(self.root / "state.json", state)
            return deepcopy(job)

    def resolve_submission(self, job_id, *, scheduler_job_id=None, verified_absent=False,
                           reconciliation_reference, scheduler=None):
        _text(reconciliation_reference, "Scheduler reconciliation reference")
        _credential_free(reconciliation_reference)
        if type(verified_absent) is not bool or bool(scheduler_job_id) == verified_absent:
            raise ValueError("Identify the scheduler job or explicitly verify its absence")
        if scheduler_job_id is not None and (not isinstance(scheduler_job_id, str) or not SLURM_ID.fullmatch(scheduler_job_id)):
            raise ValueError("Invalid scheduler job identifier")
        with metadata_lock(self.root):
            state = self._state()
            job = self._job(state, job_id)
            if job["state"] not in {"submitting", "submission_unknown", "cancel_requested", "unknown"} and not job.get("scheduler_submission_uncertain"):
                raise ValueError("Only uncertain allocations need reconciliation")
            if scheduler_job_id:
                if scheduler is not None:
                    report = scheduler.status(scheduler_job_id)
                    if report.get("state") == "absent":
                        raise ValueError("The identified scheduler job is absent")
                job.update(scheduler_job_id=scheduler_job_id, scheduler_submission_uncertain=False)
                if not job.get("started_at"):
                    job["state"] = "submitted"
            else:
                if job.get("started_at"):
                    raise ValueError("A started worker proves an allocation existed; identify its scheduler job")
                job.update(state="absent", scheduler_submission_uncertain=False, reason="researcher_verified_no_allocation")
            job["reconciliation"] = {"reference": reconciliation_reference, "recorded_at": now(),
                "identity_note": "Declared reconciliation; operator must check Slurm history by Quarry job name"}
            write_json(self.root / "state.json", state)
            return deepcopy(job)

    @staticmethod
    def _verify_checkpoint(checkpoint, bundle):
        relative = checkpoint.get("file")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Unsafe checkpoint path")
        path = bundle / relative
        current = bundle
        for component in Path(relative).parts:
            current = current / component
            if current.is_symlink():
                raise ValueError("Checkpoint paths cannot contain symlinks")
        if file_sha256(path) != checkpoint.get("sha256"):
            raise ValueError("Checkpoint hash changed")
        return path

    def import_result(self, job_id=None):
        """Transactional restore only into the unchanged originating inventory."""
        with metadata_lock(self.root), self.project._lock():
            state = self._state()
            job = self._job(state, job_id)
            if job.get("imported_at"):
                return {"imported": True, "job_id": job["job_id"], "already_imported": True}
            if job["state"] in ACTIVE or not job.get("checkpoint"):
                raise ValueError("A stopped allocation with a verified checkpoint is required")
            review = state["review"]
            bundle = Path(review["bundle"])
            verify_bundle(bundle)
            backup = self._verify_checkpoint(job["checkpoint"], bundle)
            current_fingerprint = project_fingerprint(self.project)
            receipt = self.project.store.read_setting("cluster_import_receipt") or {}
            recovered = (receipt.get("job_id") == job["job_id"]
                and receipt.get("checkpoint_sha256") == job["checkpoint"]["sha256"]
                and receipt.get("previous_origin_fingerprint") == review["origin_fingerprint"]
                and receipt.get("imported_fingerprint") == current_fingerprint)
            if current_fingerprint != review["origin_fingerprint"] and not recovered:
                raise ValueError("Origin study changed; no records or annotations were overwritten")
            if recovered:
                job["imported_at"] = receipt["imported_at"]
                review["origin_fingerprint"] = current_fingerprint
                write_json(self.root / "state.json", state)
                return {"imported": True, "job_id": job["job_id"], "recovered_committed_import": True}
            with sqlite3.connect("file:" + quote(str(backup), safe="/") + "?mode=ro&immutable=1", uri=True) as source:
                if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Checkpoint database integrity failed")
                with self.project.store.connection() as target:
                    for table in ("settings", *TABLES, "run_jobs"):
                        target.execute(f"DELETE FROM {table}")
                        columns = 2 if table != "run_jobs" else 3
                        cursor = source.execute(f"SELECT * FROM {table}")
                        while rows := cursor.fetchmany(64):
                            target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in range(columns))})", rows)
                    self.project.store.setting("cluster_accounting", {"version": VERSION,
                        "jobs": deepcopy(state["jobs"]), "reserved_gpu_hours": sum(j["reserved_gpu_hours"] for j in state["jobs"] if j["state"] != "absent"),
                        "max_gpu_hours": review["max_gpu_hours"], "allocation_cost_usd": None,
                        "allocation_cost_reason": "institutional_rates_and_server_allocations_not_metered"}, target)
                    imported_at = now()
                    self.project.store.setting("cluster_import_receipt", {"job_id": job["job_id"],
                        "checkpoint_sha256": job["checkpoint"]["sha256"], "previous_origin_fingerprint": review["origin_fingerprint"],
                        "imported_fingerprint": project_fingerprint(self.project), "imported_at": imported_at}, target)
            job["imported_at"] = imported_at
            review["origin_fingerprint"] = project_fingerprint(self.project)
            write_json(self.root / "state.json", state)
            return {"imported": True, "job_id": job["job_id"], "checkpoint": deepcopy(job["checkpoint"]),
                "status": status_summary(self.project.status()), "inventory_note": "Grounded inventory retained; meanings and completeness require source-level evaluation"}
