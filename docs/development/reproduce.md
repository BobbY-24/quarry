# Reproduce the collector

Run from a fresh checkout with a reviewed Python 3.11–3.13 installation and
[patched SQLite](../reliability/compatibility.md). Review the scripts and fixtures
first. These checks use synthetic sources and fake providers; they need no API
credentials, research data, model downloads, or scheduler access.

`tools/ci_offline.py` applies macOS Seatbelt or Linux bubblewrap, probes that
networking and unrelated file reads are denied, and fails closed without the
required isolation. A virtual environment or subprocess timeout alone does not
provide that boundary. See the [CI contract](ci.md) for bounds and platform limits.

## Prepare pinned dependencies

Dependency acquisition is the only networked preparation step below. Obtain
binary wheels for the target platform from the configured package index; inspect
them before executing their code. Linux also needs a reviewed bubblewrap install.
Choose a supported interpreter containing the required SQLite fix.

```sh
QUARRY_PYTHON="$(command -v python3.13)"
QUARRY_BASE_ROOT="$("$QUARRY_PYTHON" -I -S -c 'import sys; print(sys.prefix)')"
mkdir -p .ci/wheels verification/reproduction
env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -m pip --isolated download \
  --disable-pip-version-check --no-cache-dir --only-binary=:all: --no-deps \
  --index-url https://pypi.org/simple --dest .ci/wheels \
  --requirement requirements.txt --requirement requirements-build.txt
env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -m venv .ci/build-runtime
env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -m venv .ci/install-runtime

for runtime in build-runtime install-runtime; do
  env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
    --python "$PWD/.ci/$runtime/bin/python" --runtime-root "$PWD/.ci/$runtime" \
    --base-runtime-root "$QUARRY_BASE_ROOT" \
    --report "verification/reproduction/dependencies-$runtime.json" --timeout 120 \
    -- -m pip --isolated install --no-index --no-deps --no-cache-dir \
    --find-links .ci/wheels --requirement requirements.txt \
    --requirement requirements-build.txt
done
```

Start with empty `.ci/wheels` and `.ci/dist` directories in the fresh checkout.
The smoke check expects the five pinned dependency wheels and exactly one fresh
collector wheel. Keep previous runs in a separate evidence directory; never
overwrite an existing study or treat a missing dependency as a successful check.

## Test source, then the installed wheel

The maintained repository checker validates local Markdown/notebook links. It reads local files only; it does not fetch remote
URLs or execute notebook/example cells.

```sh
env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/build-runtime/bin/python" \
  --runtime-root "$PWD/.ci/build-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --report verification/reproduction/layout.json --timeout 60 \
  -- tools/check_repository.py

env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/build-runtime/bin/python" \
  --runtime-root "$PWD/.ci/build-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --source --report verification/reproduction/source.json --timeout 600 \
  -- -m unittest discover -s tests -q

env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/build-runtime/bin/python" \
  --runtime-root "$PWD/.ci/build-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --report verification/reproduction/build.json --timeout 120 \
  -- -m pip --isolated wheel --no-index --no-deps --no-build-isolation \
  --wheel-dir .ci/dist .

env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/install-runtime/bin/python" \
  --runtime-root "$PWD/.ci/install-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --report verification/reproduction/install.json --timeout 120 \
  -- -m pip --isolated install --no-index --no-deps --find-links .ci/dist nlpx-termfinder

env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/install-runtime/bin/python" \
  --runtime-root "$PWD/.ci/install-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --report verification/reproduction/installed.json --timeout 600 \
  -- -m unittest discover -s tests -q

env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/install-runtime/bin/python" \
  --runtime-root "$PWD/.ci/install-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --report verification/reproduction/smoke-isolation.json --timeout 180 \
  -- tools/ci_smoke.py --wheelhouse .ci/wheels --dist .ci/dist \
  --report verification/reproduction/installed-smoke.json
```

`--source` explicitly enables the reviewed source tree. Its absence in installed
checks prevents that substitution. Wheel checks compare package assets with
source, exercise CLI/API/stdio MCP, reject a synthetic credential marker, and
compare all four export formats byte for byte. Invocation receipts identify the
runtime, isolation probes, limits, file hashes, elapsed time, and exit status.

## Acceptance checks

Run each command through the same launcher using the installed runtime, a fresh
report path, and a finite timeout. For example:

```sh
env -i PATH=/usr/bin:/bin "$QUARRY_PYTHON" -I -S tools/ci_offline.py \
  --python "$PWD/.ci/install-runtime/bin/python" \
  --runtime-root "$PWD/.ci/install-runtime" --base-runtime-root "$QUARRY_BASE_ROOT" \
  --report verification/reproduction/recipes-isolation.json --timeout 600 \
  -- examples/offline_demo.py --out verification/reproduction/recipes
```

| Command after the launcher's `--` | What its evidence checks |
|---|---|
| `examples/offline_demo.py --out verification/reproduction/recipes` | Three starter recipes × both modes, original Unicode spans/PDF pages, singleton and sense retention, reversible annotations, budget/failure visibility, resume, complete-source false negatives, and reproducible exports. |
| `examples/simple_workflow_demo.py --out verification/reproduction/agent` | Terms, ideas, opinions, and sentences in both modes; scripted agent preparation, explicit review, freeze, resume, annotations, and frozen releases. |
| `tools/smoke_installed.py --report verification/reproduction/notebook.json` | Installed CLI and reviewed notebook cells in a fresh working directory. |
| `tools/check_lab_examples.py` | Research-inspired example recipes and metadata validate without paid dispatch. |
| `examples/gt-compute/offline_demo.py --out verification/reproduction/gt` | Synthetic scheduler, reviewed allocation, checkpoint/import, and bounded recovery interfaces. It submits no real GT job. |
| `examples/experiments/offline_demo.py --out verification/reproduction/experiments` | Frozen source/gold comparison mechanics and cached replay on synthetic data. |

The suite also exercises actual bounded process termination, failure isolation,
quota contention, durable operation IDs, truncation recovery, raw-response replay,
and old-project compatibility. Its checked-in V6.6 database and receipt must stay
unchanged; `tools/make_legacy_fixture.py` documents how the old implementation
created it.

Larger bounded checks are separate from routine source tests:

```text
tools/reliability_load.py --sources 1000 --report verification/reproduction/load.json
tools/reliability_mixed.py --report verification/reproduction/mixed.json
```

Use launcher bounds appropriate to the documented workload, up to 900 CPU
seconds and 1,800 wall seconds. [Stress-test instructions](../reliability/stress-tests.md)
explain the parameters and reported limitations.

## Preserve the reproduction record

Record the Git revision, built-wheel/dependency hashes, exact invocation receipts,
and report outcomes. Keep generated `.ci/` and `verification/` files outside the
published source tree; both are ignored locally. Retain failures alongside passes.
Do not overwrite the [prior V6.7 report](../reliability/results-v6.7.md) or its
[immutable receipt](../reliability/evidence/v6.7-offline.json) with a new run.
Their original source hashes and wheel identity refer to **6.7.0**, before this
repository reorganization; they do not attest to a newly built artifact.

These synthetic checks establish software behavior within their tested envelope.
They do not establish real provider quality, invoices, GT performance, student
usability, or research recall. Those require the [authorized pilot](../research/pilot.md)
and independent [complete-source evaluation](../research/evaluation.md).
