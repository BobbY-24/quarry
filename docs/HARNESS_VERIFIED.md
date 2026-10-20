# V6.4 own-harness workflow — verified October 5, 2026

The researcher installs V6 and connects its packaged skill/stdio MCP tools once
in a chosen coding-agent workspace. Later sessions create or reopen studies,
prepare and inspect complete plans, collect or resume, inspect exact evidence,
annotate and export through that same conversation. The browser is optional.
The agent manages structured inputs and identifiers; the collector retains
deterministic admission, grounding, budgets, state and reproducible exports.

This follows the skill-and-connected-tools entry pattern documented by
[Paper2Agent](https://github.com/jmiao24/Paper2Agent). V6 supplies its own fixed
collector. These checks do not establish equivalent usability, a live host
connection, lab adoption, extraction quality or publication acceptance.

## Final artifact and independent installation

The GitHub source handoff excludes local build environments, wheels, raw
verification runs, study databases and generated datasets. Paths under `dist/`
and `verification/` below identify retained local evidence; they are not files
downloadable from this repository. The portable, sanitized evidence summary
and repository handoff are documented in [GITHUB_HANDOFF.md](GITHUB_HANDOFF.md).

Install from the checked-in source using the [README procedure](../README.md#installation-on-macos-or-linux).
After installing the pinned build dependencies, a wheel can also be built with
`python -m pip wheel --no-build-isolation --no-deps --wheel-dir dist .`.
The historical hash below identifies the locally tested artifact.

The locally verified final wheel is
`dist/nlpx_termfinder-6.4.0-py3-none-any.whl`. Its SHA-256 is:

```text
e26b28183847b5e9b3816f02761e57f674b81c214000776e4532065b2cb2827f
```

It was installed into the separate `.venv-6.4-final` environment with
`pypdf==6.19.0` and `pyarrow==25.0.1`. The offline build used
`setuptools==84.0.0`, `wheel==0.48.0` and `packaging==26.0` from the reviewed
local wheelhouse. The executed platform was macOS with Python 3.12.14.
Installed checks omitted source `PYTHONPATH` and asserted the module came from
that environment. V3/V4/V5 and earlier V6 releases are not dependencies.

Earlier environments, wheels, studies and verification outputs remain preserved
on the build machine.
The first V6.4 verification wheel is retained in
`dist/verification-draft-6.4.0/`; it is not the final artifact above. The final
wheel includes a corrected planning instruction: new inputs call `prepare_study`
to obtain the complete planning bundle, while unchanged reopen/resume uses the
retained review and does not reset setup.

## Executed checks

| Check | Result | Local evidence paths |
| --- | --- | --- |
| Source suite before final skill clarification | 277 tests passed in 21.386 seconds | `verification/harness-full-source-sandbox.json` |
| Final installed suite | **277 tests passed in 22.023 seconds** | `verification/harness-final-installed-suite-sandbox.json` |
| Final pinned build and clean install | Passed with network and unrelated file reads denied | `verification/harness-final-wheel-build-sandbox.json`, `verification/harness-final-wheel-install-sandbox.json` |
| One-time project-local connection | Codex, Claude Code and generic files generated in fresh verification workspaces; matching repeats were idempotent | `verification/harness-final-installed-6.4.0/acceptance_report.json` |
| Complete browser-free MCP workflow | Same generated connection ran Broad and Specialists, each with four grounded records and two distinct `anchor` senses; full plan/source inspection, reconnect/reopen/resume, exact evidence, annotation undo and byte-identical named exports passed | `verification/harness-final-installed-6.4.0/acceptance_report.json`, `verification/harness-final-installed-smoke-sandbox.json` |
| Pending and failed source visibility | Unfetched URL and malformed PDF were inspectable in separate studies; no ready review or extraction jobs were fabricated | `verification/harness-final-installed-6.4.0/acceptance_report.json` |
| CLI, fixed-project MCP and Python notebook | Guided CLI and old fixed-study entry point passed; packaged skill exported; all five reviewed notebook code cells executed against the final installation | `verification/harness-final-cli-notebook-report.json`, `verification/harness-final-cli-notebook-sandbox.json` |
| Eight public API workflows | Terms, ideas, opinions and sentences each passed Broad and Specialists; pre-dispatch review, interruption/resume, exact evidence, reversible annotation, frozen integrity and identical CSV/JSONL/Parquet/annotation exports | `verification/harness-final-four-types-6.4.0/acceptance_report.json`, `verification/harness-final-four-types-sandbox.json` |

Every application execution used the reviewed finite macOS Seatbelt launcher
with a clean credential environment. Denied-network and unrelated-file-read
probes passed. All sources, agent plans, approval decisions and provider replies
in the rehearsals were explicitly synthetic. Paid requests and external-agent
calls were zero. No real host settings, account, persistent service, upload,
publication or external message was changed or launched.

The initial harness smoke failed because its synthetic client's positional
`name` parameter collided with the release tool's `name` argument. The client
was corrected and rerun in a fresh directory; both the failed and successful
reports remain. Earlier fixture-setup failures also remain visible. Failed
attempts are not counted as passed verification.

## Reliability and research boundaries

The suite retains all three starter term policies in both modes and covers
grounding, Unicode offsets, separate senses/community uses, deduplication,
single-extractor retention, truncation recovery, schema validation, caching,
budget admission and cost accounting, cancellation, interrupted/uncertain jobs,
source failures, finite discovery, annotation history and immutable exports.
Complete-source synthetic labels exercise false-negative measurement and grouped
splits; they do not measure real provider recall.

The new connection tests verify unrelated-setting preservation, exact matching
repeats, refusal of conflicting settings/customized skills/inline credentials,
path and symlink checks, bounded files, rollback and setup locking. Workspace
MCP tests verify selection, study isolation, one-worker ownership, paid-gate
immutability, no-selection behavior, complete paged/chunked plan inspection,
pending reviews, source problems, stale bindings, and directory replacement
checks before project initialization and SQLite access.

The agent does not execute generated extractor tools or turn model output into
scope expansion. Model annotations remain audit suggestions; human relay requires
a declared actual decision reference. Approval is hash-bound audit provenance,
not authenticated identity. Deterministic checks establish occurrence and frozen
consistency, not semantic correctness, novelty, truth, rights or recall.

## Remaining field checks and limits

- Real Claude Code/Codex discovery, trust/restart controls, organization policy,
  account integration and student usability remain untested. Generic harnesses
  may need manual registration. The recorded proof uses generated configuration
  and an actual local stdio server with a synthetic client.
- Linux, Python 3.11/3.13 and real provider calls were not executed in this macOS
  build. Verify target-platform installation and current model/rate compatibility
  before an authorized pilot. External planning-agent charges are unmetered.
- Workspace path checks are logical tool boundaries, not OS isolation against
  malicious same-user concurrent filesystem changes. Python SQLite uses paths;
  use a private trusted workspace and the reviewed OS sandbox/container where
  needed. The connection does not modify a host's permissions or trust controls.
- One connection supports multiple studies with one active worker. It catalogs
  at most 1,000 immediate workspace entries. Changed launch gates, environments
  or customized connection artifacts require an explicit V6-only migration or
  fresh workspace; connection setup refuses conflicting replacement.
- Unchanged captured plans resume without original files. New/changed plans
  after processing need the documented incremental or advanced evaluation
  protocol; previously seen text cannot become newly blind human gold.
- Archive lawful original bytes separately and verify source-use rights. OCR,
  full table records, full conversation datasets and automatic benchmark
  construction remain extensions. Frozen datasets and some aggregates still
  need representative memory/load checks for large corpora.
- Cancellation cannot retract a sent request. Uncertain provider outcomes retain
  pending coverage and possible charges; retries cannot promise exactly-once
  billing. Saved exports reproduce retained records, not new model responses.

For the actual student procedure, use [AGENT_NATIVE.md](AGENT_NATIVE.md) and
[SIMPLE_WORKFLOW.md](SIMPLE_WORKFLOW.md). The
[architecture](ARCHITECTURE.md), [notebook](../examples/simple_student_workflow.ipynb),
[publication protocol](PUBLICATION_PROTOCOL.md) and [pilot steps](PILOT.md)
provide the detailed handoff. A real pilot requires explicit authorization,
permitted sources, finite spending and independent exhaustive held-out
annotations before precision/recall or publication claims.
