"""Complete researcher acceptance demonstration; synthetic sources/fake calls only.

Review this file before running it in the documented network/data sandbox.
It never reads credentials or creates scheduled work. All outputs remain under
the explicitly supplied new output directory. No sibling-version imports exist.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
import json
from pathlib import Path
from unittest.mock import patch

from quarry import FakeProvider, Project
from quarry.config import load_profile, load_recipe, starter_recipe
from quarry.discovery import discover, StaticSearchAdapter
from quarry.evaluation import evaluate, source_splits
from quarry.sources import parse_document


CORPUS = (
    ("community.html", "en", "Gaming", "synthetic-community"),
    ("cultural.md", "mul", "multilingual-community", "synthetic-cultural"),
    ("jargon.txt", "en", "scientific-medical", "synthetic-jargon"),
    ("jargon.pdf", "en", "scientific-medical", "synthetic-jargon"),
)
EXPECTED = {
    "neologisms": {"moonstep", "anchor", "quietstack"},
    "cultural": {"春节", "お花見", "القهوة العربية", "रंगोली", "café circle"},
    "jargon": {"Heteroplasmy", "Retrieval-augmented generation", "biomarker", "PCR"},
}


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _hashes(directory: Path) -> dict:
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _gold(dataset: dict, recipe_name: str, specs: dict) -> list[dict]:
    """Translate independent full-source manual fixture labels to frozen spans.

    The labels come from gold_specs.json, never candidates or model output. Each
    literal occurrence is labeled, including mentions the fake provider omits.
    """
    result = []
    for source in dataset["sources"]:
        text = source["text"]
        labels = specs["recipes"][recipe_name].get(Path(source["locator"]).name, [])
        terms = []
        for label in labels:
            expression = label["expression"]
            spans, cursor = [], 0
            while (start := text.find(expression, cursor)) >= 0:
                spans.append({"start": start, "end": start + len(expression)})
                cursor = start + len(expression)
            if not spans:
                raise AssertionError(f"Manual fixture label not found: {expression!r}")
            terms.append({**label, "occurrences": spans})
        result.append({"source_id": source["source_id"], "text_sha256": source["text_sha256"],
                       "complete": True, "annotator": "synthetic-manual-specification",
                       "terms": terms})
    return result


def demonstrate(out: Path, *, formats=None) -> dict:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    formats = formats or ["csv", "jsonl", "parquet", "annotation"]
    fixture_root = files("quarry").joinpath("fixtures")
    specs_path = Path(__file__).with_name("gold_specs.json")
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    report = {"schema_version": 1, "offline": True, "provider": "synthetic-fake",
              "paid_requests": 0, "quality_claim": None,
              "quality_claim_reason": "Synthetic acceptance is software verification, not field accuracy.",
              "package_file": str(files("quarry")), "projects": [], "checks": []}
    for recipe_name in ("neologisms", "cultural", "jargon"):
        for mode in ("broad", "specialists"):
            directory = out / f"{recipe_name}-{mode}"
            recipe = starter_recipe(recipe_name)
            recipe["mode"] = mode
            load_recipe(recipe)
            project = Project(directory)
            project.configure(recipe, profile="fake")
            _write(directory / "research-recipe.json", recipe)
            for filename, language, community, domain in CORPUS:
                project.ingest(paths=[fixture_root.joinpath(filename)], metadata={
                    "language": language, "community": community, "domain": domain,
                    "constraints": {"redistribution": "Synthetic demonstration text"},
                })
            project.ingest(paths=[fixture_root.joinpath("broken.pdf")], metadata={
                "language": "en", "community": recipe["communities"][0], "domain": "synthetic-failure",
            })
            estimate = project.estimate()
            first_provider = FakeProvider()
            project.collect(first_provider, max_jobs=1)
            assert len(first_provider.calls) == 1, "Bounded collection should dispatch exactly one job."
            interrupted = project.status()
            assert any(job["status"] == "pending" for job in project.inventory()["jobs"]), "Unfinished work must remain pending."
            project = Project(directory)
            resumed_provider = FakeProvider()
            project.resume(resumed_provider)
            inventory = project.inventory()
            assert inventory["terms"], f"Recipe {recipe_name} must collect fixture terms."
            expressions = {term["expression"] for term in inventory["terms"]}
            assert EXPECTED[recipe_name] <= expressions, f"Missing expected grounded expressions: {EXPECTED[recipe_name] - expressions}"
            sources = {source["source_id"]: source for source in inventory["sources"]}
            for occurrence in inventory["occurrences"]:
                source = sources[occurrence["source_id"]]
                assert source["text"][occurrence["start"]:occurrence["end"]] == occurrence["expression"]
                assert occurrence["context"] in source["text"], "Context must be original observed source text."
            if recipe_name == "neologisms":
                senses = {term["sense"] for term in inventory["terms"] if term["expression"] == "anchor"}
                assert len(senses) == 2, "Distinct community senses must survive."
                if mode == "broad":
                    support = {expression: {origin["expert_id"]
                        for occurrence in inventory["occurrences"] if occurrence["expression"] == expression
                        for origin in occurrence["provenance"]} for expression in ("moonstep", "quietstack")}
                    assert support["moonstep"] == {"glm-general"}
                    assert support["quietstack"] == {"deepseek-general"}
            pdf = next(source for source in inventory["sources"] if Path(source["locator"]).name == "jargon.pdf")
            assert {block["page"] for block in pdf["blocks"]} >= {1, 2}, "PDF page locations must be retained."
            term_id = inventory["terms"][0]["term_id"]
            annotation = project.annotate(term_id, "rejected", note="Demonstrate reversible review; synthetic text only.")
            reviewed = project.inventory()
            assert any(term["term_id"] == term_id for term in reviewed["terms"]), "Review cannot delete inventory."
            assert next(term for term in reviewed["terms"] if term["term_id"] == term_id)["review_status"] == "rejected"
            project.undo_annotation(annotation)
            assert next(term for term in project.inventory()["terms"] if term["term_id"] == term_id)["review_status"] == "unreviewed"
            relation = project.relate(term_id, inventory["terms"][1]["term_id"], "alias")
            project.undo_relation(relation)
            assert next(row for row in project.inventory()["relations"] if row["relation_id"] == relation)["active"] is False
            assert len(project.inventory()["terms"]) == len(inventory["terms"])
            version = project.snapshot("offline-acceptance-v1")
            dataset = project.dataset(version)
            assert dataset["failures"], "Malformed PDF must be visible in the dataset."
            gold = _gold(dataset, recipe_name, specs)
            evaluation = evaluate(dataset, gold, heldout_source_ids=[source["source_id"] for source in dataset["sources"]])
            _write(directory / "synthetic-evaluation.json", evaluation)
            with (directory / "complete-source-gold.jsonl").open("w", encoding="utf-8") as handle:
                for packet in gold:
                    handle.write(json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n")
            _write(directory / "source-splits.json", source_splits(dataset["sources"]))
            first, second = directory / "export-one", directory / "export-two"
            # Fail immediately if export attempts either transport.
            with patch("quarry.providers.HTTPProvider.complete", side_effect=AssertionError("Export called a real provider")), \
                 patch("quarry.providers.FakeProvider.complete", side_effect=AssertionError("Export called a fake provider")):
                project.export(version, first, formats=formats)
            project.annotate(term_id, "approved", note="Later annotation must not change the frozen version.")
            with patch("quarry.providers.HTTPProvider.complete", side_effect=AssertionError("Export called a real provider")), \
                 patch("quarry.providers.FakeProvider.complete", side_effect=AssertionError("Export called a fake provider")):
                project.export(version, second, formats=formats)
            assert _hashes(first) == _hashes(second), "Saved version exports must match byte for byte."
            repeated_provider = FakeProvider()
            project.resume(repeated_provider)
            assert not repeated_provider.calls, "Completed collection should not repeat requests."
            _write(directory / "estimate.json", estimate)
            _write(directory / "status.json", project.status())
            report["projects"].append({
                "recipe": recipe_name, "mode": mode, "directory": directory.name,
                "version_id": version, "terms": len(dataset["terms"]),
                "occurrences": len(dataset["occurrences"]), "sources": len(dataset["sources"]),
                "failures": len(dataset["failures"]), "calls_before_pause": len(first_provider.calls),
                "calls_after_resume": len(resumed_provider.calls), "status_after_pause": interrupted,
                "export_files": _hashes(first), "synthetic_evaluation": evaluation["overall"],
            })
    # Cost admission with nonzero simulated rates is observable without billing.
    budget_recipe = starter_recipe("neologisms")
    budget_recipe["execution"]["budget_usd"] = 0.000001
    budget_recipe["execution"]["stage_budgets"] = {stage: 0.000001 if stage == "extraction" else 0.0
                                                       for stage in budget_recipe["execution"]["stage_budgets"]}
    budget_profile = load_profile("fake")
    budget_profile["version"] = "simulated-budget-v1"
    for model in budget_profile["models"].values():
        model["input_per_million"] = 1.0
        model["output_per_million"] = 1.0
    budget = Project(out / "budget-stop")
    budget.configure(budget_recipe, budget_profile)
    budget.ingest(paths=[fixture_root.joinpath("community.html")], metadata={"language": "en", "community": "Gaming"})
    budget_provider = FakeProvider()
    budget.collect(budget_provider)
    assert not budget_provider.calls, "Budget admission should stop before dispatch."
    assert any(job["status"] == "pending" for job in budget.inventory()["jobs"]), "Budget stop must leave unfinished work pending."
    report["budget_stop"] = budget.status()
    discovery_recipe = starter_recipe("neologisms")
    discovery_recipe["discovery"].update(enabled=True, max_sources=2, max_hops=1, max_requests=3)

    class SyntheticFetcher:
        """No transport: return the same synthetic HTML at explicit fake URLs."""
        def __init__(self):
            self.calls = []

        def fetch(self, url, metadata=None):
            self.calls.append(url)
            return parse_document(fixture_root.joinpath("community.html").read_bytes(), "text/html", url,
                                  {"language": "en", "community": "Gaming", **(metadata or {})})

    fetcher = SyntheticFetcher()
    search = StaticSearchAdapter({"schema_version": 1, "results": [
        {"url": "https://outside.invalid/escape"}, {"url": "https://example.org/fake-one"},
    ]})
    discovery = discover(discovery_recipe, fetcher, search_adapter=search,
                         seeds=["https://example.org/fake-one", "https://example.org/fake-two"],
                         decisions_path=out / "discovery-decisions.jsonl")
    assert len(fetcher.calls) == 2 and discovery["requests"] == 3
    assert discovery["stop_reason"] == "source_limit" and discovery["pending"]
    assert any(row["reason"] == "domain_out_of_scope" for row in discovery["decisions"])
    assert all(url.startswith("https://example.org/") for url in fetcher.calls)
    _write(out / "discovery-report.json", discovery)
    report["discovery"] = {"status": discovery["status"], "stop_reason": discovery["stop_reason"],
                           "requests": discovery["requests"], "sources": len(discovery["documents"]),
                           "pending": len(discovery["pending"]), "calls": fetcher.calls}
    report["checks"] = [
        "All three starters validate and configure independently.",
        "The same frozen source fixtures run in Broad and Specialists.",
        "Single-extractor discoveries and distinct literal senses survive.",
        "Unicode expression offsets and original contexts are inspectable; PDF pages survive.",
        "One-job interruption reopens and resumes without repeating completed requests.",
        "Human review and alias links are reversible; grounded inventory survives rejection.",
        "Budget admission stops without paid calls and preserves pending jobs.",
        "Malformed PDF failures remain in snapshots and manifests.",
        "Every requested export format is reproducible from a frozen version.",
        "Independent complete-source labels report synthetic false negatives.",
        "Explicit discovery records source lineage, out-of-scope rejection, and finite pending work without a network transport.",
    ]
    _write(out / "acceptance_report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New local output directory; existing directories are refused")
    parser.add_argument("--formats", default="csv,jsonl,parquet,annotation")
    args = parser.parse_args(argv)
    report = demonstrate(args.out, formats=[part.strip() for part in args.formats.split(",") if part.strip()])
    print(json.dumps({"acceptance_report": str(args.out.resolve() / "acceptance_report.json"),
                      "projects": len(report["projects"]), "checks": report["checks"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
