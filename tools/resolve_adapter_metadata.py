"""Metadata-only optional wheel resolver. Review before execution.

Downloads wheels with trusted pip, never installs/imports/builds downloaded code.
The pip child has an empty credential environment, OS file isolation and bounded
CPU/time/file output. Authorized PyPI dependency-data reads require outbound HTTPS.
"""
import argparse
import email.parser
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--home-root", type=Path, default=Path.home())
    parser.add_argument("--refresh", action="store_true", help="Resolve newer transitive metadata instead of reproducing the existing lock")
    args = parser.parse_args()
    project, runtime = args.project.resolve(), args.runtime_root.resolve()
    python = args.python.absolute()
    home = args.home_root.expanduser().resolve()
    if sys.platform != "darwin" or not python.is_file() or not runtime.is_dir():
        raise SystemExit("Explicit macOS interpreter/runtime required")
    if runtime in {Path("/"), home, home.parent} or project in {Path("/"), home, home.parent}:
        raise SystemExit("Broad filesystem root forbidden")
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_FSIZE, (536870912, 536870912))
    with tempfile.TemporaryDirectory(prefix="quarry-adapter-wheel-metadata-", dir="/private/tmp") as private:
        temp = Path(private).resolve()
        profile = temp / "resolver.sb"
        profile.write_text('''(version 1)
(allow default)
(deny network-inbound)
(deny file-read-data
 (require-all (subpath "/Users")
  (require-not (subpath (param "PROJECT")))
  (require-not (subpath (param "RUNTIME"))))
 (require-all (subpath "/private/tmp") (require-not (subpath (param "TEMP"))))
 (require-all (subpath "/private/var/folders") (require-not (subpath (param "TEMP"))))
 (subpath "/Library/Keychains") (subpath "/private/etc/ssh") (subpath "/private/var/root")
 (subpath (string-append (param "HOME_ROOT") "/.ssh"))
 (subpath (string-append (param "HOME_ROOT") "/.aws"))
 (subpath (string-append (param "HOME_ROOT") "/.config"))
 (subpath (string-append (param "HOME_ROOT") "/Library/Keychains")))
(deny file-write* (require-all (require-not (subpath (param "TEMP"))) (require-not (literal "/dev/null"))))
''')
        wheels = temp / "wheels"
        wheels.mkdir()
        command = ["/usr/bin/sandbox-exec", "-D", "PROJECT=" + str(project), "-D", "RUNTIME=" + str(runtime), "-D", "HOME_ROOT=" + str(home),
            "-D", "TEMP=" + str(temp), "-f", str(profile), str(python), "-I", "-m", "pip", "--isolated",
            "download", "--no-input", "--no-cache-dir", "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
            "--dest", str(wheels)]
        locked = project / "requirements-adapters-lock.txt"
        use_lock = locked.is_file() and not args.refresh
        command.extend(["--require-hashes"] if use_lock else [])
        command.extend(["-r", str(locked if use_lock else project / "requirements-adapters.txt"), "-c", str(project / "requirements.txt")])
        env = {"PATH": "/usr/bin:/bin", "TMPDIR": str(temp), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, env=env, cwd=temp, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180, preexec_fn=limits)
        if result.returncode:
            print(result.stdout[-12000:])
            return result.returncode
        rows = []
        for wheel in sorted(wheels.glob("*.whl")):
            with zipfile.ZipFile(wheel) as archive:
                metadata_names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
                if len(metadata_names) != 1:
                    raise ValueError("Wheel metadata count invalid")
                message = email.parser.BytesParser().parsebytes(archive.read(metadata_names[0]))
                rows.append({"name": message["Name"], "version": message["Version"], "wheel": wheel.name,
                    "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "requires_python": message["Requires-Python"],
                    "requires_dist": message.get_all("Requires-Dist", []),
                    "release": "https://pypi.org/project/" + message["Name"] + "/" + message["Version"] + "/"})
        lock = "# Metadata resolution only; no downloaded code installed or executed.\n# Python 3.12 / macOS arm64 wheel graph; platform wheel hashes are specific.\n"
        lock += "\n".join(row["name"] + "==" + row["version"] + " --hash=sha256:" + row["sha256"] for row in rows) + "\n"
        (project / "requirements-adapters-lock.txt").write_text(lock)
        graph = {"schema_version": "1", "resolved_date": "2026-10-06", "interpreter_target": "CPython 3.12 / macOS arm64",
            "metadata_only": True, "foreign_code_execution": False, "foreign_source_review": "not_complete", "wheels": rows}
        (project / "examples/v7/adapters/dependency_lock_manifest.json").write_text(json.dumps(graph, sort_keys=True, indent=2) + "\n")
        print(json.dumps({"wheel_count": len(rows), "foreign_code_execution": False, "lock": "requirements-adapters-lock.txt"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
