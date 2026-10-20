"""Rehearse the guided student workflow with synthetic sources and fake replies.

The researcher-facing experience is describe, approve, inspect and export. This
script is a visible surrogate for the student's coding agent: no real agent,
network, credential or paid provider is used. It measures software contracts,
not usability, recall or semantic accuracy. Run in the reviewed OS sandbox.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path

from quarry import Project, FakeProvider, Response, __version__
from quarry.config import experts
from quarry.workflow import prepare_review, approve_review, run_review, release_dataset

CASES = {
    "term": ("The community calls a brief pause moonstep.", "moonstep", "A brief pause"),
    "idea": ("The proposal recommends preserving original-language evidence for review.",
             "preserving original-language evidence for review", "Preserve original evidence"),
    "opinion": ("Mira wrote: I prefer bilingual signs in the library.",
                "I prefer bilingual signs in the library.", "A quoted preference for bilingual signs"),
    "sentence": ("😀 Café is mentioned here. Keep this source sentence exactly.",
                 "Keep this source sentence exactly.", "A selected original sentence"),
}


def rehearse(root, kind, mode):
    text, span, interpretation = CASES[kind]
    study = root / (kind + "-" + mode)
    corpus = study / "corpus"
    corpus.mkdir(parents=True)
    source = corpus / "fictional.md"
    source.write_text(text, encoding="utf-8")
    project = Project(study)
    setup = project.prepare_agent_setup({"data_type": kind,
        "research_question": f"Which explicitly expressed {kind} units appear in this synthetic source?",
        "local_roots": [str(corpus)], "languages": ["en"], "communities": ["synthetic-guide"],
        "mode": mode, "model_profile": "fake", "budget_usd": 0, "max_sources": 1})
    # A scripted agent builds the input. The researcher does not maintain its
    # component recipe, metadata, sampling or evaluation JSON files.
    bundle = deepcopy(setup["starter_bundle"])
    bundle["unresolved_questions"] = []
    bundle["agent"].update(tool="offline_scripted_surrogate", model="not_a_real_agent")
    bundle["recipe"]["execution"]["concurrency"] = 1
    bundle["sources"] = [{"source_key": "fixture", "kind": "local", "locator": str(source),
        "metadata": {"language": "en", "community": "synthetic-guide", "domain": "synthetic",
            "publication_date": None, "publication_date_reason": "fictional_undated_source",
            "constraints": {"content_origin": "synthetic_fixture", "license": "synthetic_test",
                "permitted_use": "offline_rehearsal", "redistribution": "synthetic_only"}},
        "why_selected": "Declared synthetic workflow fixture", "origin": "researcher_supplied",
        "search_refs": [], "family_id": "fixture-family"}]
    assert project.validate_agent_bundle(bundle)["valid"]
    review = prepare_review(project, bundle)
    assert project.store.count("jobs") == 0
    approved = approve_review(project, review["review_id"])
    candidate = {"expression": span, "language": "en", "sense": interpretation,
        "context": text, "start": None, "definition_quote": None, "translation": None, "attributes": {}}
    count = len(experts(project.recipe, project.profile))
    replies = [Response(json.dumps({"candidates": [candidate] if n == 0 else [],
        "coverage_complete": True}, ensure_ascii=False), 40, 40, "stop", "synthetic-guided-v1")
        for n in range(count)]
    provider = FakeProvider([], replies)
    run_review(project, review["review_id"], provider=provider, max_jobs=1)
    assert project.status()["jobs"].get("pending", 0) > 0
    project = Project(study)
    run_review(project, review["review_id"], provider=provider)
    assert len(provider.calls) == count
    inventory = project.inventory()
    record = inventory["records"][0]
    assert len(inventory["records"]) == 1
    assert len(inventory["terms"]) == (1 if kind == "term" else 0)
    occurrence = inventory["occurrences"][0]
    assert text[occurrence["start"]:occurrence["end"]] == span
    annotation = project.annotate(record["record_id"], "approved", "Synthetic reviewer event")
    project.undo_annotation(annotation)
    assert project.inventory()["records"][0]["review_status"] == "unreviewed"
    release = release_dataset(project, "guided-rehearsal")
    version = release["version_id"]
    assert project.publication_audit(version)["integrity_passed"]
    exported = study / "exports" / version
    original = {p.name: p.read_bytes() for p in exported.iterdir() if p.is_file()}
    project.annotate(record["record_id"], "needs_review", "Later events must not alter this release")
    calls_before = len(provider.calls)
    release_dataset(project, "guided-rehearsal", version_id=version)
    assert original == {p.name: p.read_bytes() for p in exported.iterdir() if p.is_file()}
    assert len(provider.calls) == calls_before
    return {"data_type": kind, "mode": mode, "review_id": review["review_id"],
        "version_id": version, "records": 1, "lexical_terms": len(inventory["terms"]),
        "fake_requests": len(provider.calls), "paid_requests": 0,
        "prepared_without_jobs": True, "resumed_without_duplicate_calls": True,
        "annotations_reversible": True, "exports_byte_identical": True,
        "integrity_passed": True, "approved": bool(approved)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    result = {"package_version": __version__, "origin": "synthetic_offline_rehearsal",
        "cases": [rehearse(args.out.resolve(), kind, mode) for kind in CASES for mode in ("broad", "specialists")],
        "external_agent_calls": 0, "paid_requests": 0,
        "limits": "Scripted plans and fake replies verify mechanics, not real student usability, semantic correctness or recall."}
    (args.out / "acceptance_report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
