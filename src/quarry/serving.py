"""Finite foreground vLLM lifecycle for one reviewed, pre-staged local model.

No downloads, shell commands, remote model code or credential inheritance.
Production use belongs inside the explicitly approved single-node worker.
Python hooks are trusted offline/site integrations, never JSON configuration.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .store import now

VERSION = "quarry-vllm-lifecycle-v1"
FIELDS = {"adapter", "model_alias", "local_model_dir", "artifact_files", "port",
          "startup_timeout_seconds", "max_model_len", "tensor_parallel_size",
          "gpu_memory_utilization", "package_version"}
FORBIDDEN_SUFFIXES = {".py", ".pyc", ".pyo", ".so", ".dylib", ".dll", ".sh", ".bash",
                      ".zsh", ".exe", ".pkl", ".pickle", ".pt", ".pth", ".bin"}
FORBIDDEN_PARTS = {".ssh", ".aws", ".codex", ".config", ".git", "keychains", "credentials"}
VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){2}(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?(?:\+[A-Za-z0-9.]+)?\Z")


class ServingError(RuntimeError):
    """Fixed safe categories; no provider output, artifact content or paths."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("Server integer resource limit is invalid")


def _no_symlinks(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Model location must be absolute")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError("Model locations cannot traverse symlinks")


def _inventory(directory):
    files, pending, entries_seen = {}, [directory], 0
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > 10000:
                    raise ValueError("Model inventory exceeds the finite entry limit")
                path = Path(entry.path)
                relative = path.relative_to(directory).as_posix()
                if entry.is_symlink() or entry.name.lower() in FORBIDDEN_PARTS:
                    raise ValueError("Model inventory contains unsafe links or paths")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    if path.suffix.lower() in FORBIDDEN_SUFFIXES or entry.stat(follow_symlinks=False).st_mode & 0o111:
                        raise ValueError("Model inventory contains executable code or unsupported weight formats")
                    files[relative] = path
                    if len(files) > 2000:
                        raise ValueError("Model inventory exceeds 2000 files")
                else:
                    raise ValueError("Model artifacts must be regular data files")
    return files


def normalize_server(config, extraction_profile, resources):
    """Validate data-only server settings; shape-only verification permits None.

    A full extractor profile is mandatory before execution. It must contain
    exactly one model and one loopback provider matching this owned server.
    """
    if not isinstance(config, dict) or set(config) != FIELDS or config.get("adapter") != "vllm":
        raise ValueError("Unsupported or missing local serving fields")
    value = deepcopy(config)
    from .agent_setup import _credential_free
    _credential_free(value)
    alias = value["model_alias"]
    if not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", alias):
        raise ValueError("Server requires a configured model alias")
    for field, lower, upper in (("port", 1024, 65535), ("startup_timeout_seconds", 1, 900),
            ("max_model_len", 128, 10000000), ("tensor_parallel_size", 1, 64)):
        _integer(value[field], lower, upper)
    if (not isinstance(resources, dict) or type(resources.get("gpus")) is not int
            or value["tensor_parallel_size"] > resources["gpus"]):
        raise ValueError("Server tensor parallelism exceeds the approved GPU allocation")
    utilization = value["gpu_memory_utilization"]
    if type(utilization) not in (int, float) or not math.isfinite(utilization) or not 0.05 <= utilization <= 0.95:
        raise ValueError("Server GPU memory utilization must be finite and bounded")
    version = value["package_version"]
    if not isinstance(version, str) or len(version) > 64 or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("Declare an exact installed vLLM package version")
    location = value["local_model_dir"]
    if (not isinstance(location, str) or len(location) > 4000 or any(ord(c) < 32 for c in location)
            or ".." in Path(location).parts):
        raise ValueError("Choose a specific pre-staged model directory")
    directory = Path(location)
    _no_symlinks(directory)
    if (not directory.is_dir() or directory in {Path("/"), Path.home(), Path.home().parent}
            or any(p.lower() in FORBIDDEN_PARTS for p in directory.parts)):
        raise ValueError("Choose a specific reviewed model directory, outside credential paths")
    value["local_model_dir"] = str(directory)
    artifacts = value["artifact_files"]
    if not isinstance(artifacts, dict) or not 1 <= len(artifacts) <= 2000:
        raise ValueError("A complete bounded artifact SHA256 inventory is required")
    for relative, expected in artifacts.items():
        if (not isinstance(relative, str) or not relative or len(relative) > 1000
                or any(ord(c) < 32 for c in relative) or "\\" in relative
                or Path(relative).is_absolute() or ".." in Path(relative).parts
                or Path(relative).as_posix() != relative
                or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)):
            raise ValueError("Model artifact inventory contains an unsafe location or hash")
    present = _inventory(directory)
    if set(present) != set(artifacts) or "config.json" not in present or not any(p.endswith(".safetensors") for p in present):
        raise ValueError("Inventory must cover every data file, model config and SafeTensors weights")
    if extraction_profile is not None:
        from .config import load_profile
        profile = load_profile(extraction_profile)
        if len(profile["models"]) != 1 or set(profile["models"]) != {alias}:
            raise ValueError("Owned serving currently supports exactly one configured model")
        model = profile["models"][alias]
        provider = profile["providers"][model["provider"]]
        if provider["adapter"] != "openai" or provider.get("auth") != "none" or provider["credential_env"] is not None:
            raise ValueError("Owned serving requires a credential-free OpenAI-compatible loopback provider")
        endpoint = urlsplit(provider["base_url"])
        if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.port != value["port"] or endpoint.path.rstrip("/") != "/v1":
            raise ValueError("Extractor endpoint must match the owned loopback server port and /v1 path")
        if value["max_model_len"] < model.get("context_limit_tokens", model["input_token_ceiling"]):
            raise ValueError("Server context must cover the reviewed extractor context limit")
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


