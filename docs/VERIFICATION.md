# Offline verification

Review the code and fixtures before executing them. A subprocess timeout is not
a sandbox. The build uses a clean environment and a real operating-system
sandbox with network denied and unrelated personal data/credential files
inaccessible. Tests use fake providers and fake fetch transports only. No paid
collection or dependency installation is part of the acceptance demonstration.

The tests cover schema validation, exact grounding and Unicode code-point spans,
sense preservation, deterministic deduplication, truncation recovery, finite
cost/request budgets, interruption/resume, cache reuse, source failures, discovery
scope/lineage, immutable exports, source-level evaluation, and local UI mutation
security. A readable two-page synthetic PDF tests page preservation; a malformed
PDF tests visible failure. Full Parquet verification requires the pinned `pyarrow`
runtime; absence is reported rather than masquerading as a passed export test.

## Commands inside a reviewed isolated environment

From the independent V6 directory, with its pinned dependencies installed:

```sh
python -m unittest discover -s tests -v
python examples/offline_demo.py --out /tmp/v6-acceptance
```

Use a fresh demonstration output directory; the script refuses to overwrite an
existing directory. It writes six project databases, independent complete-source
gold labels, estimates, status, evaluation reports, two byte-identical exports per
saved dataset version, and `acceptance_report.json`. The report explicitly labels
synthetic metrics as software verification. It does not measure real-provider
precision or recall.

On macOS, use the parameterized Seatbelt profile/launcher supplied in `tools`.
Replace the runtime placeholder with the reviewed interpreter's base installation
directory. Run the launcher itself with a clean environment and isolated Python
startup, then it supplies clean child environment, CPU/file limits, a private
temporary directory, and probes for denied networking/unrelated file reads before
executing the requested code:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin .venv/bin/python -I -S tools/verify_offline.py \
  --python .venv/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --source --report verification/unit-sandbox.json \
  -- -m unittest discover -s tests -v

/usr/bin/env -i PATH=/usr/bin:/bin .venv/bin/python -I -S tools/verify_offline.py \
  --python .venv/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --source --report verification/demo-sandbox.json \
  -- examples/offline_demo.py --out verification/demo
```

`--source` uses only the reviewed V6 source tree through `PYTHONPATH`. Omit it for
an installed-wheel check. Reports contain source-file hashes, safe command
arguments, probe booleans, bounds, and exit status. They contain no key values or
environment dump. macOS may require permission to invoke `sandbox-exec` from an
already sandboxed editor; the application code still executes inside Seatbelt.

On Linux, use a reviewed image pinned by digest and a wheelhouse for that image's
Python/platform. Set the two task-specific variables to actual reviewed values;
the command intentionally has no host credential mounts or network:

```sh
V6_IMAGE='python:3.12-slim@sha256:REPLACE_WITH_REVIEWED_IMAGE_DIGEST'
V6_WHEELHOUSE='/absolute/path/to/reviewed-linux-wheels'
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --cpus 2 --memory 2g --pids-limit 256 --read-only \
  --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,nodev,size=1073741824 \
  --mount "type=bind,src=$PWD,dst=/work" \
  --mount "type=bind,src=$V6_WHEELHOUSE,dst=/wheelhouse,readonly" \
  --workdir /work --env PYTHONDONTWRITEBYTECODE=1 --env OMP_NUM_THREADS=2 \
  "$V6_IMAGE" sh -eu -c '
    python -m venv /tmp/v6-env
    /tmp/v6-env/bin/python -m pip install --no-index --find-links /wheelhouse -r requirements-build.txt
    /tmp/v6-env/bin/python -m pip install --no-index --find-links /wheelhouse --no-build-isolation /work
    /tmp/v6-env/bin/python -m unittest discover -s tests -v
    /tmp/v6-env/bin/python examples/offline_demo.py --out /work/verification/linux-demo
  '
