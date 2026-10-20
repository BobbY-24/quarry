"""Rehearse installed V6 inside a synthetic coding-agent harness, without a UI.

Review this script and run under verify_offline.py. It installs connection files
only in fresh test workspaces, then invokes the generated local MCP command.
No host account, personal configuration, credential or real provider is used.
"""
from copy import deepcopy
import argparse
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import select
import subprocess
import sys
import time


class SyntheticHarness:
    def __init__(self, connection, cwd):
        self.process = subprocess.Popen([connection["command"], *connection["args"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd)
        self.identifier = 0
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "offline-synthetic-researcher-harness", "version": "1"}})
        self.request("notifications/initialized", notification=True)

    def request(self, method, params=None, *, notification=False):
        self.identifier += 1
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            message["id"] = self.identifier
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        if notification:
            return None
        if not select.select([self.process.stdout], [], [], 20)[0]:
            raise TimeoutError("Synthetic MCP response exceeded the finite timeout")
        line = self.process.stdout.readline(300_000)
        response = json.loads(line)
        assert response.get("id") == self.identifier and "error" not in response, response
        return response["result"]

    def tool(self, tool_name, **arguments):
        response = self.request("tools/call", {"name": tool_name, "arguments": arguments})
        assert not response["isError"], response
        return json.loads(response["content"][0]["text"])

    def wait_collection(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = self.tool("status")
            if not result["running"]:
                assert not result.get("worker_error"), result
                return result
            time.sleep(0.05)
        raise TimeoutError("Synthetic collection exceeded the finite timeout")

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        stderr = self.process.stderr.read(3000)
        self.process.stdout.close()
        self.process.stderr.close()
        assert self.process.returncode == 0 and not stderr, "MCP exited with unexpected diagnostics"


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.iterdir() if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    if not out.is_relative_to(root / "verification") or out.exists():
        parser.error("Use a fresh output directory inside verification")
    out.mkdir(parents=True)
    import quarry
    assert quarry.__version__ == "6.5.0"
    assert Path(quarry.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    connections = {}
    for host in ("codex", "claude", "generic"):
        workspace = out / host
        workspace.mkdir()
        command = [sys.executable, "-m", "quarry", "connect", "--host", host,
                   "--workspace", str(workspace)]
        first = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
        connection = json.loads(first.stdout)
        assert connection["installed_globally"] is False and connection["allow_paid"] is False
        assert Path(connection["skill_path"]).joinpath("SKILL.md").is_file()
        assert Path(connection["config_path"]).is_file()
        second = json.loads(subprocess.run(command, capture_output=True, text=True,
                                          timeout=20, check=True).stdout)
        assert second["changed"] is False
        connections[host] = connection
    connection = connections["generic"]
    workspace = Path(connection["workspace"])
    corpus = workspace / "corpus"
    corpus.mkdir()
    source = corpus / "community.html"
    source.write_bytes(files("quarry").joinpath("fixtures", "community.html").read_bytes())
    cases = []
    harness = SyntheticHarness(connection, workspace)
    try:
        names = {tool["name"] for tool in harness.request("tools/list")["tools"]}
        assert {"create_study", "open_study", "list_studies", "inspect_review",
                "review_sources", "review_text", "collect", "release"} <= names
        for mode in ("broad", "specialists"):
            slug = "vocabulary-" + mode
            harness.tool("create_study", slug=slug)
            setup = harness.tool("prepare_study", brief={"id": "neologisms", "data_type": "term",
                "research_question": "Which expressions and different senses occur in this fictional Gaming source?",
                "starter_recipe": "neologisms", "local_roots": [str(corpus)],
                "languages": ["en"], "communities": ["Gaming"], "mode": mode,
                "model_profile": "fake", "budget_usd": 0, "max_sources": 1})
            bundle = deepcopy(setup["starter_bundle"])
            bundle["unresolved_questions"] = []
            bundle["agent"].update(tool="offline_synthetic_harness", model="not_a_real_agent")
            bundle["recipe"]["execution"]["concurrency"] = 1
            bundle["sources"] = [{"source_key": "fictional-gaming", "kind": "local", "locator": str(source),
                "metadata": {"language": "en", "community": "Gaming", "domain": "synthetic",
                    "publication_date": None, "publication_date_reason": "fictional_undated_fixture",
                    "constraints": {"content_origin": "synthetic_fixture", "license": "synthetic-test",
                        "permitted_use": "offline_rehearsal", "redistribution": "synthetic_only"}},
                "why_selected": "A declared synthetic fixture for software verification",
                "origin": "researcher_supplied", "search_refs": [], "family_id": "fictional-gaming"}]
            source_declaration = deepcopy(bundle["sources"][0])
            assert harness.tool("submit_plan", bundle=bundle)["valid"]
            review = harness.tool("prepare_review", fetch_remote=False)
            review_id = review["review_id"]
            assert review["ready"] and not review["approval"]
            assert harness.tool("status")["status"]["counts"]["jobs"] == 0
            for section in ("summary", "brief", "recipe", "profile", "costs", "source_plan",
                            "source_provenance", "failures", "pending_sources", "freeze"):
                page = harness.tool("inspect_review", review_id=review_id, section=section, limit=100)
                assert page["review_id"] == review_id and not page.get("preview_only")
                assert page["page"]["next_offset"] is None
            sources = harness.tool("review_sources", review_id=review_id, limit=1)
            assert len(sources["sources"]) == 1 and sources["page"]["next_offset"] is None
            long_field = harness.tool("review_text", review_id=review_id, section="brief",
                                      json_pointer="/research_question", offset=0, length=12000)
            assert long_field["complete_value"] and long_field["next_offset"] is None
            harness.tool("approve_review", review_id=review_id, researcher_approved=True,
                         approval_reference="Synthetic test decision after full harness review; not a real researcher approval")
            harness.tool("collect", review_id=review_id, max_jobs=1)
            paused = harness.wait_collection()
            assert paused["status"]["jobs"]["done"] == 1 and paused["status"]["jobs"]["pending"] > 0
            # The installed connection is reused in a new session. The collector
            # resumes the selected study; there is no browser or JSON handoff.
            harness.close()
            harness = SyntheticHarness(connection, workspace)
            harness.tool("open_study", slug=slug)
            harness.tool("collect", review_id=review_id)
            completed = harness.wait_collection()
            expected_jobs = 2 if mode == "broad" else 4
            assert completed["status"]["jobs"] == {"done": expected_jobs}
            records = harness.tool("records", limit=100)["records"]
            assert len(records) == 4
            assert len([r for r in records if r["observed_text"] == "anchor"]) == 2
            record = next(r for r in records if r["observed_text"] == "moonstep")
            detail = harness.tool("inspect_record", record_id=record["record_id"], limit=100)
            occurrence = detail["occurrences"][0]
            excerpt = harness.tool("inspect_source", source_id=occurrence["source_id"],
                                   offset=occurrence["start"], length=occurrence["end"] - occurrence["start"])
            assert excerpt["excerpt"]["text"] == occurrence["observed_text"] == "moonstep"
            suggestion = harness.tool("annotate", record_id=record["record_id"], status="needs_review",
                                     note="Synthetic model suggestion for a harness test")
            assert not suggestion["changes_human_review_status"]
            annotation = harness.tool("annotate", record_id=record["record_id"], status="approved",
                annotation_origin="human_relay", researcher_approved=True,
                approval_reference="Synthetic annotation test decision; not actual human evaluation")
            harness.tool("undo_annotation", annotation_id=annotation["annotation_id"],
                researcher_approved=True, approval_reference="Synthetic undo test decision")
            release = harness.tool("release", name="harness-v1")
            assert release["audit"]["integrity_passed"]
            export_path = Path(release["out"])
            before = hashes(export_path)
            again = harness.tool("release", name="harness-v1")
            assert again["version_id"] == release["version_id"] and before == hashes(export_path)
            cases.append({"mode": mode, "slug": slug, "review_id": review_id,
                "version_id": release["version_id"], "completed_fake_jobs": expected_jobs,
                "grounded_records": 4, "distinct_anchor_senses": 2, "full_review_in_harness": True,
                "reconnected_and_resumed": True, "annotations_reversible": True,
                "exports_byte_identical": True, "integrity_passed": True})
        # A harness must expose unusable sources too, even when there is no
        # captured corpus from which to create a collection-review ID.
        problems = []
        bad_pdf = corpus / "malformed.pdf"
        bad_pdf.write_bytes(b"%PDF-1.0\nThis is a deliberately malformed synthetic PDF.\n")
        for slug, kind, locator, expected_state in (
                ("pending-url", "url", "https://example.org/fictional", "pending"),
                ("failed-pdf", "local", str(bad_pdf), "failed")):
            harness.tool("create_study", slug=slug)
            setup = harness.tool("prepare_study", brief={"research_question": "Inspect this synthetic source problem before collection.",
                "local_roots": [str(corpus)], "domains": ["example.org"], "communities": ["Gaming"],
                "model_profile": "fake", "budget_usd": 0, "max_sources": 1})
            bundle = deepcopy(setup["starter_bundle"])
            bundle["unresolved_questions"] = []
            declaration = deepcopy(source_declaration)
            declaration.update(source_key=slug, kind=kind, locator=locator, family_id=slug)
            bundle["sources"] = [declaration]
            validation = harness.tool("submit_plan", bundle=bundle)
            assert validation["valid"]
            review = harness.tool("prepare_review", fetch_remote=False)
            assert not review["ready"] and review["review_id"] is None
            chunks, offset = [], 0
            while True:
                detail = harness.tool("inspect_plan", plan_sha256=validation["bundle_sha256"],
                                      section="ingestion", offset=offset, length=12000)
                assert detail["inspection_only"]
                chunks.append(detail["text"])
                if detail["next_offset"] is None:
                    break
                offset = detail["next_offset"]
            assert expected_state in "".join(chunks)
            assert harness.tool("status")["status"]["counts"]["jobs"] == 0
            problems.append({"source_kind": kind, "state": expected_state,
                             "visible_inside_harness": True, "extraction_jobs": 0})
        catalog = harness.tool("list_studies", limit=100)
        assert len(catalog["studies"]) == 4
        for case in cases:
            harness.tool("open_study", slug=case["slug"])
            assert harness.tool("status")["status"]["jobs"]["done"] == case["completed_fake_jobs"]
        result = {"package_version": quarry.__version__, "installed_module": str(quarry.__file__),
            "origin": "synthetic_installed_harness_rehearsal", "configured_hosts": list(connections),
            "project_local_configuration_idempotent": True, "same_connection_multiple_studies": True,
            "browser_required": False, "cases": cases, "source_problem_cases": problems,
            "paid_requests": 0, "external_agent_calls": 0,
            "limits": "Generated client configurations and actual stdio tools are tested; no live Claude/Codex account or human usability claim."}
        (out / "acceptance_report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        if harness.process.poll() is None:
            harness.close()


if __name__ == "__main__":
    main()
