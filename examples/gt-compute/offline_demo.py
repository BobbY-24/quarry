"""Rehearse durable cluster collection without Slurm, GPUs, agents or network.

The scheduler and provider below are explicit synthetic test doubles. They verify
software contracts, not GT access, model quality, throughput or student usability.
Review this file and run it in the finite OS isolation from docs/development/reproduce.md.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import sys

from termfinder import Project, FakeProvider, __version__
from termfinder.cluster import file_sha256
from termfinder.cluster_worker import run_bundle
from termfinder.config import experts
from termfinder.workflow import prepare_review, approve_review, release_dataset


class FakeScheduler:
    """In-memory receipts only; never invokes a process or reads credentials."""

    def __init__(self):
        self.states = {}
        self.submissions = []
        self.cancellations = []

    def submit(self, script_path, job_name):
        script = Path(script_path).read_text(encoding="utf-8")
        assert "termfinder.cluster_worker" in script
        scheduler_id = str(1000 + len(self.submissions))
        self.submissions.append({"scheduler_job_id": scheduler_id, "job_name": job_name})
        self.states[scheduler_id] = "pending"
        return scheduler_id

    def status(self, job_id):
        return {"state": self.states[job_id]}

    def cancel(self, job_id):
        self.cancellations.append(job_id)
        self.states[job_id] = "cancelled"


def site_profile(project, durable):
    executable = Path(sys.executable).resolve()
    return {
        "schema_version": "quarry-cluster-v1", "name": "synthetic-offline-site",
        "account": "synthetic-account", "partition": "synthetic-partition", "qos": None,
        "gpus": 1, "cpus": 1, "memory_gb": 1, "walltime_seconds": 600,
        "checkpoint_seconds": 5, "shutdown_grace_seconds": 240,
        "max_submissions": 3, "max_gpu_hours": 0.5,
        "scratch_env": "TMPDIR", "durable_root": str(durable),
        "runtime": {"python_executable": str(executable),
            "python_sha256": file_sha256(executable), "runtime_id": "synthetic-installed-python",
            "runtime_reference": "Offline rehearsal uses the inspected current interpreter"},
        "model_artifacts": [{"model_alias": alias, "checkpoint_id": "synthetic-fixture-" + alias,
            "sha256": "0" * 64, "quantization": None} for alias in project.profile["models"]],
        "configuration_reference": "Synthetic resources only: no real allocation or model artifacts",
    }


def rehearse(root, mode):
    case = root / mode
    corpus, durable, scratch = (case / name for name in ("corpus", "durable", "node-local"))
    for path in (corpus, durable, scratch):
        path.mkdir(parents=True, mode=0o700)
    fixtures = files("termfinder").joinpath("fixtures")
    paths = []
    for name in ("jargon.txt", "broken.pdf"):
        target = corpus / name
        content = fixtures.joinpath(name).read_bytes()
        if name == "jargon.txt":
            content = "😀 Café — synthetic Unicode note.\n\n".encode("utf-8") + content
        target.write_bytes(content)
        paths.append(target)
    project = Project(case / "control-study")
    setup = project.prepare_agent_setup({
        "research_question": "Which medical/scientific terms occur in these synthetic notes?",
        "data_type": "term", "starter_recipe": "jargon", "mode": mode,
        "model_profile": "fake", "max_sources": 2, "budget_usd": 0,
        "languages": ["en"], "communities": ["synthetic-guide"], "local_roots": [str(corpus)],
    })
    bundle = deepcopy(setup["starter_bundle"])
    bundle["agent"].update(tool="offline_scripted_surrogate", model="not_a_real_agent")
    bundle["unresolved_questions"] = []
    bundle["recipe"]["execution"]["concurrency"] = 1
    bundle["sources"] = [{"source_key": "synthetic-" + str(index), "kind": "local",
        "locator": str(path), "metadata": {"language": "en", "community": "synthetic-guide",
            "domain": "synthetic-medical", "publication_date": None,
            "publication_date_reason": "synthetic_undated_fixture",
            "constraints": {"content_origin": "synthetic_fixture", "license": "synthetic_test",
                "permitted_use": "offline_rehearsal", "redistribution": "synthetic_only"}},
        "why_selected": "Synthetic jargon fixture or deliberate parser-failure fixture",
        "origin": "researcher_supplied", "search_refs": [], "family_id": "synthetic-family-" + str(index)}
        for index, path in enumerate(paths)]
    assert project.validate_agent_bundle(bundle)["valid"]
    review = prepare_review(project, bundle, fetch_remote=False)
    assert project.store.count("jobs") == 0
    assert Path(review["freeze"]["out"]).is_dir()
    # Synthetic recorded approval: this is not a real human-study decision.
    approve_review(project, review["review_id"], approval_origin="agent_relay",
        approval_reference="Synthetic rehearsal approval, not research authorization")
    project.configure_cluster(site_profile(project, durable))
    # Guided plans receive a study-specific recipe ID. Bind the reviewed jargon
    # fixture script to that ID while preserving each model-specific discovery.
    expectations = [deepcopy(item) for item in json.loads(
        fixtures.joinpath("expectations.json").read_text(encoding="utf-8"))
        if "jargon" in item.get("recipe_ids", [])]
    assert {item["expression"] for item in expectations} == {
        "Heteroplasmy", "Retrieval-augmented generation", "biomarker", "PCR"}
    for item in expectations:
        item["recipe_ids"] = [project.recipe["id"]]
    controller = project.cluster()
    resource_review = controller.prepare(review["review_id"])
    cluster_review_id = resource_review["cluster_review_id"]
    scheduler = FakeScheduler()
    permissions = {"human_approved": True, "allow_execution": True,
        "allow_paid": False, "scheduler": scheduler,
        "approval_reference": "Synthetic finite resource decision for offline verification"}

    cancelled = controller.submit(cluster_review_id, **permissions)
    controller.cancel(cancelled["job_id"], scheduler=scheduler)
    assert controller.status(cancelled["job_id"], scheduler=scheduler)["job"]["state"] == "cancelled"

    interrupted = controller.resume(cluster_review_id, **permissions)
    first_provider = FakeProvider(expectations=expectations)
    run_bundle(resource_review["bundle"], interrupted["job_id"], execute=True,
        provider=first_provider, max_jobs=1, scratch_root=scratch)
    partial = controller.status(interrupted["job_id"])["job"]
    assert partial["checkpoint"] and partial["state"] == "partial"
    assert len(first_provider.calls) == 1

    # New process/object surrogate: durable receipts survive the prior connection.
    project = Project(case / "control-study")
    controller = project.cluster()
    assert len(controller.status()["jobs"]) == 2
    resumed = controller.resume(cluster_review_id, **permissions)
    second_provider = FakeProvider(expectations=expectations)
    run_bundle(resource_review["bundle"], resumed["job_id"], execute=True,
        provider=second_provider, scratch_root=scratch)
    calls = len(scheduler.submissions)
    try:
        controller.resume(cluster_review_id, **permissions)
    except ValueError as error:
        assert "budget exhausted" in str(error)
    else:
        raise AssertionError("A fourth allocation escaped the finite cap")
    assert len(scheduler.submissions) == calls
    controller.import_result(resumed["job_id"])
    assert controller.import_result(resumed["job_id"])["already_imported"]
    inventory = project.inventory()
    assert len(first_provider.calls) + len(second_provider.calls) == len(experts(project.recipe, project.profile))
    expected_records = {(item["expression"], item["sense"]) for item in expectations}
    assert {(row["observed_text"], row["interpretation"]) for row in inventory["records"]} == expected_records
    assert {(row["expression"], row["sense"]) for row in inventory["terms"]} == expected_records
    assert len(inventory["records"]) == len(expected_records) == 4
    sources = {source["source_id"]: source for source in inventory["sources"]}
    assert any("😀 Café" in source["text"] for source in sources.values())
    for occurrence in inventory["occurrences"]:
        text = sources[occurrence["source_id"]]["text"]
        assert text[occurrence["start"]:occurrence["end"]] == occurrence["expression"]
        assert occurrence["start"] == text.index(occurrence["expression"])
        assert text[occurrence["context_start"]:occurrence["context_end"]] == occurrence["context"]
        if occurrence["expression"] == "PCR":
            assert all(item["expert_id"].startswith("glm-") for item in occurrence["provenance"])
        elif occurrence["expression"] == "biomarker":
            assert all(item["expert_id"].startswith("deepseek-") for item in occurrence["provenance"])
    record_id = inventory["records"][0]["record_id"]
    annotation = project.annotate(record_id, "needs_review", "Synthetic reversible annotation")
    project.undo_annotation(annotation)
    assert all(row["review_status"] == "unreviewed" for row in project.inventory()["records"])
    failures = project.status()["failures"]
    assert failures and {item["locator"] for item in failures} == {str(paths[1])}
    assert all(item["reason"] == "pdf_parse_failed" for item in failures)

    released = release_dataset(project, "synthetic-gt-v1")
    out = Path(released["out"])
    exported = {path.name: path.read_bytes() for path in out.iterdir() if path.is_file()}
    release_dataset(project, "synthetic-gt-v1", version_id=released["version_id"])
    assert exported == {path.name: path.read_bytes() for path in out.iterdir() if path.is_file()}
    return {"mode": mode, "cluster_review_id": cluster_review_id,
        "records": len(inventory["records"]), "first_checkpoint_completed_requests": len(first_provider.calls),
        "fake_requests": len(first_provider.calls) + len(second_provider.calls),
        "fake_submissions": len(scheduler.submissions), "scheduler_commands_executed": 0,
        "complete_source_packets_frozen_before_extraction": True,
        "gpu_jobs_launched": 0, "paid_requests": 0, "external_agent_calls": 0,
        "cancelled_and_reconnected": True, "resumed_without_duplicate_completed_calls": True,
        "visible_parsing_failures": project.status()["failure_count"],
        "annotations_reversible": True, "exports_byte_identical": True,
        "finite_allocation_cap_enforced": True, "version_id": released["version_id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--mode", choices=("broad", "specialists"), help="Omit to rehearse both on the same fixtures")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {"package_version": __version__, "origin": "synthetic_offline_cluster_rehearsal",
        "cases": [rehearse(args.out.resolve(), mode) for mode in ([args.mode] if args.mode else ("broad", "specialists"))],
        "limitations": "No real Slurm, GT allocation, model server, agent, throughput or quality measurement."}
    (args.out / "acceptance_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