```

Use a fresh output path. The build was verified on macOS; the Linux container
command is a documented workflow and requires verification on the target Linux
machine. Do not substitute an unreviewed/latest image or enable networking merely
because a wheel is missing.

## Independent package check

Build a wheel using the pinned build dependencies, install it in a clean isolated
environment without sibling paths in `PYTHONPATH`, and invoke `termfinder --help`.
Run packaged fixture extraction through `importlib.resources.files('termfinder')`
with only that installed wheel and its reviewed runtime dependencies present.
This verifies that the shipped recipes, profiles, fixtures, and browser assets
are included. Merely running from the source checkout does not prove independent
installation.

## Agent-assisted workflow verification for 6.1

Keep the existing 6.0 reports and demonstration outputs. Install the reviewed
6.1 wheel into a separate environment such as `.venv-6.1`; do not replace the
earlier environment or add sibling version directories to `PYTHONPATH`. The
current source suite contains 149 tests. Recorded run results and the released
wheel hash are in [VERIFIED.md](VERIFIED.md); the commands below describe how to
repeat the checks, rather than claiming a new run.

On macOS, use the same reviewed runtime root and clean-environment launcher as
above. These checks deliberately omit `--source`, so the collector comes from
the installed wheel. Choose fresh report and output paths for every repeat:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.1/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.1/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/agent-release-unit-sandbox.json \
  -- -m unittest discover -s tests -v

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.1/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.1/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/agent-release-installed-sandbox.json \
  -- tools/smoke_agent_installed.py --report verification/agent-release-installed-report.json

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.1/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.1/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/agent-release-demo-sandbox.json \
  -- examples/agent_workflow/offline_demo.py --out verification/agent-release-demo
```

The installed-package smoke check asserts that `termfinder` is imported from
the selected environment and reports its version and location. It configures
all five research brief examples against a temporary synthetic local corpus,
validates and applies their returned plans, checks the compiled input files,
and freezes their source-review packets before extraction. It also executes
the nine reviewed Python cells in
[the standalone notebook](../examples/agent_workflow/researcher_agent_workflow.ipynb)
in a fresh temporary working directory. The smoke tool refuses to overwrite its
report and restricts that report to `verification/`.

The new demonstration creates separate term, idea, opinion, and sentence
projects. Each uses an explicitly scripted surrogate agent bundle and fake
Specialists responses at a zero spending budget. It checks exact observed
spans, Unicode locations, the separation between observed text and generated
interpretation, retention of a discovery proposed by only one extractor,
one-job pause/reopen/resume, reversible annotation, a saved-version integrity
audit, and byte-identical CSV, JSONL, Parquet, and annotation exports. Nonterm
records do not enter the lexical term inventory. Its fabricated gold labels
exercise evaluation mechanics only; they are not independent human labels or
evidence of field precision or recall. The demo refuses an existing output
directory and writes `acceptance_report.json` beneath its fresh output.

Additional tests cover the following boundaries:

- Agent plans cannot broaden approved domains, local roots, budgets, model
  profiles, or data types. Malformed plans yield a repair request; unresolved
  questions block application. Source fetch remains a separate explicit action.
- Hidden, credential-bearing, out-of-scope, and symlinked local paths are
  rejected. Rejected secret-bearing input is not echoed or retained as raw
  input. Browser mutations require the local origin and cannot silently switch
  a real profile to a fake one.
- Frozen review packets group source families and remain blank. A freeze after
  any extraction job for those content hashes is rejected. Small corpora may
  have no held-out family; external human exposure cannot be verified.
- Nonterm records preserve distinct source spans and interpretations. A
  generated paraphrase cannot serve as an observed span, and evidence checks
  do not establish semantic correctness, speaker identity, truth, or novelty.
- Frozen audits detect altered evidence, hashes, record types, job/model
  provenance, plan bindings, and event history. Missing rights, original-byte
  archives, incomplete processing, and unverified gold remain visible
  limitations; an archive declaration is not an independently checked archive.
- The local interface handles brief preparation, plan repair, local application,
  explicit URL fetching, blind-review preparation, evidence inspection, and
  structured definitions without giving returned JSON authority to execute
  tools or change scope.

For a bounded browser demonstration of the installed wheel, the reviewed
launcher permits local browser access while denying outbound networking and
unrelated file reads. It disables paid collection and expires after 300 seconds:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.1/bin/python -I -S tools/agent_browser_launcher.py \
  --python .venv-6.1/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --installed --report verification/agent-release-browser-sandbox.json
```

Open `http://127.0.0.1:8766` in a local browser and walk through the setup using
only synthetic sources and a fake profile. The launcher starts a fresh project
and refuses an existing report. Its report proves the launcher's probes and
bounds; record any browser interactions separately. It does not itself assert
that every interface action was exercised. Linux checks require the reviewed
container workflow above with the same installed-package smoke and demo
commands; macOS Seatbelt launchers are not portable to Linux.

No verification here contacts a student's ChatGPT or Claude agent, searches the
web, or calls a paid provider. Successful scripted handoffs establish software
contracts, not the quality of an actual agent-generated research plan.

## Repeat the V6.3 simple workflow checks

