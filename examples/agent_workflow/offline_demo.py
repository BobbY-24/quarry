"""Synthetic handoff/import/collection rehearsal for all four evidence types.

No external assistant, search, credentials or paid APIs are used. The returned
agent objects and provider replies below are explicit test fixtures. They prove
workflow mechanics, not extraction quality or publication suitability.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from termfinder import FakeProvider, Project, Response
from termfinder.agent_setup import write_handoff
from termfinder.evaluation import evaluate

CASES = {
    "term": ("The protocol uses byte-level BPE for tokenization.", "byte-level BPE", "A tokenization method"),
    "idea": ("The proposal suggests preserving original-language evidence for later review.", "preserving original-language evidence for later review", "Preserve evidence before interpretation"),
    "opinion": ("I think bilingual signs make the library more accessible.", "I think bilingual signs make the library more accessible.", "The source expresses support for bilingual signs"),
    "sentence": ("😀 Café appears here. The source retains its exact punctuation.", "The source retains its exact punctuation.", "A selected original sentence"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    root = args.out.resolve()
    reports = []
    for kind, (text, span, interpretation) in CASES.items():
        study = root / kind
        corpus = study / "corpus"
        corpus.mkdir(parents=True)
        source = corpus / "synthetic.md"
        source.write_text(text, encoding="utf-8")
        project = Project(study)
        setup = project.prepare_agent_setup({"data_type": kind, "starter_recipe": "jargon",
            "research_question": f"Which source-supported {kind} units occur in the declared synthetic fixture?",
            "languages": ["en"], "communities": ["synthetic-guide"], "local_roots": [str(corpus)],
            "budget_usd": 0, "max_sources": 2, "mode": "specialists", "model_profile": "fake"})
        write_handoff(setup, study / "handoff")
        bundle = deepcopy(setup["starter_bundle"])
        bundle["unresolved_questions"] = []
        bundle["agent"].update(tool="synthetic_returned_object", model="not_a_real_agent")
        bundle["recipe"]["execution"]["concurrency"] = 1
        bundle["recipe"]["examples"]["positive"][0] = {
            "text": text, "expression": span, "language": "en", "sense": interpretation,
            "reason": "Synthetic positive workflow fixture; adapt the policy for a real study."}
        bundle["sources"] = [{"source_key": "fixture-001", "kind": "local", "locator": str(source),
            "metadata": {"language": "en", "community": "synthetic-guide", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "synthetic_fixture",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test_fixture",
                                "permitted_use": "offline_workflow_verification", "redistribution": "synthetic_only"}},
            "why_selected": "Synthetic acceptance fixture", "origin": "researcher_supplied", "search_refs": [], "family_id": "fixture-family"}]
        (study / "returned-bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validation = project.validate_agent_bundle(bundle)
        assert validation["valid"], validation
        applied = project.apply_agent_bundle(bundle)
        assert len(applied["source_ids"]) == 1 and applied["input_files"]["files"]
        blind = project.freeze_agent_corpus(seed="offline-guide-v1")
        proposal = {"expression": span, "language": "en", "sense": interpretation, "context": text,
                    "start": None, "definition_quote": None, "attributes": {}, "translation": None}
        def response(items):
            return Response(json.dumps({"candidates": items, "coverage_complete": True}, ensure_ascii=False),
                            40, 40, "stop", "synthetic-span-v1")
        provider = FakeProvider([], [response([proposal])] + [response([])] * 3)
        project.collect(provider, max_jobs=1)
        assert project.status()["jobs"].get("pending", 0) > 0
        project = Project(study)
        project.resume(provider)
        inventory = project.inventory()
        assert len(inventory["records"]) == 1
        assert len(inventory["terms"]) == (1 if kind == "term" else 0)
        record = inventory["records"][0]
        aid = project.annotate(record["record_id"], "approved", "Synthetic human-review fixture")
        project.undo_annotation(aid)
        assert project.inventory()["records"][0]["review_status"] == "unreviewed"
        version = project.snapshot("synthetic-extraction-v1")
        audit = project.publication_audit(version)
        assert audit["integrity_passed"], audit
        source_row = inventory["sources"][0]
        gold = [{"source_id": source_row["source_id"], "text_sha256": source_row["text_sha256"], "complete": True,
                 "data_type": kind, "terms" if kind == "term" else "records": [{"record_type": kind,
                     "observed_text": span, "language": "en", "start": text.index(span), "end": text.index(span)+len(span)}]}]
        measured = evaluate(project.dataset(version), gold)
        assert measured["overall"]["recall"] == 1
        # The fabricated gold tests mechanics only; real labels must be
        # independently produced by humans on complete held-out sources.
        exports = [study / "export-a", study / "export-b"]
        for out in exports:
            project.export(version, out)
        assert all(p.read_bytes() == (exports[1] / p.name).read_bytes() for p in exports[0].iterdir())
        reports.append({"data_type": kind, "records": 1, "lexical_terms": len(inventory["terms"]),
                        "blind_corpus_version": blind["version_id"], "version_id": version,
                        "integrity_passed": audit["integrity_passed"], "fake_requests": len(provider.calls),
                        "paid_requests": 0, "exports_byte_identical": True})
    report = {"schema_version": 1, "origin": "synthetic_offline_rehearsal", "cases": reports,
              "limits": "No external agent or real-world quality measurement; synthetic gold proves evaluation mechanics only."}
    (root / "acceptance_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
