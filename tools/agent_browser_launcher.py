"""Reviewed bounded setup-wizard launcher; loopback inbound only, clean env."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_offline import PROBE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--seed-project", type=Path)
    parser.add_argument("--report", type=Path, default=Path("verification/agent-browser-sandbox.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = args.runtime_root.resolve()
    home = Path.home().resolve()
    if not runtime.is_dir() or runtime in {Path("/"), home, home.parent}:
        parser.error("Pass the specific reviewed Python runtime directory")
    interpreter = (args.python or root / ".venv/bin/python").absolute()
    report_path = (root / args.report).resolve()
    if not interpreter.is_file() or not report_path.is_relative_to(root / "verification") or report_path.exists():
        parser.error("Use an existing reviewed interpreter and a fresh verification report")
    with tempfile.TemporaryDirectory(prefix="v6-agent-browser-", dir="/private/tmp") as tmp, tempfile.NamedTemporaryFile(prefix="v6-unrelated-probe-", dir="/private/tmp") as marker:
        private = Path(tmp).resolve()
        marker.write(b"public unrelated-file probe marker\n")
        marker.flush()
        profile = private / "browser.sb"
        profile.write_text((root / "tools/offline.sb").read_text() + '\n(allow network-inbound (local tcp "localhost:8766"))\n')
        prefix = ["/usr/bin/sandbox-exec", "-D", f"PROJECT_ROOT={root}", "-D", f"RUNTIME_ROOT={runtime}",
                  "-D", f"BASE_RUNTIME_ROOT={runtime}", "-D", f"HOME_ROOT={home}", "-D", f"TEMP_ROOT={private}",
                  "-f", str(profile), str(interpreter)]
        env = {"PATH": str(interpreter.parent) + ":/usr/bin:/bin", "TMPDIR": str(private),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
               "OMP_NUM_THREADS": "2", "ARROW_NUM_THREADS": "2"}
        if not args.installed:
            env["PYTHONPATH"] = str(root / "src")
        probe = subprocess.run(prefix + ["-c", PROBE, marker.name], cwd=root, env=env,
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        if probe.returncode:
            print(probe.stdout, end="", flush=True)
            print(probe.stderr, end="", flush=True)
            raise RuntimeError("Sandbox probe failed; browser server was not launched")
        print(probe.stdout, end="", flush=True)
        command = [str(root / "tools/agent_browser_demo.py")]
        if args.seed_project:
            command += ["--seed-project", str(args.seed_project)]
        try:
            result = subprocess.run(prefix + command, cwd=root, env=env,
                                    stdin=subprocess.DEVNULL, timeout=310)
            returncode=result.returncode
        except KeyboardInterrupt:
            returncode=130
        report = {"exit_code": returncode, "probe": json.loads(probe.stdout),
                  "network": "outbound denied; inbound 127.0.0.1:8766 only", "credential_environment": "empty",
                  "wall_limit_seconds": 300, "paid_requests": 0, "source_tree": not args.installed,
                  "reviewed_files_sha256": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                           for path in [root / "tools/agent_browser_demo.py", root / "tools/agent_browser_launcher.py",
                                                        root / "src/termfinder/web.py", *sorted((root / "src/termfinder/static").glob("*"))]}}
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        return returncode


if __name__ == "__main__":
    raise SystemExit(main())
