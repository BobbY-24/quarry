"""Reviewed, fail-closed CI isolation for application/build/test execution.

Dependency wheels are acquired separately. Run this orchestrator with env -i
and Python -I -S. Only explicitly named runtimes, repository and private temp
are available to the executed code. No credentials or network are inherited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time

PROBE = r'''
import json, os, socket, sys
result = {}
isolated_namespace = False
if sys.platform.startswith('linux'):
    isolated_namespace = os.readlink('/proc/self/ns/net') != sys.argv[2]
    result['host_network_namespace_isolated'] = isolated_namespace
    with open('/proc/self/status', encoding='utf-8') as stream:
        status = dict(line.rstrip().split(':', 1) for line in stream if ':' in line)
    result['application_capabilities_dropped'] = all(
        int(status.get(key, '1').strip(), 16) == 0
        for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))
    result['no_new_privileges'] = status.get('NoNewPrivs', '').strip() == '1'
    import pwd
    result['synthetic_account_home'] = pwd.getpwuid(os.getuid()).pw_dir == '/home/quarry-ci'
try:
    with open(sys.argv[1], 'rb') as stream: stream.read(1)
except OSError:
    result['unrelated_file_read_denied'] = True
else:
    result['unrelated_file_read_denied'] = False
try:
    client = socket.socket(); client.settimeout(.2); client.connect(('127.0.0.1', 9))
except OSError as error:
    # bubblewrap isolates host/external networking; its private loopback may
    # return connection-refused instead of a macOS permission error.
    result['network_denied'] = error.errno in (1, 13) or isolated_namespace
else:
    result['network_denied'] = False
finally:
    if 'client' in locals(): client.close()
print(json.dumps(result, sort_keys=True))
sys.exit(0 if all(result.values()) else 3)
'''

# SIP removes DYLD variables while starting Apple's protected sandbox launcher.
# Set only this reviewed artifact path after entering Seatbelt, then exec the
# selected ordinary Python. The original explicit empty environment is retained.
SQLITE_EXEC = r'''
import os, sys
environment = dict(os.environ)
environment['DYLD_LIBRARY_PATH' if sys.platform == 'darwin' else 'LD_LIBRARY_PATH'] = sys.argv[1]
os.execve(sys.argv[2], [sys.argv[2], *sys.argv[3:]], environment)
'''


def sqlite_runtime(project, root):
    expected = project / ".ci" / "sqlite"
    if root.absolute() != expected or root.resolve() != expected.resolve():
        raise ValueError("SQLite CI runtime must be the fixed project/.ci/sqlite artifact")
    spec = importlib.util.spec_from_file_location("quarry_ci_sqlite", project / "tools" / "ci_sqlite.py")
    sqlite_tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sqlite_tool)
    manifest_path = sqlite_tool.controlled_path(root / "manifest.json", project / ".ci")
    if manifest_path.stat().st_size > 16384:
        raise ValueError("SQLite manifest exceeds its bound")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filename = "libsqlite3.0.dylib" if sys.platform == "darwin" else "libsqlite3.so.0"
    alias = "libsqlite3.dylib" if sys.platform == "darwin" else "libsqlite3.so"
    if (manifest.get("schema_version") != 1 or manifest.get("sqlite_version") != sqlite_tool.VERSION
            or manifest.get("sqlite_source_id") != sqlite_tool.SOURCE_ID
            or manifest.get("archive_sha256") != sqlite_tool.ARCHIVE_SHA256
            or manifest.get("sqlite3_c_sha3_256") != sqlite_tool.C_SHA3_256
            or manifest.get("library_filename") != filename
            or manifest.get("platform") != platform.system()
            or manifest.get("machine") != platform.machine()
            or manifest.get("aliases") != {alias: filename}):
        raise ValueError("SQLite manifest does not identify the reviewed platform/release")
    library = sqlite_tool.controlled_path(root / "lib" / filename, project / ".ci")
    if not 1 <= library.stat().st_size <= 32_000_000 or sqlite_tool.sha256(library) != manifest.get("library_sha256"):
        raise ValueError("SQLite native library does not match its build receipt")
    alias_path = root / "lib" / alias
    if not alias_path.is_symlink() or os.readlink(alias_path) != filename:
        raise ValueError("SQLite library alias does not identify the reviewed artifact")
    if {path.name for path in (root / "lib").iterdir()} != {filename, alias}:
        raise ValueError("SQLite loader directory contains an unreviewed artifact")
    identity = {key: manifest[key] for key in
                ("sqlite_version", "sqlite_source_id", "archive_sha256", "library_sha256")}
    if (root / "python").exists():
        identity["native_extension"] = sqlite_native_overlay(project, root, identity)
    return root / "lib", identity


def sqlite_native_overlay(project, root, library_identity):
    spec = importlib.util.spec_from_file_location("quarry_ci_native_sqlite", project / "tools/ci_sqlite_extension.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    overlay = builder.SQLITE.controlled_path(root / "python", project / ".ci")
    manifest_path = builder.SQLITE.controlled_path(overlay / "manifest.json", project / ".ci")
    if manifest_path.stat().st_size > 262144:
        raise ValueError("Native SQLite manifest exceeds its bound")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = platform.python_version()
    suffix, soabi = sysconfig.get_config_var("EXT_SUFFIX"), sysconfig.get_config_var("SOABI")
    filename = builder.validate_abi(version, sys.implementation.name, suffix, soabi,
                                    builtin="_sqlite3" in sys.builtin_module_names,
                                    debug=bool(sysconfig.get_config_var("Py_DEBUG")),
                                    gil_disabled=bool(sysconfig.get_config_var("Py_GIL_DISABLED")))
    if (manifest.get("schema_version") != 1
            or manifest.get("runtime_component") != "stock_cpython_sqlite_native_extension"
            or manifest.get("python_version") != version or manifest.get("implementation") != "cpython"
            or manifest.get("module_filename") != filename or manifest.get("extension_suffix") != suffix
            or manifest.get("soabi") != soabi or manifest.get("platform") != platform.system()
            or manifest.get("machine") != platform.machine()
            or manifest.get("source_checkpoint") != "CPython v" + version
            or manifest.get("source_archive_sha256") != builder.CPYTHON_SOURCES[version]
            or manifest.get("sqlite_library_sha256") != library_identity["library_sha256"]
            or manifest.get("sqlite_archive_sha256") != library_identity["archive_sha256"]
            or manifest.get("sqlite_version") != library_identity["sqlite_version"]
            or manifest.get("sqlite_source_id") != library_identity["sqlite_source_id"]):
        raise ValueError("Native SQLite manifest differs from the reviewed Python/library ABI")
    native = builder.SQLITE.controlled_path(overlay / filename, project / ".ci")
    if not 1 <= native.stat().st_size <= 8_000_000 or builder.SQLITE.sha256(native) != manifest.get("native_module_sha256"):
        raise ValueError("Native SQLite module differs from its build receipt")
    builder.overlay_layout(overlay, filename)
    return {key: manifest[key] for key in ("python_version", "source_checkpoint", "source_archive_sha256",
                                          "soabi", "module_filename", "native_module_sha256")}


def source_hashes(project):
    hashes = {}
    for name in ("pyproject.toml", "requirements.txt", "requirements-build.txt", "README.md", "LICENSE"):
        path=project/name
        if path.is_file() and not path.is_symlink():
            hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("src", "tests", "tools", "examples", ".github"):
        for path in sorted((project / name).rglob("*")):
            if (path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
                    and not any(part.endswith(".egg-info") for part in path.parts)):
                hashes[path.relative_to(project).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def synthetic_identity(private):
    # No host account database or home directory is exposed. Clean subprocesses
    # can still resolve their uid even when their environment deliberately omits
    # HOME. These files contain only the sandbox's current numeric identity.
    passwd, group = private / "passwd", private / "group"
    passwd.write_text(f"quarry-ci:x:{os.getuid()}:{os.getgid()}:Quarry CI:/home/quarry-ci:/bin/false\n", encoding="utf-8")
    group.write_text(f"quarry-ci:x:{os.getgid()}:\n", encoding="utf-8")
    return passwd, group


def bounded_run(command, *, environment, cwd, timeout, cpu_seconds):
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1_073_741_824, 1_073_741_824))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (4_294_967_296, 4_294_967_296))
    with tempfile.TemporaryFile(dir=environment["TMPDIR"]) as log:
        process = subprocess.Popen(command, env=environment, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, preexec_fn=limits)
        try:
            process.wait(timeout=timeout)
            code = process.returncode
        except subprocess.TimeoutExpired:
            # Terminate the entire isolated process family, not only its launcher.
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            code = 124
        log.seek(0)
        output = log.read(8_388_609)
        if len(output) > 8_388_608:
            code, output = 125, output[:8_388_608] + b"\nCI output limit reached.\n"
        return code, output.decode("utf-8", errors="replace")


def isolation_result(code, output, *, linux):
    """Expose fixed startup categories, never arbitrary launcher output or paths."""
    required = {"unrelated_file_read_denied", "network_denied"}
    if linux:
        required.update({"host_network_namespace_isolated", "application_capabilities_dropped",
                         "no_new_privileges", "synthetic_account_home"})
    try:
        probe = json.loads(output)
    except ValueError:
        probe = None
    valid = (isinstance(probe, dict) and required <= probe.keys()
             and all(type(probe[key]) is bool for key in required))
    if valid and code == 0 and all(probe[key] for key in required):
        return probe, None
    lower = output.lower()
    if code == 124:
        category = "startup_timeout"
    elif "bwrap:" in lower and "loopback:" in lower:
        category = "private_loopback_setup_failed"
    elif "bwrap:" in lower and any(text in lower for text in ("namespace", "unshare")):
        category = "namespace_setup_failed"
    elif "bwrap:" in lower and any(text in lower for text in ("mount", "bind", "mkdir")):
        category = "filesystem_setup_failed"
    elif "bwrap:" in lower and "exec" in lower:
        category = "interpreter_launch_failed"
    elif valid:
        category = "isolation_assertion_failed"
    else:
        category = "unrecognized_startup_output"
    safe_probe = {key: probe[key] for key in sorted(required)} if valid else {}
    return safe_probe, category


def launcher_diagnostic(output):
    # The trusted launcher only receives fixed public probe arguments and an
    # empty credential environment. Keep its first error line; never include
    # Python tracebacks, additional output, local path values or env assignments.
    line = output.splitlines()[0] if output else ""
    if not line.startswith("bwrap:") or "=" in line or len(line) > 500:
        return None
    return re.sub(r"/[^\s:'\"]+", "<path>", line)[:300]


def main(argv=None):
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--base-runtime-root", type=Path, required=True)
    parser.add_argument("--sqlite-runtime-root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--cpu-seconds", type=int, default=300)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 1800 or not 1 <= args.cpu_seconds <= 900:
        parser.error("CI wall/CPU bounds must remain finite")
    interpreter = args.python.expanduser().absolute()
    roots = {args.runtime_root.expanduser().resolve(), args.base_runtime_root.expanduser().resolve()}
    if not interpreter.is_file() or any(not root.is_dir() or root in {Path("/"), Path.home(), Path.home().parent} for root in roots):
        parser.error("Explicit reviewed interpreter and narrow runtime directories are required")
    if not any(interpreter.resolve().is_relative_to(root) for root in roots):
        parser.error("Interpreter must belong to an explicit reviewed runtime")
    sqlite_library, sqlite_identity = None, None
    if args.sqlite_runtime_root:
        try:
            sqlite_library, sqlite_identity = sqlite_runtime(project, args.sqlite_runtime_root)
        except (ValueError, OSError, KeyError):
            parser.error("SQLite CI runtime must match its reviewed build receipt")
    destination = args.report.resolve()
    if not destination.is_relative_to(project / "verification"):
        parser.error("CI receipts must stay inside repository verification/")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide explicit reviewed Python arguments after --")
    started = time.monotonic()
    before_hashes = source_hashes(project)
    with tempfile.TemporaryDirectory(prefix="quarry-ci-", dir="/private/tmp" if sys.platform == "darwin" else "/tmp") as temporary, \
            tempfile.NamedTemporaryFile(prefix="quarry-unrelated-probe-", dir="/private/tmp" if sys.platform == "darwin" else "/tmp") as marker:
        private = Path(temporary).resolve()
        marker.write(b"public isolation probe marker; no private data\n"); marker.flush()
        if sys.platform == "darwin":
            if not Path("/usr/bin/sandbox-exec").is_file():
                parser.error("macOS Seatbelt is required; no unsandboxed fallback")
            prefix = ["/usr/bin/sandbox-exec", "-D", f"PROJECT_ROOT={project}",
                      "-D", f"RUNTIME_ROOT={args.runtime_root.resolve()}",
                      "-D", f"BASE_RUNTIME_ROOT={args.base_runtime_root.resolve()}",
                      "-D", f"HOME_ROOT={Path.home()}", "-D", f"TEMP_ROOT={private}",
                      "-f", str(project / "tools" / "offline.sb"), str(interpreter)]
            sandbox = "macOS Seatbelt"
        elif sys.platform.startswith("linux"):
            bwrap = shutil.which("bwrap", path="/usr/bin:/bin")
            if not bwrap:
                parser.error("Linux bubblewrap is required; no unsandboxed fallback")
            prefix = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
                      "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
            for system in ("/usr/bin", "/usr/lib", "/usr/lib64", "/usr/libexec/gcc", "/usr/include", "/usr/share/zoneinfo", "/bin", "/lib", "/lib64"):
                if Path(system).exists(): prefix.extend(["--ro-bind", system, system])
            for system in ("/etc/ld.so.cache", "/etc/localtime"):
                if Path(system).exists(): prefix.extend(["--ro-bind", system, system])
            for root in sorted(roots): prefix.extend(["--ro-bind", str(root), str(root)])
            passwd, group = synthetic_identity(private)
            prefix.extend(["--ro-bind", str(passwd), "/etc/passwd", "--ro-bind", str(group), "/etc/group",
                           "--dir", "/home/quarry-ci"])
            prefix.extend(["--bind", str(project), str(project), "--bind", str(private), str(private),
                           "--chdir", str(project), str(interpreter)])
            sandbox = "Linux bubblewrap"
        else:
            parser.error("Supported offline CI platforms are Linux and macOS")
        if sqlite_library:
            prefix.extend(["-I", "-S", "-c", SQLITE_EXEC, str(sqlite_library), str(interpreter)])
        environment = {"PATH": str(interpreter.parent) + ":/usr/bin:/bin", "TMPDIR": str(private),
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                       "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "ARROW_NUM_THREADS": "2"}
        if args.source: environment["PYTHONPATH"] = str(project / "src")
        if sqlite_identity and sqlite_identity.get("native_extension"):
            overlay = str(project / ".ci/sqlite/python")
            environment["QUARRY_CI_SQLITE_EXTENSION_ROOT"] = overlay
            environment["PYTHONPATH"] = overlay + (os.pathsep + environment["PYTHONPATH"] if args.source else "")
        host_namespace = os.readlink("/proc/self/ns/net") if sys.platform.startswith("linux") else "unavailable_on_macos"
        code, output = bounded_run(prefix + ["-c", PROBE, marker.name, host_namespace], environment=environment,
                                   cwd=project, timeout=20, cpu_seconds=args.cpu_seconds)
        probe, category = isolation_result(code, output, linux=sys.platform.startswith("linux"))
        if category:
            failure = {"schema_version": 1, "isolation_probe_failed": True, "probe": probe,
                       "application_executed": False, "exit_code": code, "sandbox": sandbox,
                       "startup_failure_category": category,
                       "launcher_diagnostic": launcher_diagnostic(output),
                       "probe_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                       "reviewed_files_sha256": before_hashes}
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({key: value for key, value in failure.items() if key != "reviewed_files_sha256"}))
            return 3
        code, output = bounded_run(prefix + command, environment=environment, cwd=project,
                                   timeout=args.timeout, cpu_seconds=args.cpu_seconds)
        print(output, end="", flush=True)
        hashes = source_hashes(project)
        changed = sorted(key for key in set(before_hashes) | set(hashes) if before_hashes.get(key) != hashes.get(key))
        if changed and code == 0: code = 126
        report = {"schema_version": 1, "sandbox": sandbox, "probe": probe,
                  "credential_environment": "empty", "network": "host_network_denied" if sys.platform.startswith("linux") else "denied",
                  "python_version": platform.python_version(),
                  "sqlite_runtime": sqlite_identity,
                  "platform": platform.platform(), "python_arguments": command, "source_tree": args.source,
                  "wall_timeout_seconds": args.timeout, "cpu_seconds_per_process": args.cpu_seconds,
                  "file_bytes_per_file_limit": 1_073_741_824, "open_files_limit": 256,
                  "address_space_bytes_per_process": 4_294_967_296 if sys.platform.startswith("linux") else None,
                  "address_space_reason": None if sys.platform.startswith("linux") else "Seatbelt has no reliable per-process AS bound",
                  "exit_code": code, "elapsed_seconds": round(time.monotonic() - started, 3),
                  "reviewed_files_sha256": before_hashes, "files_changed_during_execution": changed,
                  "output_sha256": hashlib.sha256(output.encode()).hexdigest()}
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return code


if __name__ == "__main__":
    raise SystemExit(main())
