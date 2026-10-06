"""Reviewed macOS offline verification launcher with clean environment and bounds.

Launch this orchestrator itself with a clean environment and Python -I -S, as
documented. It accepts explicit reviewed interpreter/runtime locations and never
reads credentials. Linux verification uses the documented isolated container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
import time

PROBE = r'''
import json, socket, sys
result = {}
try:
    with open(sys.argv[1], 'rb') as stream:
        stream.read(1)
except OSError:
    result['unrelated_file_read_denied'] = True
else:
    result['unrelated_file_read_denied'] = False
try:
    client = socket.socket()
    client.settimeout(0.2)
    client.connect(('127.0.0.1', 9))
except PermissionError:
    result['network_denied'] = True
except OSError as error:
    result['network_denied'] = error.errno in (1, 13)
else:
    result['network_denied'] = False
finally:
    if 'client' in locals():
        client.close()
print(json.dumps(result, sort_keys=True))
sys.exit(0 if all(result.values()) else 3)
'''


def main(argv=None) -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Explicit reviewed Python interpreter")
    parser.add_argument("--runtime-root", type=Path, required=True, help="Reviewed Python runtime root")
    parser.add_argument("--base-runtime-root", type=Path, help="Additional base stdlib/runtime root; defaults to --runtime-root")
    parser.add_argument("--home-root", type=Path, default=Path.home(), help="Home directory to protect; values never read")
    parser.add_argument("--source", action="store_true", help="Use reviewed src via PYTHONPATH; omit for installed-wheel checks")
    parser.add_argument("--report", type=Path, help="Save invocation/probe/result report inside V6")
    parser.add_argument("--timeout", type=int, default=600, help="Finite wall-clock seconds")
    parser.add_argument("--cpu-seconds", type=int, default=300, help="Finite CPU seconds per child")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Python arguments after --; defaults to unittest discovery")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or not shutil.which("sandbox-exec", path="/usr/bin:/bin"):
        parser.error("This launcher requires macOS Seatbelt. Use the documented network-disabled Linux container workflow.")
    if not 1 <= args.timeout <= 3600 or not 1 <= args.cpu_seconds <= 1800:
        parser.error("Timeout/CPU limits must be finite and within the documented bounds.")
    interpreter = args.python.expanduser().absolute()
    runtime = args.runtime_root.expanduser().resolve()
    base_runtime = (args.base_runtime_root or runtime).expanduser().resolve()
    home = args.home_root.expanduser().resolve()
    for path in (runtime, base_runtime):
        if not path.is_dir() or path in {Path("/"), home, home.parent}:
            parser.error("A runtime root must name a specific reviewed runtime directory, not a filesystem/home root.")
    if not interpreter.is_file():
        parser.error("The reviewed interpreter does not exist.")
    if args.report:
        report_path = args.report.expanduser().resolve()
        if not report_path.is_relative_to(project):
            parser.error("The verification report must stay inside V6.")
    else:
        report_path = None
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    command = command or ["-m", "unittest", "discover", "-s", "tests", "-v"]
    started = time.monotonic()

    def bounds():
        resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_seconds, args.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1_073_741_824, 1_073_741_824))

    with tempfile.TemporaryDirectory(prefix="v6-private-", dir="/private/tmp") as tmp, \
         tempfile.NamedTemporaryFile(prefix="v6-unrelated-probe-", dir="/private/tmp") as marker:
        marker.write(b"public sandbox probe marker; no secret data\n")
        marker.flush()
        private_tmp = Path(tmp).resolve()
        prefix = ["/usr/bin/sandbox-exec", "-D", f"PROJECT_ROOT={project}",
                  "-D", f"RUNTIME_ROOT={runtime}", "-D", f"BASE_RUNTIME_ROOT={base_runtime}",
                  "-D", f"HOME_ROOT={home}", "-D", f"TEMP_ROOT={private_tmp}",
                  "-f", str(project / "tools" / "offline.sb"), str(interpreter)]
        environment = {"PATH": str(interpreter.parent) + ":/usr/bin:/bin", "TMPDIR": str(private_tmp),
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                       "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "ARROW_NUM_THREADS": "2"}
        if args.source:
            environment["PYTHONPATH"] = str(project / "src")
        probe = subprocess.run(prefix + ["-c", PROBE, marker.name], env=environment, cwd=project,
                               stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=min(args.timeout, 30), preexec_fn=bounds)
        try:
            probe_result = json.loads(probe.stdout)
        except ValueError:
            probe_result = {"unrelated_file_read_denied": False, "network_denied": False}
        if probe.returncode or not all(probe_result.values()):
            print("Sandbox probe failed; requested code was not executed.", file=sys.stderr)
            print(json.dumps({"probe": probe_result, "exit_code": probe.returncode}, sort_keys=True), file=sys.stderr)
            if probe.stderr:
                print(probe.stderr, file=sys.stderr)
            return 3
        print(json.dumps({"sandbox": "macOS Seatbelt", **probe_result}, sort_keys=True), flush=True)
        try:
            result = subprocess.run(prefix + command, env=environment, cwd=project,
                                    stdin=subprocess.DEVNULL, timeout=args.timeout, preexec_fn=bounds)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            print("Verification reached its finite wall-clock limit.", file=sys.stderr)
            returncode = 124
        report = {"schema_version": 1, "sandbox": "macOS Seatbelt", "network": "denied",
                  "unrelated_file_contents": "denied", "credential_environment": "empty",
                  "probe": probe_result, "python": str(interpreter), "runtime_root": str(runtime),
                  "base_runtime_root": str(base_runtime), "source_tree": args.source,
                  "python_arguments": command, "cpu_seconds": args.cpu_seconds,
                  "wall_timeout_seconds": args.timeout, "exit_code": returncode,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        report["reviewed_files_sha256"] = {
            path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for directory in ("src", "tests", "tools", "examples")
            for path in sorted((project / directory).rglob("*"))
            if path.is_file() and not path.is_symlink() and path.suffix != ".pyc" and "__pycache__" not in path.parts
        }
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return returncode


if __name__ == "__main__":
    raise SystemExit(main())
