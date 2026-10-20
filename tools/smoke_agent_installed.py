"""Reviewed installed-wheel agent API, example briefs and notebook smoke check.

Execute only in the documented credential-free OS sandbox. All source material
is synthetic; no external assistant, search or model service is contacted.
"""
from contextlib import redirect_stdout
from copy import deepcopy
import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("verification/agent-installed-report.json"))
    args = parser.parse_args()
    report_path = args.report.resolve()
    root = Path(__file__).resolve().parents[1]
    if not report_path.is_relative_to(root / "verification") or report_path.exists():
        parser.error("Use a fresh report path inside V6's verification directory.")
    import quarry
    from quarry import Project
    assert Path(quarry.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), "Import the installed wheel"
    assert quarry.__version__ == "6.2.0"
    results = []
    with tempfile.TemporaryDirectory(prefix="v6-agent-installed-") as temporary:
        base = Path(temporary)
        corpus = base / "corpus"
        corpus.mkdir()
        source = corpus / "synthetic.txt"
        source.write_text("A synthetic complete source for configuration checks.", encoding="utf-8")
        for path in sorted((root / "examples/agent_workflow").glob("*.brief.json")):
            brief = json.loads(path.read_text())
            brief["local_roots"] = [str(corpus)]
            project = Project(base / path.stem)
            setup = project.prepare_agent_setup(brief)
            bundle = deepcopy(setup["starter_bundle"])
            bundle["unresolved_questions"] = []
            bundle["sources"] = [{"source_key": "synthetic", "kind": "local", "locator": str(source),
                "metadata": {"language": brief["languages"][0], "community": brief["communities"][0],
                    "domain": "synthetic-configuration", "publication_date": None,
                    "publication_date_reason": "synthetic_undated", "constraints": {
                        "content_origin": "synthetic_fixture", "license": "test-only",
                        "permitted_use": "offline_configuration_check", "redistribution": "test-only"}},
                "why_selected": "Synthetic configuration check", "origin": "researcher_supplied",
                "search_refs": [], "family_id": "synthetic"}]
            report = project.validate_agent_bundle(bundle)
            assert report["valid"], (path.name, report)
            applied = project.apply_agent_bundle(bundle)
            assert len(applied["source_ids"]) == 1
            assert (Path(applied["input_files"]["out"]) / "recipe.json").is_file()
            assert project.freeze_agent_corpus()["source_count"] == 1
            results.append({"example": path.name, "data_type": brief["data_type"],
                            "configured": True, "provider_requests": 0})
        notebook = json.loads((root / "examples/agent_workflow/researcher_agent_workflow.ipynb").read_text())
        original = Path.cwd()
        os.chdir(base)
        namespace = {"__name__": "__notebook__"}
        executed = 0
        try:
            for cell in notebook["cells"]:
                if cell["cell_type"] == "code":
                    with redirect_stdout(io.StringIO()):
                        exec(compile("".join(cell["source"]), "researcher_agent_workflow.ipynb", "exec"), namespace)
                    executed += 1
        finally:
            os.chdir(original)
        assert namespace["audit"]["integrity_passed"]
        report = {"package_version": quarry.__version__, "installed_module": str(quarry.__file__),
                  "briefs": results, "notebook_code_cells": executed, "paid_requests": 0,
                  "external_agent_calls": 0,
                  "limit": "Scripted handoff and synthetic source test mechanics; no field accuracy measurement."}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
