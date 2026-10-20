"""Check the saved synthetic project after the manual V6.3 browser rehearsal.

Use under verify_offline.py. No browser actions, network, agent, provider or
credentials are invoked. The only mutation is an idempotent local re-export.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project_path, report = args.project.resolve(), args.report.resolve()
    if not project_path.is_relative_to(root / "verification") or not project_path.is_dir():
        parser.error("Use the named synthetic browser verification project")
    if not report.is_relative_to(root / "verification") or report.exists():
        parser.error("Use a fresh verification report")
    from quarry import Project, __version__
    from quarry.workflow import current_review, release_dataset
    project = Project(project_path)
    assert project.profile["id"] == "fake"
    status, inventory = project.status(), project.inventory()
    assert status["jobs"] == {"done": 4}, status["jobs"]
    assert len(inventory["records"]) == len(inventory["occurrences"]) == 4
    assert len([record for record in inventory["records"] if record["observed_text"] == "anchor"]) == 2
    source_texts = {source["source_id"]: source["text"] for source in inventory["sources"]}
    for occurrence in inventory["occurrences"]:
        assert source_texts[occurrence["source_id"]][occurrence["start"]:occurrence["end"]] == occurrence["observed_text"]
    moonstep = next(record for record in inventory["records"] if record["observed_text"] == "moonstep")
    assert moonstep["review_status"] == "unreviewed"
    annotations = project.store.rows("annotations")
    assert len(annotations) == 1 and not annotations[0]["active"]
    assert annotations[0]["attributes"]["innovation_type"] == "synthetic review"
    review = current_review(project)
    assert review["approval"] and review["ready"]
    versions = project.versions()
    assert len(versions) == 2
    version = next(item["version_id"] for item in versions if item["name"] == "browser-rehearsal-v1")
    out = project_path / "exports" / version
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    jobs_before, runs_before = project.store.count("jobs"), project.store.count("runs")
    release = release_dataset(project, "browser-rehearsal-v1")
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    assert before == after
    assert len(release["files"]) == 44 and len(after) == 45 and "manifest.json" in after
    assert project.store.count("jobs") == jobs_before and project.store.count("runs") == runs_before
    assert release["version_id"] == version and release["audit"]["integrity_passed"]
    wheel = root / "dist" / "nlpx_termfinder-6.3.0-py3-none-any.whl"
    result = {"package_version": __version__, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "origin": "manual_browser_plus_saved_state_verification", "project": str(project_path),
        "review_id": review["review_id"], "version_id": version, "jobs": status["jobs"],
        "records": 4, "verified_evidence_spans": 4, "distinct_anchor_senses": 2,
        "reversed_annotations": 1, "exported_payload_files": 44, "total_files_with_manifest": 45,
        "reexport_byte_identical": True,
        "reexport_created_jobs_or_runs": False, "integrity_passed": True,
        "paid_requests": 0, "external_agent_calls": 0,
        "limits": "Synthetic fixture and scripted MCP plan. Browser interaction observations are documented separately; this state check cannot prove UI actions or field accuracy."}
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