class VLLMServer:
    def __init__(self, profile, extraction_profile, *, process_factory=None, readiness=None, cancelled=None):
        if (process_factory is not None and not callable(process_factory) or readiness is not None and not callable(readiness)
                or cancelled is not None and not callable(cancelled)):
            raise ValueError("Serving hooks must be trusted Python callables")
        self.profile, self.extractor = deepcopy(profile), deepcopy(extraction_profile)
        self.config = normalize_server(profile["server"], extraction_profile, profile)
        if extraction_profile is None:
            raise ValueError("A fully validated extraction profile is required to start a server")
        self.factory, self.readiness = process_factory, readiness
        self.cancelled = cancelled
        self.process = self.receipt = self.work = None
        self._closed = False

    def _environment(self):
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1",
            "TOKENIZERS_PARALLELISM": "false", "VLLM_PLUGINS": "",
            "VLLM_LOGGING_LEVEL": "WARNING", "VLLM_HOST_IP": "127.0.0.1"}
        devices = os.environ.get("CUDA_VISIBLE_DEVICES")
        if devices is not None:
            tokens = devices.split(",")
            device_pattern = r"(?:[0-9]{1,5}|GPU-[0-9A-Fa-f-]{8,80}|MIG-[0-9A-Fa-f-]{8,80}|MIG-GPU-[0-9A-Fa-f-]{8,80}/[0-9]{1,4}/[0-9]{1,4})"
            if (len(devices) > 4096 or len(tokens) > self.profile["gpus"] or len(tokens) < self.config["tensor_parallel_size"]
                    or len(set(tokens)) != len(tokens) or any(not re.fullmatch(device_pattern, item) for item in tokens)):
                raise ServingError("invalid_scheduler_cuda_visibility")
            environment["CUDA_VISIBLE_DEVICES"] = devices
        elif self.factory is None:
            raise ServingError("scheduler_cuda_visibility_unavailable")
        return environment

    def _verify_artifacts(self, deadline):
        directory = Path(self.config["local_model_dir"])
        _no_symlinks(directory)
        present = _inventory(directory)
        if set(present) != set(self.config["artifact_files"]):
            raise ServingError("model_artifact_integrity_failed")
        for relative, path in present.items():
            self._check_cancelled()
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > 16_000_000_000:
                    raise ServingError("model_artifact_integrity_failed")
                checksum = hashlib.sha256()
                while block := stream.read(1_048_576):
                    self._check_cancelled()
                    if time.monotonic() >= deadline:
                        raise ServingError("model_server_startup_timeout")
                    checksum.update(block)
                after = os.fstat(stream.fileno())
                identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                if identity(before) != identity(after) or checksum.hexdigest() != self.config["artifact_files"][relative]:
                    raise ServingError("model_artifact_integrity_failed")

    def _check_cancelled(self):
        if self.cancelled is not None and self.cancelled():
            raise ServingError("model_server_startup_cancelled")

    def _package_version(self, environment, deadline):
        self._check_cancelled()
        if time.monotonic() >= deadline:
            raise ServingError("model_server_startup_timeout")
        timeout = max(0.01, min(10, deadline - time.monotonic()))
        code = "from importlib.metadata import version; value=version('vllm'); print(value if len(value)<=128 else 'invalid')"
        try:
            answer = subprocess.run([self.profile["runtime"]["python_executable"], "-I", "-c", code],
                env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=timeout, check=False)
            actual = answer.stdout.decode("ascii").strip() if len(answer.stdout) <= 256 and answer.returncode == 0 else None
        except Exception:
            raise ServingError("vllm_package_version_unavailable") from None
        if actual != self.config["package_version"]:
            raise ServingError("vllm_package_version_mismatch")

    def _ready(self, endpoint):
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        deadline = getattr(self, "_startup_deadline", time.monotonic() + 0.5)
        try:
            with opener.open(Request(endpoint, headers={"Accept": "application/json"}),
                             timeout=max(0.01, min(0.5, deadline - time.monotonic()))) as response:
                blocks, size = [], 0
                while time.monotonic() < deadline:
                    self._check_cancelled()
                    block = response.read1(min(4096, 65537 - size))
                    if not block: break
                    size += len(block)
                    if size > 65536: return False
                    blocks.append(block)
                else:
                    return False
                value = json.loads(b"".join(blocks))
                expected = self.extractor["models"][self.config["model_alias"]]["model"]
                return isinstance(value, dict) and isinstance(value.get("data"), list) and any(
                    isinstance(item, dict) and item.get("id") == expected for item in value["data"])
        except Exception:
            return False

    def start(self):
        if self._closed:
            raise ServingError("model_server_already_stopped")
        if self.process is not None:
            if self.process.poll() is None and self.receipt is not None:
                return deepcopy(self.receipt)
            raise ServingError("model_server_already_stopped")
        deadline = time.monotonic() + self.config["startup_timeout_seconds"]
        self._startup_deadline = deadline
        try:
            self._check_cancelled()
            environment = self._environment()
            self._verify_artifacts(deadline)
            self._package_version(environment, deadline)
            self._check_cancelled()
            if time.monotonic() >= deadline:
                raise ServingError("model_server_startup_timeout")
            if self.factory is None:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind(("127.0.0.1", self.config["port"]))
            self.work = tempfile.mkdtemp(prefix="quarry-vllm-")
            os.chmod(self.work, 0o700)
            for name, relative in (("HF_HOME", "hf"), ("HF_HUB_CACHE", "hf/hub"),
                    ("XDG_CACHE_HOME", "cache"), ("VLLM_CACHE_ROOT", "vllm"),
                    ("XDG_CONFIG_HOME", "config"), ("VLLM_CONFIG_ROOT", "config/vllm")):
                environment[name] = str(Path(self.work) / relative)
            model = self.extractor["models"][self.config["model_alias"]]
            argv = [self.profile["runtime"]["python_executable"], "-m", "vllm.entrypoints.openai.api_server",
                "--model", self.config["local_model_dir"], "--served-model-name", model["model"],
                "--host", "127.0.0.1", "--port", str(self.config["port"]),
                "--max-model-len", str(self.config["max_model_len"]),
                "--tensor-parallel-size", str(self.config["tensor_parallel_size"]),
                "--distributed-executor-backend", "mp",
                "--gpu-memory-utilization", str(self.config["gpu_memory_utilization"]),
                "--load-format", "safetensors", "--generation-config", "vllm",
                "--enable-prefix-caching"]
            self.process = (self.factory or subprocess.Popen)(argv, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, cwd=self.work)
            endpoint = "http://127.0.0.1:" + str(self.config["port"]) + "/v1/models"
            while time.monotonic() < deadline:
                self._check_cancelled()
                if self.process.poll() is not None:
                    raise ServingError("model_server_exited_before_ready")
                if (self.readiness or self._ready)(endpoint):
                    self.receipt = {"version": VERSION, "adapter": "vllm", "model_alias": self.config["model_alias"],
                        "served_model_name": model["model"], "package_version": self.config["package_version"],
                        "model_artifact_files": deepcopy(self.config["artifact_files"]), "ready_at": now(),
                        "model_files_verified_before_launch": True, "checkpoint_remote_attested": False,
                        "integrity_note": "Hashes checked before launch; operator must keep pre-staged artifacts immutable. Readiness proves served-model availability, not extraction quality.",
                        "context_limit_tokens": self.config["max_model_len"], "tensor_parallel_size": self.config["tensor_parallel_size"],
                        "prefix_caching": True, "startup_seconds": round(self.config["startup_timeout_seconds"] - max(0, deadline - time.monotonic()), 6),
                        "endpoint": endpoint.rsplit("/models", 1)[0], "downloads": "disabled", "remote_model_code": "disabled",
                        "plugin_autoload": "disabled", "api_host": "127.0.0.1",
                        "load_format": "safetensors", "generation_config": "vllm", "distributed_executor_backend": "mp",
                        "network_isolation_note": "Loopback API and disabled downloads are not an OS network sandbox; site isolation must protect vLLM and PyTorch internal communication ports."}
                    return deepcopy(self.receipt)
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            raise ServingError("model_server_startup_timeout")
        except ServingError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ServingError("model_server_startup_failed") from None
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        process = self.process
        self.process = None
        if process is not None and (self.factory is None or process.poll() is None):
            try:
                if self.factory is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    if self.factory is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass
            finally:
                if self.factory is None:
                    # GPU engine subprocesses can survive a frontend failure.
                    # This session was created exclusively for this server.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
        if self.work is not None:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None
