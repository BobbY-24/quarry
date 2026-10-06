"""Reviewed synthetic MCP client for the installed browser integration rehearsal.

No agent account or collection is invoked. The stdio client prepares a fake,
one-source plan in an explicitly named verification project, then closes.
Run under verify_offline.py after launching the finite browser helper.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project, report = args.project.resolve(), args.report.resolve()
    if not project.is_relative_to(root / "verification") or not project.is_dir():
        parser.error("Use the fresh synthetic verification project from the browser helper")
    if not report.is_relative_to(root / "verification") or report.exists():
        parser.error("Use a fresh verification report")
    from termfinder import Project
    existing = Project(project)
    if existing.profile and existing.profile["id"] != "fake":
        parser.error("Only a synthetic fake-provider project is allowed")
    process = subprocess.Popen([str(Path(sys.prefix) / "bin" / "termfinder-mcp"), "--project", str(project)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
    identifier = 0
    try:
        def request(method, params=None, notification=False):
            nonlocal identifier
            identifier += 1
            body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if not notification:
                body["id"] = identifier
            process.stdin.write(json.dumps(body, ensure_ascii=False) + "\n")
            process.stdin.flush()
            if notification:
                return None
            response = json.loads(process.stdout.readline(1_000_000))
            assert "error" not in response, response
            return response["result"]

        def tool(name, arguments):
            response = request("tools/call", {"name": name, "arguments": arguments})
            assert not response["isError"], response
            return json.loads(response["content"][0]["text"])

        request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "synthetic-browser-surrogate", "version": "1"}})
        request("notifications/initialized", notification=True)
        setup = tool("prepare_study", {"brief": {
            "id": "neologisms",
            "research_question": "Which new expressions and distinct senses occur in this fictional Gaming source?",
            "data_type": "term", "starter_recipe": "neologisms",
            "local_roots": [str(root / "src" / "termfinder" / "fixtures")],
            "languages": ["en"], "communities": ["Gaming"], "mode": "specialists",
            "model_profile": "fake", "budget_usd": 0, "max_sources": 1}})
        bundle = deepcopy(setup["starter_bundle"])
        bundle["unresolved_questions"] = []
        bundle["agent"].update(tool="offline_mcp_surrogate", model="not_a_real_agent")
        # The shipped fake responses are keyed to the starter recipe ID. The
        # agent normally chooses a study-specific ID; this explicit synthetic
        # surrogate uses the fixture's documented ID to exercise real evidence.
        bundle["recipe"]["execution"]["concurrency"] = 1
        bundle["sources"] = [{"source_key": "synthetic-gaming", "kind": "local",
            "locator": str(root / "src" / "termfinder" / "fixtures" / "community.html"),
            "metadata": {"language": "en", "community": "Gaming", "domain": "synthetic",
                "publication_date": "2026-01-15", "publication_date_reason": None,
                "constraints": {"content_origin": "synthetic_fixture", "license": "synthetic-test",
                    "permitted_use": "offline_rehearsal", "redistribution": "synthetic_only"}},
            "why_selected": "A synthetic fixture to inspect single-extractor discoveries and distinct senses",
            "origin": "researcher_supplied", "search_refs": [], "family_id": "fictional-gaming"}]
        validation = tool("submit_plan", {"bundle": bundle})
        assert validation["valid"]
        review = tool("prepare_review", {"fetch_remote": False})
        assert review["ready"] and not review["approval"]
        assert existing.store.count("jobs") == 0
        result = {"origin": "synthetic_mcp_surrogate", "project": str(project),
            "review_id": review["review_id"], "mode": review["mode"],
            "model_profile": review["model_profile"], "frozen_version": review["freeze"]["version_id"],
            "source_count": review["source_count"], "jobs_before_approval": 0,
            "paid_requests": 0, "external_agent_calls": 0}
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


if __name__ == "__main__":
    main()
