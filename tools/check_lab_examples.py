"""Offline end-to-end checks of the public-research guide's named examples.

Run only through the reviewed offline verification sandbox. These checks use
synthetic texts, the installed package and a provider that must never be called.
They validate workflow/configuration, not extraction quality or paper results.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import termfinder
from termfinder import Project
from termfinder.config import experts, load_profile, load_recipe
from termfinder.sources import in_domain_scope


class MustNotDispatch:
    paid = False
    cache_identity = "lab-guide-no-dispatch-check-v1"

    def __init__(self):
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Zero-budget guide preparation must not dispatch")


def main():
    root = Path(__file__).resolve().parents[1]
    examples = root / "examples" / "lab_recipes"
    catalog = json.loads((examples / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["students"]) == 11
    assert len({s["slug"] for s in catalog["students"]}) == 11
    assert "/src/" not in str(termfinder.__file__), "Use the independently installed package"
    results = []

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "termfinder", *map(str, args)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=True, timeout=30,
        )
        return json.loads(result.stdout)

    with tempfile.TemporaryDirectory(prefix="v6-lab-guide-") as temp:
        base = Path(temp)
        for student in catalog["students"]:
            recipe_path = examples / student["recipe"]
            recipe = load_recipe(recipe_path)
            metadata = json.loads((examples / student["metadata"]).read_text(encoding="utf-8"))
            profile = load_profile(recipe["model_profile"])
            assert recipe["execution"]["budget_usd"] == 0
            assert all(v == 0 for v in recipe["execution"]["stage_budgets"].values())
            assert recipe["discovery"]["enabled"] is False
            assert recipe["source_scope"] == {"domains": ["local-only.invalid"], "local": True}
            assert not in_domain_scope("https://example.org/source", recipe["source_scope"])
            assert metadata["community"] == student["community"]
            assert metadata["community"] in recipe["communities"]
            assert all(metadata["community"] in lens["communities"] for lens in recipe["specialist_lenses"])
            for group in recipe["examples"].values():
                for example in group:
                    assert example["expression"] in example["text"]
                    assert example["reason"].startswith("SYNTHETIC GUIDE EXAMPLE.")

            # A local copy of the explicitly synthetic positive example proves
            # supported ingestion/metadata/routing; it is not research evidence.
            text = "# Synthetic guide workflow check\n\n" + recipe["examples"]["positive"][0]["text"] + "\n"
            document = base / (student["slug"] + ".md")
            document.write_text(text, encoding="utf-8")
            probe_metadata = deepcopy(metadata)
            probe_metadata["retrieved_at"] = "2026-10-05T00:00:00Z"
            probe_metadata["constraints"].update(content_origin="synthetic_verification_fixture",
                                                   content_origin_reason=None)
            metadata_path = base / (student["slug"] + ".metadata.json")
            metadata_path.write_text(json.dumps(probe_metadata, ensure_ascii=False), encoding="utf-8")
            source_ids = []
            for mode in ("broad", "specialists"):
                project_path = base / (student["slug"] + "-" + mode)
                configured = cli("init", project_path, "--recipe", recipe_path,
                                 "--profile", "glm-deepseek", "--mode", mode)
                assert configured["mode"] == mode
                cli("--project", project_path, "ingest", document, "--metadata", metadata_path)
                estimate = cli("--project", project_path, "estimate")
                project = Project(project_path)
                sources = project.inventory()["sources"]
                assert len(sources) == 1 and not project.source_exclusion(sources[0])
                assert sources[0]["text"] == text
                assert sources[0]["constraints"]["content_origin"] == "synthetic_verification_fixture"
                assert sources[0]["publication_date"] is None
                assert sources[0]["publication_date_reason"]
                source_ids.append(sources[0]["source_id"])
                passes = experts(project.recipe, project.profile)
                expected = 2 if mode == "broad" else 4
                assert len(passes) == expected
                assert len(estimate["scenarios"][0]["passes"]) == expected
                assert estimate["assumptions"]["specialist_routing"] == "observed metadata"
                assert estimate["range_usd"][0] > 0

                # Freeze a blind source packet before any collection attempt.
                version = cli("--project", project_path, "snapshot", "blind-corpus-v1")["version_id"]
                out_a = base / (student["slug"] + "-" + mode + "-export-a")
                out_b = base / (student["slug"] + "-" + mode + "-export-b")
                formats = "csv,jsonl,parquet,annotation"
                cli("--project", project_path, "export", version, out_a, "--formats", formats)
                packet = json.loads((out_a / "annotation_sources.jsonl").read_text(encoding="utf-8"))
                assert packet["text"] == text and packet["terms"] == []
                assert packet["complete"] is False and packet["text_sha256"] == sources[0]["text_sha256"]
                assert (out_a / "annotation_candidates.jsonl").read_bytes() == b""

                # Exercise zero-budget stop and reopen/resume with no transport.
                provider = MustNotDispatch()
                project.collect(provider)
                stopped = project.status()
                assert stopped["stop_reason"] == "spending_budget_reservation_exhausted"
                assert stopped["jobs"].get("pending") == expected
                reopened = Project(project_path)
                reopened.resume(provider)
                assert reopened.status()["jobs"].get("pending") == expected
                assert provider.calls == 0 and reopened.inventory()["costs"] == []
                assert reopened.inventory()["terms"] == []

                # Later run records cannot alter an earlier immutable version.
                cli("--project", project_path, "export", version, out_b, "--formats", formats)
                names = sorted(p.name for p in out_a.iterdir())
                assert names == sorted(p.name for p in out_b.iterdir())
                assert all((out_a / name).read_bytes() == (out_b / name).read_bytes() for name in names)
                results.append({"student": student["name"], "mode": mode,
                                "routed_passes": expected,
                                "estimated_usd": estimate["range_usd"],
                                "pending_jobs": expected, "provider_calls": provider.calls,
                                "byte_identical_export_files": len(names)})
            assert source_ids[0] == source_ids[1], "Comparison arms must ingest identical evidence"

    inputs = [examples / "catalog.json", root / "docs" / "LAB_PROTOCOL.md",
              root / "docs" / "NLPX_STUDENT_GUIDE.md", examples / "README.md"]
    inputs += [examples / s[key] for s in catalog["students"] for key in ("recipe", "metadata")]
    report = {"schema_version": 1, "checked_at": "2026-10-05",
              "installed_module": str(termfinder.__file__), "students": 11,
              "mode_workflows": len(results), "provider_calls": 0, "results": results,
              "checks": ["strict recipe schema and literal labeled synthetic examples",
                         "matching metadata and Broad/Specialists routing",
                         "CLI init/ingest/estimate/snapshot/export with installed package",
                         "null date with reason and retained source-origin metadata",
                         "blind complete-source packets before extraction",
                         "zero-dollar stop, visible pending jobs, reopen/resume without dispatch",
                         "identical source IDs between mode arms",
                         "CSV/JSONL/Parquet/annotation re-export bytes identical after later runs"],
              "limitations": "Synthetic workflow checks only; no model extraction-quality or named-paper reproduction claims.",
              "input_sha256": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
    (root / "verification" / "lab-examples-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("students", "mode_workflows", "provider_calls", "checks")}, indent=2))


if __name__ == "__main__":
    main()
