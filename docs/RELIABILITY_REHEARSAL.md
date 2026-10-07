# Install and rehearse the hardened collector

Use a fresh environment with a supported Python 3.11–3.13 and a patched SQLite
runtime. [Compatibility](COMPATIBILITY.md) names the accepted fixes, backup and
rollback procedure. These commands install the reviewed local checkout; the
GitHub default branch is not updated by this local delivery.

```sh
cd quarry
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-build-isolation .
quarry --help
```

Dependency acquisition needs network access. Review and pin the dependencies
before running unfamiliar code. Keep API keys exclusively in the selected
provider environment; the rehearsals below need none. The clean environment
and virtual environment do not replace OS isolation.

## Rehearse the complete researcher workflow offline

Inside the reviewed isolation boundary described in [CI](CI.md):

```sh
python examples/offline_demo.py --out verification/rehearsal-recipes
python examples/simple_workflow_demo.py --out verification/rehearsal-agent
python tools/ci_smoke.py --wheelhouse .ci/wheels --dist .ci/release-dist \
  --report verification/installed-smoke.json
python tools/reliability_load.py --sources 1000 \
  --report verification/reliability-load-1000.json
```

Use fresh output directories. The recipe demonstration exercises all three
starter policies in Broad and Specialists, inspectable exact evidence,
reversible annotations, interruption/resume, visible budgets/failures,
complete-source scoring and frozen exports. The simple workflow demonstration
rehearses the researcher-agent handoff without calling an external agent or
model. The installed smoke expects the fresh wheel and five pinned dependency
wheels used by the release gate. The delivered V6.7 wheel is in
`.ci/release-dist`; the V7.1 carry uses `.ci/dist`. When rebuilding elsewhere,
use the directory containing exactly one freshly built, matching wheel.
These are engineering checks, not extraction
quality or student usability experiments.

For ordinary local CLI use after reviewing the inputs:

```sh
quarry init ./study --profile fake --mode broad
quarry --project ./study ingest src/termfinder/fixtures/community.html \
  --metadata examples/source_metadata.json
quarry --project ./study estimate
quarry --project ./study collect --offline --max-jobs 1
quarry --project ./study doctor
quarry --project ./study resume --offline
quarry --project ./study inspect
quarry --project ./study snapshot offline-v1
quarry --project ./study export VERSION_ID ./frozen-export \
  --formats csv,jsonl,parquet,annotation
```

Replace `VERSION_ID` with the saved ID. Re-export that ID to a new destination
to reproduce its records without inference. A nonempty mismatching or
incomplete destination is refused. [Recovery](RECOVERY.md) explains lost replies,
operation IDs, unknown billing, capacity waits and retained cluster receipts.

## Notebook/API

```python
from pathlib import Path
from importlib.resources import files
from termfinder import Project
from termfinder.config import starter_recipe
from termfinder.sources import parse_document

project = Project(Path("notebook-study"))
project.configure(starter_recipe("cultural"), "fake")
project.add_source(parse_document(
    files("termfinder").joinpath("fixtures", "cultural.md").read_bytes(),
    "text/markdown", "synthetic-cultural.md",
    {"language": "mul", "community": "multilingual-community"},
))
project.collect(max_jobs=1)
project.resume()
print(project.doctor())
page = project.page_inventory(limit=20)
version = project.snapshot("offline-cultural-v1")
project.export(version, "notebook-export", ["csv", "jsonl", "parquet", "annotation"])
```

The fake provider recognizes packaged synthetic fixtures. Real deployment
uses the researcher's configured HTTP or reviewed process adapter and explicit
execution authorization. Trusted notebook callbacks must return cooperatively;
reviewed process adapters provide the supported hard transport deadline.

[Measured envelope](RELIABILITY_RESULTS.md) · [Operator runbook](RECOVERY.md) ·
[GT pilot plan](STRESS_TESTS.md#georgia-tech-stress-pilot-plan-only)
