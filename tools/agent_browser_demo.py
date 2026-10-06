"""Finite, empty-project setup-wizard smoke server. Only synthetic test inputs.

Run through agent_browser_launcher.py. No credentials or provider calls are
allowed; the OS sandbox denies outbound network traffic and unrelated reads.
"""
import argparse
import json
from pathlib import Path
import resource
import signal
import sqlite3
import uuid

from termfinder import Project
from termfinder.web import serve


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-project", type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_FSIZE, (100_000_000, 100_000_000))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.alarm(300)
    root = Path(__file__).resolve().parents[1]
    path = root / "verification" / ("agent-browser-project-" + uuid.uuid4().hex[:12])
    if args.seed_project:
        # Copy a completed synthetic project through SQLite's backup API. The
        # original study/outputs remain read-only and the UI edits its copy.
        seed = args.seed_project.resolve()
        if not seed.is_relative_to(root / "verification") or (seed / "project.sqlite3").is_symlink():
            raise ValueError("Seed only an explicitly reviewed verification project")
        with sqlite3.connect((seed / "project.sqlite3").as_uri() + "?mode=ro", uri=True) as original:
            profile_row = original.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
            sources = [json.loads(row[0]) for row in original.execute("SELECT data FROM sources")]
            if not profile_row or json.loads(profile_row[0])["id"] != "fake" or not sources or any(s["constraints"].get("content_origin") != "synthetic_fixture" for s in sources):
                raise ValueError("The seed must use only the fake profile and synthetic verification sources")
            path.mkdir()
            with sqlite3.connect(path / "project.sqlite3") as copied:
                original.backup(copied)
    project = Project(path)
    print(json.dumps({"project": str(path), "synthetic_corpus_folder": str(root / "src/termfinder/fixtures"),
                      "provider_requests": 0, "outbound_network": "denied"}), flush=True)
    serve(project, port=8766, allow_paid=False)
