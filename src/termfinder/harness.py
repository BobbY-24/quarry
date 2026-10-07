"""Explicit project-local setup for a researcher's existing agent harness.

This module prepares inert skill/configuration files. It does not start a client,
change trust settings, install packages, use credentials, or collect anything.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tomllib
import uuid

MAX_FILE_BYTES = 1_048_576
MAX_SKILL_FILES = 100
SKILL_NAME = "v6-collect-research"
SERVER_NAME = "v6"


class HarnessError(ValueError):
    """Fixed diagnostics never include existing configuration contents."""


def _chosen_root(value, *, existing=False):
    if not isinstance(value, (str, os.PathLike)):
        raise HarnessError("Choose a specific workspace or studies directory.")
    path = Path(value).expanduser().absolute()
    if ".." in path.parts or any(part.startswith(".") for part in path.parts[1:]):
        raise HarnessError("Workspace and studies paths cannot be hidden or contain traversal.")
    home = Path.home().absolute()
    broad = {Path("/"), home, home.parent, Path("/Users"), Path("/home"),
             Path("/tmp"), Path("/private/tmp"), Path("/private"), Path("/var")}
    if path in broad or any(part.lower() in {"keychains", "credentials"} for part in path.parts):
        raise HarnessError("Choose a specific project directory, not a home, filesystem, or credential root.")
    if existing:
        fd = _directory(path)
        os.close(fd)
    else:
        fd = _directory(path.parent)
        try:
            try:
                info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return path
            if not stat.S_ISDIR(info.st_mode):
                raise HarnessError("The studies path must be a nonsymlink directory.")
        finally:
            os.close(fd)
    return path


def _directory(path):
    """Open every ancestor without following links; callers own the result."""
    # Search-only ancestors do not read directory inventories outside the chosen
    # workspace. Some macOS Python builds omit SDK symbols; Darwin's ABI defines
    # O_SEARCH = O_EXEC (0x40000000) | O_DIRECTORY. Do not fall back to a readable
    # ancestor descriptor just because CPython did not export the symbol.
    # https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/fcntl.h
    if sys.platform == "darwin":
        search = getattr(os, "O_SEARCH", getattr(os, "O_EXEC", 0x40000000) | os.O_DIRECTORY)
    else:
        search = getattr(os, "O_SEARCH", getattr(os, "O_PATH", os.O_RDONLY))
    fd = os.open("/", search | os.O_DIRECTORY)
    try:
        parts = Path(path).parts[1:]
        for index, part in enumerate(parts):
            access = os.O_RDONLY if index == len(parts) - 1 else search
            child = os.open(part, access | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except OSError:
        os.close(fd)
        raise HarnessError("Directory paths must exist and have no symbolic-link ancestors.") from None


def _read_at(fd, name):
    try:
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise HarnessError("A configuration or skill path is unsafe or unreadable.") from None
    try:
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise HarnessError("Configuration and skill files must be regular files within the size bound.")
        content = bytearray()
        while True:
            chunk = os.read(source, min(65_536, MAX_FILE_BYTES + 1 - len(content)))
            if not chunk:
                return bytes(content)
            content.extend(chunk)
            if len(content) > MAX_FILE_BYTES:
                raise HarnessError("Configuration or skill file exceeds the size bound.")
    finally:
        os.close(source)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise HarnessError("The host configuration contains duplicate fields.")
        value[key] = item
    return value


def _credential_free(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {"apikey", "password", "secret", "token", "accesstoken", "authtoken",
                              "authorization", "credential", "credentials", "httpheaders", "headers"} \
                    or normalized.endswith(("apikey", "password", "accesstoken", "authtoken")) \
                    or normalized in {"env", "environment"} and isinstance(item, dict) and item:
                raise HarnessError("This host configuration may contain inline credentials. Use a fresh workspace or configure V6 manually without copying credentials.")
            _credential_free(item)
    elif isinstance(value, list):
        for item in value:
            _credential_free(item)
    elif isinstance(value, str) and re.search(
            r"(?:\bsk-[A-Za-z0-9_-]{20,}|\bAIza[A-Za-z0-9_-]{25,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|https?://[^/@\s]+:[^/@\s]+@)", value):
        raise HarnessError("This host configuration may contain inline credentials. Use a fresh workspace or configure V6 manually without copying credentials.")


def _configuration(host, original, entry):
    try:
        text = original.decode("utf-8") if original is not None else ""
        _credential_free(text)
        if re.search(r"(?im)\b(?:api[_-]?key|access[_-]?token|password|authorization)\s*[:=]", text):
            raise HarnessError("This host configuration may contain inline credentials. Use a fresh workspace or configure V6 manually without copying credentials.")
        if host == "codex":
            parsed = tomllib.loads(text)
            _credential_free(parsed)
            servers = parsed.get("mcp_servers", {})
        else:
            parsed = json.loads(text, object_pairs_hook=_unique,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())) if text else {}
            _credential_free(parsed)
            if not isinstance(parsed, dict):
                raise ValueError()
            servers = parsed.get("mcpServers", {})
        if not isinstance(parsed, dict) or not isinstance(servers, dict):
            raise ValueError()
        expected = entry if host != "codex" else {k: v for k, v in entry.items() if k != "type"}
        if SERVER_NAME in servers:
            if servers[SERVER_NAME] != expected:
                raise HarnessError("The existing v6 MCP entry differs. Choose a fresh workspace or explicitly review and remove only that entry before reconnecting; the installer will not replace it.")
            return original
        if host == "codex":
            block = ("\n\n[mcp_servers.v6]\ncommand = " + json.dumps(expected["command"], ensure_ascii=False)
                     + "\nargs = " + json.dumps(expected["args"], ensure_ascii=False) + "\n")
            result = text + block
            # TOML inline tables cannot always be safely extended. Fail before writes.
            if tomllib.loads(result).get("mcp_servers", {}).get(SERVER_NAME) != expected:
                raise ValueError()
        else:
            parsed.setdefault("mcpServers", {})[SERVER_NAME] = expected
            result = json.dumps(parsed, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        return result.encode("utf-8")
    except HarnessError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise HarnessError("The existing host configuration cannot be safely merged. Review its structure or choose a fresh workspace; its contents were not changed.") from None


def _launcher():
    interpreter = Path(sys.executable).absolute()
    script = interpreter.parent / "termfinder-mcp"
    try:
        info = script.lstat()
    except OSError:
        info = None
    if info and stat.S_ISREG(info.st_mode) and os.access(script, os.X_OK):
        return str(script), []
    # Preserve the venv path: resolving its interpreter link can lose site-packages.
    if not interpreter.is_file():
        raise HarnessError("The installed Python entry point is unavailable.")
    return str(interpreter), ["-m", "termfinder.mcp_server"]


def _assets():
    root = Path(__file__).with_name("agent_skill")
    fd = _directory(root.absolute())
    try:
        assets = _tree(fd)
    finally:
        os.close(fd)
    if "SKILL.md" not in assets:
        raise HarnessError("The installed V6 skill is unavailable.")
    return assets


def _tree(fd, prefix="", found=None, count=None):
    found = {} if found is None else found
    count = [0] if count is None else count
    if prefix.count("/") > 10:
        raise HarnessError("The skill folder exceeds the finite depth bound.")
    for name in sorted(os.listdir(fd)):
        count[0] += 1
        if count[0] > 1000:
            raise HarnessError("The skill folder exceeds the finite entry bound.")
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        relative = prefix + name
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                _tree(child, relative + "/", found, count)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            if len(found) >= MAX_SKILL_FILES:
                raise HarnessError("The skill folder exceeds the finite file bound.")
            found[relative] = _read_at(fd, name)
        else:
            raise HarnessError("Skill folders cannot contain links or special files.")
    return found


class _Transaction:
    """No-clobber new files and checked, atomic targeted configuration updates."""
    def __init__(self, workspace, workspace_fd):
        self.workspace = workspace
        self.workspace_fd = workspace_fd
        self.created_files = []
        self.created_dirs = []
        self.replaced = []
        self.opened = []

    def directory(self, path):
        if not path.is_relative_to(self.workspace):
            fd = _directory(path)
            self.opened.append(fd)
            return fd
        fd = os.dup(self.workspace_fd)
        try:
            for part in path.relative_to(self.workspace).parts:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    self.created_dirs.append((os.dup(fd), part))
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            self.opened.append(fd)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def write(self, path, original, content):
        parent = self.directory(path.parent)
        if _read_at(parent, path.name) != original:
            raise HarnessError("An installation target changed during setup. No conflicting file will be overwritten.")
        if original == content:
            return
        temporary = ".v6-connect-" + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if original is None:
                os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                self.created_files.append((os.dup(parent), path.name, content))
            else:
                if _read_at(parent, path.name) != original:
                    raise HarnessError("The host configuration changed during setup. Retry only after inspecting the concurrent change.")
                os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                self.replaced.append((os.dup(parent), path.name, original, content))
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass

    def finish(self, rollback=False):
        incomplete = False
        if rollback:
            for fd, name, original, content in reversed(self.replaced):
                try:
                    if _read_at(fd, name) != content:
                        incomplete = True
                        continue
                    temporary = ".v6-rollback-" + uuid.uuid4().hex
                    target = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    with os.fdopen(target, "wb") as stream:
                        stream.write(original)
                    os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
                except (HarnessError, OSError):
                    incomplete = True
            for fd, name, content in reversed(self.created_files):
                try:
                    if _read_at(fd, name) == content:
                        os.unlink(name, dir_fd=fd)
                    else:
                        incomplete = True
                except (HarnessError, OSError):
                    incomplete = True
            for fd, name in reversed(self.created_dirs):
                try:
                    os.rmdir(name, dir_fd=fd)
                except OSError:
                    incomplete = True
        for item in self.replaced + self.created_files + self.created_dirs:
            os.close(item[0])
        for fd in self.opened:
            os.close(fd)
        if incomplete:
            raise HarnessError("Setup stopped; concurrent changes prevented complete rollback. Inspect only the V6 skill and server entry before retrying.")


def _existing(path):
    try:
        fd = _directory(path.parent)
    except HarnessError:
        # Missing internal host folders are valid; links or non-directories are not.
        for parent in [path.parent, *path.parent.parents]:
            if parent.is_symlink() or parent.exists() and not parent.is_dir():
                raise HarnessError("Installation paths cannot contain symbolic links or special files.") from None
        return None
    try:
        return _read_at(fd, path.name)
    finally:
        os.close(fd)


def connect_harness(host, workspace, studies=None, *, allow_paid=False, allow_cluster=False,
                    cluster_storage_roots=()):
    """Prepare one local harness workspace from explicit researcher-chosen paths.

    Existing matching V6 files are idempotent. Different V6 definitions require
    an explicit migration; unrelated settings are retained and never echoed.
    """
    if host not in {"codex", "claude", "generic"} or not isinstance(allow_paid, bool) or not isinstance(allow_cluster, bool):
        raise HarnessError("Choose codex, claude, or generic and a Boolean paid launch gate.")
    workspace = _chosen_root(workspace, existing=True)
    studies = _chosen_root(studies if studies is not None else workspace / "v6-studies")
    if not studies.exists() and not studies.is_relative_to(workspace):
        raise HarnessError("A new studies root must be inside the chosen workspace; create any separate root explicitly first.")
    command, prefix = _launcher()
    roots = [_chosen_root(root, existing=True) for root in cluster_storage_roots]
    args = prefix + ["--workspace", str(studies)] + (["--allow-paid"] if allow_paid else []) + (["--allow-cluster"] if allow_cluster else [])
    args += [part for root in roots for part in ("--cluster-storage-root", str(root))]
    entry = {"type": "stdio", "command": command, "args": args}
    skill = workspace / ({"codex": ".agents/skills", "claude": ".claude/skills", "generic": ""}[host]) / SKILL_NAME
    config = workspace / {"codex": ".codex/config.toml", "claude": ".mcp.json", "generic": "v6-mcp.json"}[host]
    assets = _assets()
    try:
        fd = _directory(skill)
    except HarnessError:
        if skill.exists() or skill.is_symlink():
            raise HarnessError("The existing V6 skill folder is unsafe. Choose a fresh workspace or inspect that folder explicitly.") from None
        for parent in skill.parents:
            if parent.is_symlink() or parent.exists() and not parent.is_dir():
                raise HarnessError("Skill parents cannot contain symbolic links or special files.") from None
        existing_assets = {}
    else:
        try:
            existing_assets = _tree(fd)
        finally:
            os.close(fd)
        if existing_assets != assets:
            raise HarnessError("The existing V6 skill differs. Choose a fresh workspace or explicitly relocate that skill before reconnecting; it will not be overwritten.")
    original = _existing(config)
    content = _configuration(host, original, entry)
    changed = original != content or not existing_assets or not studies.exists()
    workspace_fd = _directory(workspace)
    lock = ".v6-connect.lock"
    try:
        try:
            lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=workspace_fd)
        except FileExistsError:
            raise HarnessError("A V6 setup lock already exists. Wait for the other setup, or inspect and remove a stale .v6-connect.lock before retrying.") from None
        os.close(lock_fd)
        transaction = _Transaction(workspace, workspace_fd)
        try:
            transaction.directory(studies)
            for relative, value in sorted(assets.items()):
                transaction.write(skill / relative, existing_assets.get(relative), value)
            transaction.write(config, original, content)
        except BaseException as error:
            transaction.finish(rollback=True)
            if isinstance(error, HarnessError):
                raise
            raise HarnessError("V6 setup failed; newly owned artifacts were rolled back. Existing configuration contents were not disclosed.") from None
        else:
            transaction.finish()
        finally:
            os.unlink(lock, dir_fd=workspace_fd)
    finally:
        os.close(workspace_fd)
    invocation = "$v6-collect-research" if host == "codex" else "/v6-collect-research" if host == "claude" else "the V6 research-collection skill"
    prompt = ("Use " + invocation + " to create a new study from my research question. Help me choose the collection unit, permitted sources, inclusion criteria, models and a finite budget. Present the complete collection plan before running, preserve exact source evidence, and deliver a reproducible dataset. Start with an offline rehearsal unless I authorize real collection.")
    next_steps = (["Register v6-mcp.json in your custom host and load v6-collect-research/SKILL.md using that host's documented mechanism."] if host == "generic" else
                  ["Open this workspace in your own agent harness; reopen the session if needed to discover the skill.",
                   "Review and approve the project MCP connection in your host. Codex also requires project trust; organization policies may restrict project integrations."])
    return {"status": "exported" if host == "generic" else "configured", "host": host,
            "workspace": str(workspace), "studies": str(studies), "skill_path": str(skill),
            "config_path": str(config), "command": command, "args": args,
            "allow_paid": allow_paid, "allow_cluster": allow_cluster,
            "cluster_storage_roots": [str(root) for root in roots], "changed": changed, "installed_globally": False,
            "client_started": False, "connection_verified": False, "prompt": prompt,
            "next_steps": next_steps, "skill_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(assets.items())}}