Keep the earlier environments and reports. Install the final 6.3 wheel into a
separate environment such as `.venv-6.3` and review the current code and fixtures.
The final installed suite contains 234 tests. Recorded results and the wheel
hash are in [SIMPLIFICATION_VERIFIED.md](SIMPLIFICATION_VERIFIED.md). These
commands use an installed package, with no source `PYTHONPATH`; choose fresh
reports and output directories for every repeat.

```sh
/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.3/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.3/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-simple-unit-sandbox.json \
  -- -m unittest discover -s tests

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.3/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.3/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-simple-installed-sandbox.json \
  -- tools/smoke_simple_installed.py --report verification/repeat-simple-installed-report.json

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.3/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.3/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-simple-demo-sandbox.json \
  -- examples/simple_workflow_demo.py --out verification/repeat-simple-demo
```

The smoke check asserts installed version/module location, executes guided
CLI commands, exports the packaged skill, initializes the actual stdio entry
point, and executes the five reviewed code cells of
[the simple notebook](../examples/simple_student_workflow.ipynb). The eight-case
demo covers each collection unit in Broad and Specialists, a prepared blank
packet with no jobs, explicit review approval, pause/reopen/resume, single-model
grounded retention, exact spans, annotation undo, frozen audit, and byte-identical
exports after later live annotations. All inputs/replies are synthetic.

For the installed browser, use the bounded launcher command above with
`.venv-6.3` and a fresh report. It prints a fresh verification project. The
reviewed `tools/simple_browser_plan.py` can prepare a synthetic plan in that
project through installed stdio MCP without invoking an external agent. Follow
the visible browser actions recorded in SIMPLIFICATION_VERIFIED. Run
`tools/check_simple_browser.py` in the same OS sandbox to confirm the saved
state and repeat export. Neither helper automates or proves browser interaction;
both restrict project/report locations to `verification/`. Do not replace the
operating-system sandbox with an ordinary subprocess timeout.

## Repeat the V6.4 own-harness checks

Keep the earlier wheels, environments, projects and reports. Install the reviewed
6.4 wheel into a separate environment and omit `--source` when checking that
installation. The current suite contains 277 tests. Recorded results and the
released wheel hash are in [HARNESS_VERIFIED.md](HARNESS_VERIFIED.md). Use fresh
report/output paths for each repeat:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.4/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.4/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-harness-unit-sandbox.json \
  -- -m unittest discover -s tests

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.4/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.4/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-harness-installed-sandbox.json \
  -- tools/smoke_harness_installed.py --out verification/repeat-harness-installed

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.4/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.4/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-harness-notebook-sandbox.json \
  -- tools/smoke_simple_installed.py --expect-version 6.4.0 \
  --report verification/repeat-harness-notebook-report.json

/usr/bin/env -i PATH=/usr/bin:/bin .venv-6.4/bin/python -I -S tools/verify_offline.py \
  --python .venv-6.4/bin/python --runtime-root /absolute/path/to/reviewed/python-base \
  --report verification/repeat-harness-types-sandbox.json \
  -- examples/simple_workflow_demo.py --out verification/repeat-harness-types
```

The harness smoke check prepares Codex, Claude Code and generic connection files
in fresh verification workspaces only. It verifies matching-repeat idempotence,
launches the generated MCP command with a synthetic stdio client, completes
Broad and Specialists studies through the same connection, inspects the full
plan and exact evidence, closes/reconnects/reopens pending work, reverses
annotations, and reproduces a named export. Separate source-problem studies show
unfetched URLs and failed PDFs inside the harness without extraction jobs.
No actual host application, account, personal configuration or provider is used.

The notebook check also exercises the existing CLI and fixed-project MCP route,
exports the packaged skill and executes all five reviewed synthetic notebook
cells. The eight-case demo verifies terms, ideas, opinions and sentences in both
modes through the public Python API. These checks establish installed software
contracts, not real-agent planning quality, recall, client discovery/trust, or
student usability. Do not invoke a live host with unrelated credentials merely
to make the offline smoke check more realistic. Linux uses the reviewed container
workflow above and still needs platform-specific verification.

## Interpreting the evidence

The one-job acceptance pause demonstrates a researcher stopping/reopening a
session; core fault tests additionally exercise interrupted running jobs and
uncertain provider outcomes. Reproducible export checks compare actual file
bytes/hashes and forbid provider calls during export. Complete-source synthetic
gold specs are independent of generated candidates and intentionally expose
missed contextual occurrences. Distinct senses and both single-extractor
discoveries are retained, even if one human annotation rejects a candidate.

When a test fails or a dependency is unavailable, keep its result in the
verification report and distinguish completed checks from remaining work.
Review production claims against the documented limitations before an explicitly
authorized pilot.
