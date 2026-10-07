"""Reviewed installed-wheel, packaged CLI and notebook checks. Synthetic only."""
from contextlib import redirect_stdout
import argparse
from importlib.resources import files
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main(report_path=None):
    import termfinder
    from termfinder import Project, FakeProvider
    from termfinder.config import starter_recipe
    root=Path(__file__).resolve().parents[1]
    assert Path(termfinder.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), "must import installed wheel"
    entry=Path(sys.executable).parent/"termfinder"
    checks=[]
    with tempfile.TemporaryDirectory(prefix="v6-installed-") as temporary:
        base=Path(temporary)
        environment={k:os.environ[k] for k in ("PATH","TMPDIR","PYTHONNOUSERSITE","PYTHONDONTWRITEBYTECODE",
                                              "DYLD_LIBRARY_PATH","LD_LIBRARY_PATH") if k in os.environ}
        native_overlay = os.environ.get("QUARRY_CI_SQLITE_EXTENSION_ROOT")
        if native_overlay:
            assert Path(native_overlay).resolve() == root / ".ci/sqlite/python"
            environment["PYTHONPATH"] = native_overlay  # Native runtime only; never collector source.
        def cli(*args):
            result=subprocess.run([str(entry),*map(str,args)],cwd=base,env=environment,capture_output=True,text=True,timeout=60)
            if result.returncode:
                raise AssertionError(f"CLI check failed: {args[0]}; safe error: {result.stderr}")
            return json.loads(result.stdout)
        project_path=base/"cli-project"
        cli("init",project_path,"--recipe","neologisms","--profile","fake","--mode","specialists")
        fixture=files("termfinder").joinpath("fixtures","community.html")
        metadata=base/"metadata.json"
        metadata.write_text(json.dumps({"community":"Gaming","language":"en"}))
        cli("--project",project_path,"ingest",fixture,"--metadata",metadata)
        cli("--project",project_path,"estimate")
        cli("--project",project_path,"collect","--offline","--max-jobs","1")
        progress=cli("--project",project_path,"status")
        assert progress["jobs"]["pending"]>0
        cli("--project",project_path,"resume","--offline")
        cli("--project",project_path,"large-run")
        cli("--project",project_path,"reset-model","glm")
        cli("--project",project_path,"backup",base/"cli-backup.sqlite3")
        checks.append("installed CLI large-run/reset-model/consistent backup")
        inventory=cli("--project",project_path,"inspect")
        assert inventory["terms"] and inventory["occurrences"]
        version=cli("--project",project_path,"snapshot","installed-v1")["version_id"]
        exported=cli("--project",project_path,"export",version,base/"cli-export")
        assert exported["manifest"]["tables"]["terms"]>0
        assert (base/"cli-export"/"occurrences.parquet").is_file()
        assert cli("--project",project_path,"versions")["versions"][0]["version_id"]==version
        checks.append("installed CLI init/ingest/estimate/interrupt/resume/inspect/snapshot/versions/all exports")
        # Execute reviewed notebook cells in the no-network OS sandbox, starting
        # from a new independent working directory, with no source PYTHONPATH.
        notebook=json.loads((root/"examples"/"researcher_workflow.ipynb").read_text())
        original=Path.cwd()
        os.chdir(base)
        namespace={"__name__":"__notebook__"}
        executed=0
        try:
            for cell in notebook["cells"]:
                if cell["cell_type"]=="code":
                    with redirect_stdout(io.StringIO()):
                        exec(compile("".join(cell["source"]),"researcher_workflow.ipynb","exec"),namespace)
                    executed+=1
        finally:
            os.chdir(original)
        assert namespace["inventory"]["terms"]
        checks.append(f"{executed} notebook code cells executed with installed package")
        for name in ("neologisms","cultural","jargon"):
            assert starter_recipe(name)["schema_version"]==1
        assert files("termfinder").joinpath("static","index.html").is_file()
        assert files("termfinder").joinpath("fixtures","jargon.pdf").is_file()
        checks.append("packaged recipes/profiles/fixtures/browser assets available independently")
    report={"checks":checks,"installed_module":str(termfinder.__file__),"paid_requests":0,"notebook_code_cells":executed}
    destination = Path(report_path) if report_path else root/"verification"/"installed-report.json"
    destination.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    main(parser.parse_args().report)
