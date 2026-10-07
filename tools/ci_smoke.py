"""Offline installed-wheel CLI/API/MCP/export and artifact integrity checks."""
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib import metadata
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def run(arguments, *, input=None, cwd=None):
    result = subprocess.run([sys.executable, *arguments], input=input, text=True,
                            capture_output=True, timeout=30, cwd=cwd)
    if result.returncode:
        raise AssertionError(f"offline smoke subprocess failed with exit {result.returncode}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    import termfinder
    from termfinder import Project
    from termfinder.config import starter_recipe
    from termfinder.sources import parse_document
    assert Path(termfinder.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), "must import a fresh installed wheel"
    assert metadata.version("nlpx-termfinder") == termfinder.__version__
    wheel_hashes = {}
    for wheel in sorted(args.wheelhouse.glob("*.whl")):
        wheel_hashes[wheel.name] = sha256(wheel.read_bytes()).hexdigest()
    assert len(wheel_hashes) == 5, "only the five pinned build/runtime dependency wheels are expected"
    distributions = list(args.dist.glob("*.whl"))
    assert len(distributions) == 1
    wheel_hashes[distributions[0].name] = sha256(distributions[0].read_bytes()).hexdigest()
    root = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(distributions[0]) as wheel:
        for source in (root / "src" / "termfinder").rglob("*"):
            if source.is_file() and source.suffix != ".pyc" and "__pycache__" not in source.parts:
                relative = source.relative_to(root / "src").as_posix()
                assert wheel.read(relative) == source.read_bytes(), f"wheel source/asset drift: {relative}"
    checks = ["wheel package/version/source/assets integrity", "five pinned binary dependency artifact hashes"]
    with tempfile.TemporaryDirectory(prefix="quarry-ci-smoke-") as temporary:
        base = Path(temporary)
        cli = base / "cli"
        run(["-m", "termfinder", "init", str(cli), "--profile", "fake"], cwd=base)
        status = json.loads(run(["-m", "termfinder", "--project", str(cli), "status"], cwd=base))
        assert status["counts"]["sources"] == 0
        checks.append("installed packaged CLI init/status")
        project = Project(base / "api")
        project.configure(starter_recipe("neologisms"), "fake")
        project.add_source(parse_document(files("termfinder").joinpath("fixtures", "community.html").read_bytes(),
            "text/html", "synthetic-community.html", {"community": "Gaming", "language": "en", "constraints": {"content_origin": "synthetic_fixture"}}))
        project.collect()
        assert project.inventory()["terms"]
        version = project.snapshot("ci-frozen-synthetic-v1")
        formats = ["csv", "jsonl", "parquet", "annotation"]
        first, second = base / "first", base / "second"
        project.export(version, first, formats)
        project.export(version, second, list(reversed(formats)))
        hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in first.iterdir() if path.is_file()}
        assert hashes == {path.name: sha256(path.read_bytes()).hexdigest() for path in second.iterdir() if path.is_file()}
        assert any(name.endswith(".parquet") for name in hashes)
        checks.append("installed notebook API, all exports, byte-identical frozen version")
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "offline-ci", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]
        (base / "mcp").mkdir()
        output = run(["-m", "termfinder.mcp_server", "--workspace", str(base / "mcp")],
                     input="".join(json.dumps(message) + "\n" for message in messages), cwd=base)
        replies = [json.loads(line) for line in output.splitlines()]
        tools = next(reply["result"]["tools"] for reply in replies if reply.get("id") == 2)
        assert {"create_study", "status", "collect"} <= {tool["name"] for tool in tools}
        checks.append("installed stdio MCP initialize/tools-list/EOF shutdown")
        # This noncredential marker tests the rejection/error boundary; it is
        # deliberately synthetic and never usable for a service.
        canary = "sk-QUARRY-SYNTHETIC-CANARY-00000000000000000000"
        bad = starter_recipe("neologisms"); bad["api_key"] = canary
        try: project.configure(bad, "fake")
        except ValueError as error:
            assert canary not in str(error)
        else: raise AssertionError("credential-shaped unsupported setup field was accepted")
        assert canary not in json.dumps(project.inventory())
        assert all(canary.encode() not in path.read_bytes() for path in first.iterdir() if path.is_file())
        checks.append("synthetic credential marker excluded from errors/inventory/export")
    result = {"schema_version": 1, "synthetic_only": True, "paid_requests": 0, "checks": checks,
              "installed_version": termfinder.__version__, "wheel_sha256": wheel_hashes,
              "frozen_export_sha256": hashes, "source_artifacts_match_built_wheel": True}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
