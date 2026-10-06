"""Reviewed, finite, synthetic browser smoke launcher. No provider credentials."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from verify_offline import PROBE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    runtime = args.runtime_root.resolve()
    home = Path.home().resolve()
    if not runtime.is_dir() or runtime in {Path("/"), home, home.parent}:
        parser.error("Pass the specific reviewed Python runtime directory")
    interpreter = project / ".venv/bin/python"
    with tempfile.TemporaryDirectory(prefix="v6-browser-", dir="/private/tmp") as tmp, tempfile.NamedTemporaryFile(prefix="v6-unrelated-probe-", dir="/private/tmp") as marker:
        private = Path(tmp).resolve()
        marker.write(b"public probe marker\n")
        marker.flush()
        # Compose the reviewed offline policy with one specific inbound socket.
        profile = private / "browser.sb"
        profile.write_text((project / "tools/offline.sb").read_text() + '\n(allow network-inbound (local tcp "localhost:8765"))\n')
        prefix = ["/usr/bin/sandbox-exec", "-D", f"PROJECT_ROOT={project}", "-D", f"RUNTIME_ROOT={runtime}", "-D", f"BASE_RUNTIME_ROOT={runtime}", "-D", f"HOME_ROOT={home}", "-D", f"TEMP_ROOT={private}", "-f", str(profile), str(interpreter)]
        env = {"PATH": str(interpreter.parent) + ":/usr/bin:/bin", "TMPDIR": str(private), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "2", "ARROW_NUM_THREADS": "2"}
        probe = subprocess.run(prefix + ["-c", PROBE, marker.name], cwd=project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        if probe.returncode:
            print(probe.stdout, end="", flush=True)
            print(probe.stderr, end="", flush=True)
            raise RuntimeError("Browser sandbox probe failed; server was not launched")
        print(probe.stdout, end="", flush=True)
        result = subprocess.run(prefix + [str(project / "tools/browser_demo.py")], cwd=project, env=env, stdin=subprocess.DEVNULL, timeout=310)
        report = {"exit_code": result.returncode, "probe": json.loads(probe.stdout), "network": "outbound denied; inbound 127.0.0.1:8765 only", "credential_environment": "empty", "wall_limit_seconds": 300, "paid_requests": 0}
        (project / "verification/browser-sandbox.json").write_text(json.dumps(report, indent=2) + "\n")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
