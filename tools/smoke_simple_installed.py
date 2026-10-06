"""Reviewed installed-package CLI/skill smoke check; fake sources only.

Run via verify_offline.py with no source PYTHONPATH. No provider, credentials,
external agent, installer, or startup configuration is used here.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expect-version", choices=("6.3.0", "6.4.0", "6.5.0"), default="6.3.0")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_path = args.report.resolve()
    if not report_path.is_relative_to(root / "verification") or report_path.exists():
        parser.error("Use a fresh report inside verification")
    import termfinder
    from termfinder import Project
    assert termfinder.__version__ == args.expect_version
    assert Path(termfinder.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    with tempfile.TemporaryDirectory(prefix="v6-simple-installed-") as tmp:
        base = Path(tmp)
        corpus = base / "corpus"
        corpus.mkdir()
        source = corpus / "fictional.md"
        source.write_text("This source is a synthetic sentence for a workflow rehearsal.", encoding="utf-8")
        study = base / "study"
        project = Project(study)
        setup = project.prepare_agent_setup({"data_type": "sentence", "research_question": "Which complete source sentences should be retained?",
            "local_roots": [str(corpus)], "languages": ["en"], "communities": ["synthetic-guide"],
            "model_profile": "fake", "budget_usd": 0, "max_sources": 1})
        bundle = deepcopy(setup["starter_bundle"])
        bundle["unresolved_questions"] = []
        bundle["sources"] = [{"source_key": "fixture", "kind": "local", "locator": str(source),
            "metadata": {"language": "en", "community": "synthetic-guide", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "fictional_undated",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                    "permitted_use": "offline_rehearsal", "redistribution": "synthetic_only"}},
            "why_selected": "Synthetic fixture", "origin": "researcher_supplied", "search_refs": [], "family_id": "fixture"}]
        bundle_file = base / "agent-plan.json"
        bundle_file.write_text(json.dumps(bundle), encoding="utf-8")
        commands = []
        def cli(*arguments):
            result = subprocess.run([sys.executable, "-m", "termfinder", "--project", str(study), *arguments],
                cwd=base, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=True)
            commands.append(arguments[0])
            return json.loads(result.stdout)
        cli("validate-plan", str(bundle_file))
        review = cli("review-plan", "--bundle", str(bundle_file))
        assert project.store.count("jobs") == 0
        cli("approve-review", review["review_id"])
        cli("run-review", review["review_id"], "--offline", "--max-jobs", "1")
        cli("run-review", review["review_id"], "--offline")
        saved = cli("release", "cli-rehearsal")
        version = saved["version_id"]
        cli("release", "cli-rehearsal", "--version", version)
        cli("current-review")
        skill = cli("agent-skill", "--out", str(base / "v6-collector-skill"))
        assert (base / "v6-collector-skill" / "SKILL.md").is_file()
        assert project.publication_audit(version)["integrity_passed"]
        # Exercise the actual installed console entry point over stdio. This is
        # a synthetic protocol client, not a configured live Claude/Codex app.
        packets = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "offline-installed-smoke", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "status", "arguments": {}}},
        ]
        protocol = subprocess.run([str(Path(sys.prefix) / "bin" / "termfinder-mcp"), "--project", str(study)],
            input="".join(json.dumps(p) + "\n" for p in packets), cwd=base,
            capture_output=True, text=True, timeout=30, check=True)
        assert protocol.stderr == ""
        replies = [json.loads(line) for line in protocol.stdout.splitlines()]
        assert len(replies) == 3
        assert replies[0]["result"]["serverInfo"]["version"] == args.expect_version
        assert {"prepare_study", "submit_plan", "prepare_review", "collect", "release"} <= {
            t["name"] for t in replies[1]["result"]["tools"]}
        server_status = json.loads(replies[2]["result"]["content"][0]["text"])
        assert server_status["paid_transport_permitted"] is False
        # Only execute this reviewed, shipped synthetic notebook under the same
        # OS sandbox. Agent-authored notebooks/programs are never run here.
        notebook = json.loads((root / "examples" / "simple_student_workflow.ipynb").read_text(encoding="utf-8"))
        namespace = {"__name__": "__offline_notebook_rehearsal__"}
        executed_cells = 0
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                exec(compile("".join(cell["source"]), "simple_student_workflow.ipynb", "exec"), namespace)
                executed_cells += 1
        namespace["workspace"].cleanup()
        report = {"package_version": termfinder.__version__, "installed_module": str(termfinder.__file__),
            "commands": commands, "guided_cli_passed": True, "skill_exported": True,
            "installed_stdio_entrypoint_passed": True, "notebook_cells_executed": executed_cells,
            "frozen_integrity_passed": True, "paid_requests": 0, "external_agent_calls": 0,
            "limits": "Synthetic fake-provider software rehearsal; no usability or field accuracy estimate."}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
