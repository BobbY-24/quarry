"""Three-recipe comparison smoke test: frozen text, fresh arms, fake providers.

Run from the repository after installation. These measurements test software
mechanics, never the quality of real models or hypotheses about real communities.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
import json
from pathlib import Path

from termfinder import FakeProvider, Project
from termfinder.config import load_profile, starter_recipe
from termfinder.experiments import compare_study, quarry_run
from termfinder.exports import canonical_json

FIXTURES = (("community.html", "en", "Gaming", "synthetic-community", "community"),
            ("cultural.md", "mul", "multilingual-community", "synthetic-cultural", "cultural"),
            ("jargon.txt", "en", "scientific-medical", "synthetic-jargon", "methods-note"),
            ("jargon.pdf", "en", "scientific-medical", "synthetic-jargon", "methods-note"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def gold_packets(sources, labels):
    # Independently authored fixture labels; do not inspect model predictions.
    packets = []
    for source in sources:
        terms = []
        for label in labels.get(Path(source["locator"]).name, []):
            spans, cursor = [], 0
            while (start := source["text"].find(label["expression"], cursor)) >= 0:
                end = start + len(label["expression"])
                spans.append({"start": start, "end": end})
                cursor = end
            assert spans, "Independent fixture gold must occur in frozen source text"
            terms.append({**label, "occurrences": spans})
        packets.append({"source_id": source["source_id"], "text_sha256": source["text_sha256"], "complete": True, "terms": terms})
    return packets


def demonstrate(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    master = Project(out / "master-corpus")
    master.configure(starter_recipe("neologisms"), profile="fake")
    fixture_root = files("termfinder").joinpath("fixtures")
    family_by_filename = {}
    for filename, language, community, domain, family in FIXTURES:
        master.ingest(paths=[fixture_root.joinpath(filename)], metadata={"language": language, "community": community, "domain": domain,
                      "constraints": {"redistribution": "Synthetic demonstration text"}})
        family_by_filename[filename] = family
    frozen = master.dataset(master.snapshot("source-only-before-extraction"))
    assert not frozen["jobs"] and not frozen["occurrences"]
    documents = frozen["sources"]
    assert len(documents) == len(FIXTURES)
    corpus_sources = [{key: source[key] for key in ("source_id", "text", "text_sha256", "domain", "language", "locator")} |
                      {"family_id": family_by_filename[Path(source["locator"]).name]} for source in documents]
    manual = json.loads(Path(__file__).parents[1].joinpath("gold_specs.json").read_text(encoding="utf-8"))
    # File hashes identify this exact engineering fixture implementation.
    code = {name: hashlib.sha256(Path(__file__).parents[2].joinpath("src", "termfinder", name).read_bytes()).hexdigest()
            for name in ("engine.py", "grounding.py", "experiments.py", "evaluation.py")}
    revision = "local-source-sha256:" + hashlib.sha256(canonical_json(code).encode()).hexdigest()
    summary = {"offline": True, "paid_requests": 0, "quality_claim": None,
               "quality_claim_reason": "Synthetic fixtures and fake providers verify comparison mechanics, not research hypotheses.",
               "source_code_sha256": code, "cells": []}
    for name in ("neologisms", "cultural", "jargon"):
        cell = out / name
        cell.mkdir()
        corpus = {"schema_version": "1", "corpus_id": "synthetic-" + name, "data_type": "term", "sources": corpus_sources}
        write(cell / "corpus.json", corpus)
        # Gold is written before any arm executes; these are synthetic exhaustive
        # labels, not a blinded real-human annotation study.
        packets = gold_packets(documents, manual["recipes"][name])
        (cell / "gold.jsonl").write_text("".join(canonical_json(packet) + "\n" for packet in packets), encoding="utf-8")
        arm_reports = []
        for mode in ("broad", "specialists"):
            project = Project(cell / (mode + "-project"))
            recipe = starter_recipe(name)
            recipe["mode"] = mode
            profile = load_profile("fake")
            # Nonzero simulated rates exercise arithmetic without billing.
            for model in profile["models"].values():
                model.update(input_per_million=.1, output_per_million=.2)
            project.configure(recipe, profile=profile)
            # Import already parsed documents: identical master IDs/text, no
            # reacquisition/reparsing, no copied jobs/cache/approval/annotations.
            for document in documents:
                assert project.add_source(document) == document["source_id"]
            first = FakeProvider()
            project.collect(first, max_jobs=1)
            assert len(first.calls) == 1
            if mode == "broad":
                partial = project.dataset(project.snapshot("paused-after-one-request"))
                write(cell / "quarry-broad-partial.json", quarry_run(partial, run_id="quarry-broad-partial", software_revision=revision))
                assert any(j["status"] == "pending" for j in partial["jobs"])
            project = Project(project.path)
            resumed = FakeProvider()
            project.resume(resumed)
            completed = project.dataset(project.snapshot("completed-offline-arm"))
            normalized = quarry_run(completed, run_id="quarry-" + mode, software_revision=revision)
            write(cell / ("quarry-" + mode + ".json"), normalized)
            cached = FakeProvider()
            project.resume(cached)
            assert not cached.calls, "Completed requests must not be dispatched again"
            arm_reports.append({"mode": mode, "calls_before_pause": len(first.calls), "calls_after_resume": len(resumed.calls),
                                "calls_on_completed_resume": len(cached.calls), "snapshot_id": completed["version_id"]})
        study = {"schema_version": "1", "corpus": "corpus.json", "gold": "gold.jsonl",
                 "runs": ["quarry-broad-partial.json", "quarry-broad.json", "quarry-specialists.json"],
                 "unit": "occurrence", "require_sense": False, "bootstrap_samples": 0, "seed": "synthetic-smoke-v1"}
        write(cell / "study.json", study)
        report = compare_study(cell / "study.json")
        assert compare_study(cell / "study.json") == report, "Frozen comparison must reproduce without model requests"
        assert report["runs"][0]["coverage"]["complete_fraction"] < 1
        assert report["runs"][0]["detection"]["overall"]["false_negatives"] > 0
        assert report["runs"][1]["raw_proposals"]["exact_grounding_rate"] is None
        write(cell / "report.json", report)
        summary["cells"].append({"recipe": name, "sources": len(documents), "families": len(set(s["family_id"] for s in corpus_sources)),
                                "arms": arm_reports, "comparison": name + "/report.json",
                                "report_sha256": hashlib.sha256((cell / "report.json").read_bytes()).hexdigest()})
    write(out / "report.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(demonstrate(args.out), ensure_ascii=False, indent=2, sort_keys=True))
