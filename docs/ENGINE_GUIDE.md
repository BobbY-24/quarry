# V6 engine and interface guide

Detailed CLI, API, cost and data-format reference preserved from the V6.4 introduction.

# V6 — NLPx research collector

V6 collects **terms and senses with inspectable source evidence**, plus exact
source spans expressing ideas, opinions, or sentences. Start with a research
question in plain language. Your own coding agent drafts a plan;
V6 validates its scope and inputs, collects with Broad or Specialists, resumes
unfinished work, and saves a reproducible dataset version. It is intended for PhD
students and research assistants in Georgia Tech's NLPx lab working with [name removed]
and [name removed]. Their publications guide the product; this implementation is
not a requested lab deployment or a reproduction of their datasets.

V5 supplies the GLM + DeepSeek broad route, additive community specialist lenses,
grounded union, exact-occurrence deduplication, bounded split recovery, recorded
rates, and a separate Gemini direction. V6 implements a new independent package
around those principles: editable recipes, HTML/text/PDF ingestion, bounded
discovery, durable SQLite projects, API/CLI/browser workflows, reversible review,
immutable exports, and complete-source evaluation. V3, V4, V5, and existing
outputs are not dependencies and are preserved.

## Install and connect once; use your own agent for each study

V6's default interface is **your existing coding-agent conversation**. Install
the collector and its project-local skill/MCP connection once. Then ask that
agent to create or reopen a study, prepare its sources and recipe, show a
concrete cost review, collect or resume, inspect exact evidence, and deliver the
dataset. You do not write JSON, move bundle files, or open a browser to finish
the session. The optional browser provides a visual evidence workspace.

For an agent that has local terminal and file tools, paste this setup request.
Replace the paths and choose `codex`, `claude`, or `generic` for the host:

> Read the reviewed local V6 package at `<V6_DIR>`, including this README and
> `src/termfinder/agent_skill/SKILL.md`. Install it in a fresh isolated Python
> 3.11–3.13 environment using its pinned dependencies. Enable the project-local
> `v6-collect-research` skill and local MCP connection for this harness in
> `<WORKSPACE>`, with studies in `<STUDIES_ROOT>`, using `termfinder connect`.
> Preserve existing settings and studies. Keep the default offline launch gate;
> make no paid collection calls. Verify the connection with `list_studies`.
> Run subsequent V6 sessions here in conversation; use the browser only if I
> request a visual view. Do not download an installer into an interpreter or
> put credentials in arguments, configuration files, or reports.

After [installation](#installation-on-macos-or-linux), the manual equivalent is:

```sh
termfinder connect --host codex --workspace /path/to/research-workspace \
  --studies /path/to/research-workspace/v6-studies
```

Use `--host claude` for Claude Code or `--host generic` for another harness.
The connection is scoped to the chosen workspace and a bounded studies root;
it does not edit home/global settings, install hooks, or run a background
service. Follow the command's host-specific result, reload or restart the agent
if necessary, and verify an actual V6 tool call. Generic setup provides local
skill/stdio instructions; a custom host may need its own registration step.
[Connection details](AGENT_NATIVE.md) cover artifacts and verification.
The chosen workspace must already exist; V6 can create its default studies
folder. The default connection is offline only. Real collection needs a
separately authorized paid launch gate and the approved finite plan.

Once connected, a student's request can be:

> Use V6 to create `ev-language` for new expressions and changed senses in my
> permitted `/path/to/ev-corpus` exports. Exclude names used only as names and
> retain singleton uses. Use English, Broad, the GLM + DeepSeek profile, at most
> 30 sources, and a $10 cap. Show the complete sources, problems, and estimate
> here before collection. Do not start a paid run until I approve this plan.

The agent prepares and pages through the complete plan using V6 tools, presents
it in conversation, and relays your actual approval. It handles progress,
cancellation, resume, exact source inspection, and named reproducible exports.
On a later day, say: “Open `ev-language`, show unfinished work and costs, and
resume the approved plan.” The launch gate, finite budget, and approval binding
continue to apply. Your personal agent session's cost is separate and unknown
to V6. Offline fake is a rehearsal, not an extractor for arbitrary research.

[The student procedure](SIMPLE_WORKFLOW.md) includes NEO-BENCH, Camellia,
CARE, and MedReadMe-inspired examples. The [11 student walkthroughs](NLPX_STUDENT_GUIDE.md)
and [publication protocol](PUBLICATION_PROTOCOL.md) retain the detailed
research and evaluation procedures. These are proposed extensions, not claims
of lab adoption or dataset reproduction.

### Optional visual workspace

Ask your agent to show a visual view, or run:

```sh
termfinder --project /path/to/research-workspace/v6-studies/ev-language serve
```

**Plan, Evidence, and Dataset** show the same saved study. Evidence supports
exact contexts, reversible annotations and relations; Dataset saves/audits/
exports the frozen inventory. The browser is optional. An ordinary chat agent
without local tools can use its expandable prompt/bundle fallback. Advanced
CLI/API/manual configuration remains available.

The conversational entry follows the skill-and-connected-tool direction of
[Paper2Agent](https://github.com/jmiao24/Paper2Agent); the visual annotation view
draws on [Thresh](https://aclanthology.org/2023.emnlp-demo.30/) by [name removed],
[name removed], and [name removed]. V6 supplies its own fixed collector; it has no dependency
on either project. Real harness usability and real provider quality still need
field verification.

V6.4 adds workspace connection and an entirely conversational review path on
top of V6.3's simple visual interface and V6.2's recovery
for runs with thousands of sources: saved per-model backoff,
five-attempt failover, finite larger execution caps, indexed queues, paginated
evidence inspection, staged exports, and consistent backups. Existing projects
opt in with `termfinder --project STUDY large-run`; spending and source scope
remain researcher-controlled. See [the long-run procedure](LONG_RUNS.md)
and [release verification](RESILIENCE_VERIFIED.md).

V6 preserves existing inventories and the earlier wheels/environments.
The revised extraction prompt has a new version, so earlier prompt responses are
not reused for new extraction jobs. Re-exporting a saved version needs no model
calls; running new extraction requires its own reviewed scope and budget.

[The earlier agent workflow](AGENT_WORKFLOW.md) documents the file-handoff
fallback. Agent-proposed sources and search histories remain declarations that
need verification; deterministic evidence checks establish source occurrence,
not semantic correctness, representative sampling, or recall.

## Installation on macOS or Linux

Select an installed Python 3.11, 3.12, or 3.13 first; a machine's default
`python3` may point to an unsupported version. Clone the standalone **v6-research-collector** repository, then run with a supported interpreter (the example uses Python 3.13):

```sh
cd v6-research-collector
python3.13 -m venv .venv-6.4
. .venv-6.4/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-build-isolation .
termfinder --help
```

Runtime and build dependencies are pinned in `pyproject.toml` and
`requirements-build.txt`. Installation requires access to the configured package
index or a reviewed local wheelhouse. For an offline machine, obtain wheels for
the target Python/platform on an authorized connected machine, inspect them, and
use `pip install --no-index --find-links WHEELHOUSE ...`. Do not run downloaded
installers through a shell pipe. There is no LaTeX, sibling environment, browser
automation, database server, or provider SDK requirement.

The offline demonstration needs no credentials. Never place a credential in a
recipe, URL, notebook output, CLI argument, or export. Real profiles use only the
environment variable named in their provider configuration. The project and
browser store research evidence; protect their directories like the source data.

## Optional CLI reference and offline collection

```sh
termfinder recipe neologisms --out recipe.json
termfinder init demo-neologisms --recipe recipe.json --profile fake --mode broad
termfinder --project demo-neologisms ingest src/termfinder/fixtures/community.html \
  --metadata examples/source_metadata.json
termfinder --project demo-neologisms estimate
termfinder --project demo-neologisms collect --offline --max-jobs 1
termfinder --project demo-neologisms status
termfinder --project demo-neologisms resume --offline
termfinder --project demo-neologisms inspect
termfinder --project demo-neologisms snapshot first-offline-version
termfinder --project demo-neologisms versions
```

Copy the returned `version_id` into the export command:

```sh
termfinder --project demo-neologisms export VERSION_ID demo-export \
  --formats csv,jsonl,parquet,annotation
termfinder --project demo-neologisms serve
```

Open the loopback URL printed by `serve`. The local browser supports project
setup, Broad/Specialists selection, estimates, source ingest, progress, evidence,
annotations/undo, snapshots, and exports. It accepts no credentials. Paid dispatch
requires explicit authorization for that CLI command or browser session.

`init --mode specialists` adds recipe-routed specialist passes to the same broad
extractors. `--profile fake` makes the demonstration independent of paid APIs.
The synthetic provider uses known fixture contexts; it is not a general offline
extractor and its output is not model-quality evidence.

All three term research policies are shipped:

```sh
termfinder recipe cultural --out cultural-recipe.json
termfinder recipe jargon --out jargon-recipe.json
python examples/offline_demo.py --out demo-acceptance
```

The complete demo configures each starter, runs both modes on the same local
fixture corpus, exercises interruption/resume, inspects Unicode evidence and
distinct senses, reverses annotations/relations, shows budget stops and failures,
evaluates independent complete-source labels, and exports every format twice.
It writes a reviewable `acceptance_report.json`. Use a fresh output directory.

Rehearse the new agent handoff and all four collection types without credentials:

```sh
python examples/agent_workflow/offline_demo.py --out agent-demo
python examples/simple_workflow_demo.py --out simple-demo
```

This uses explicitly scripted bundles and fake responses to verify the mechanism,
including compiled inputs, corpus freeze, evidence, resume, annotation undo,
publication audit, and byte-identical exports. It does not test a live external
agent or measure field accuracy. The simple demo exercises the same new
prepare/approve/resume/release operations used by the browser and MCP server,
with all four data types in both modes.

## Notebook / Python API

For an agent-prepared study, the same short workflow is available in Python:

```python
from termfinder import Project
from termfinder.workflow import prepare_review, approve_review, run_review, release_dataset

project = Project("my-study")
review = prepare_review(project, bundle=agent_bundle, fetch_remote=False)
# Display the review and record the researcher's actual approval before collection.
approve_review(project, review["review_id"], approval_origin="notebook")
progress = run_review(project, review["review_id"], max_jobs=1)
progress = run_review(Project(project.path), review["review_id"])  # resume
release = release_dataset(project, "research-v1")
```

Use a fake profile for this rehearsal. Real profiles require `allow_paid=True`
for an explicitly authorized pilot. The self-contained
[simple student notebook](../examples/simple_student_workflow.ipynb) supplies a
synthetic agent-plan surrogate, exact evidence, annotation undo, and frozen
exports. The lower-level API remains available for advanced workflows:

```python
from importlib.resources import files
from termfinder import Project, FakeProvider
from termfinder.config import starter_recipe

recipe = starter_recipe("cultural")
recipe["mode"] = "specialists"
project = Project("my-cultural-study")
project.configure(recipe, profile="fake")
project.ingest(
    paths=[files("termfinder").joinpath("fixtures", "cultural.md")],
    metadata={"language": "mul", "community": "multilingual-community", "domain": "synthetic-cultural"},
)
estimate = project.estimate()
progress = project.collect(FakeProvider(), max_jobs=1)
project = Project("my-cultural-study")  # a new process can reopen the same project
project.resume(FakeProvider())
inventory = project.inventory()
term_id = inventory["terms"][0]["term_id"]
annotation_id = project.annotate(term_id, "approved", note="Reviewed the complete source.")
project.undo_annotation(annotation_id)
version_id = project.snapshot("v1")
project.export(version_id, "my-cultural-export")
```

[The example notebook](../examples/researcher_workflow.ipynb) expands this workflow
with evidence spans, annotation history, complete-source evaluation, and a frozen
export. The coding agent drafts ordinary research-policy changes as validated
inputs; neither path requires engine changes.
See [recipe customization](RECIPES.md).

For the idea-to-agent-to-collector API, use the
[agent workflow notebook](../examples/agent_workflow/researcher_agent_workflow.ipynb).
The `Project` methods `prepare_agent_setup`, `validate_agent_bundle`,
`apply_agent_bundle`, `ingest_agent_sources`, `freeze_agent_corpus`, and
`publication_audit` are shared by the CLI and browser.

For proposed workflows tied to existing NLPx research, see the
[11 student walkthroughs](NLPX_STUDENT_GUIDE.md),
[complete lab procedure](LAB_PROTOCOL.md), and
[editable student recipes and batch metadata](../examples/lab_recipes/README.md).
The named examples use synthetic few-shots and zero spending until a researcher
reviews the actual corpus, profile and finite budget.

## Sources and discovery

Implemented ingestion accepts URL lists and local HTML, text, Markdown, and
text-bearing PDFs. Frozen parsed text retains useful blocks and Unicode offsets;
PDF blocks retain page numbers. HTML does not execute JavaScript. Parsing failures
are visible, including the intentionally broken PDF fixture. Image-only PDFs
need a separately reviewed OCR extension.

Implemented discovery adapters are an explicit static JSON search manifest and
an optional public HTTPS JSON search endpoint, plus scoped HTTP(S) fetching.
Domain scope, hop/source/request limits, and finite prices constrain discovery;
decisions and parent/query lineage are recorded. No search-provider account or
authenticated connector is silently configured. See [source and discovery examples](SOURCES.md).

## Cost and model profiles

Broad uses independently configured GLM and DeepSeek extractors and preserves
their grounded union, including single-model discoveries. Specialists adds
recipe lenses. There is no agreement threshold, frequency threshold, final-term
quota, or model judgment stage that deletes candidates. Gemini remains a separate
explicit profile. The recorded V5 model identifiers are:

| Profile model | Recorded identifier |
| --- | --- |
| GLM / Fireworks | `accounts/fireworks/models/glm-5p3-flash` |
| DeepSeek / Fireworks | `accounts/fireworks/models/deepseek-v4p1-flash` |
| Gemini | `gemini-3.5-flash-lite` |

Providers, rates, aliases, prompt versions, token/timeout settings, and models live
in profile/recipe configuration. Before an authorized real run, verify model
availability, current rates, and adapter settings and save the reviewed profile.
The build does not make paid test requests.

```sh
termfinder --project demo-neologisms estimate --links 300
termfinder --project demo-neologisms estimate --links 300 --average-chars 20000 --cache-hit-rate 0
```

Count-only estimates show a range and assumptions. Actual parsed lengths give a
more useful estimate. Stages include discovery, parsing/OCR assumptions,
extraction, specialist passes, and translation assumptions; costs/unknown
reservations appear in status and manifests. Output translations are optional
extraction suggestions, not a separate translation stage. Fake calls have no
service bill. English HTML measurements do not calibrate multilingual PDFs.
Budget exhaustion leaves unfinished work visible; uncertain API acceptance can
imply possible charges and cannot guarantee exactly-once billing.

Known failed/partial jobs can be requeued with `retry-job JOB_ID`. Uncertain jobs
need a deliberate resolution: `resolve-uncertain JOB_ID` closes the unresolved
outcome without retry; `resolve-uncertain JOB_ID --retry
--acknowledge-possible-duplicate-billing` queues another attempt while retaining
unknown cost reservations. Queueing does not itself dispatch a paid request.

## Dataset versions and evaluation

Typed records, evidence, lexical terms/senses, occurrences, sources, runs, jobs, audit proposals, annotations,
relations, discovery, and costs are separate exported tables. JSONL preserves
native types. CSV stores nested values as canonical JSON; null and empty string
can share an empty cell, so use JSONL/Parquet when that distinction matters.
Formula-like CSV cells are prefixed with an apostrophe for safe spreadsheet
inspection. Each table's schema names a companion column listing escaped fields;
remove exactly one inserted apostrophe from those listed cells to restore values.
Parquet preserves homogeneous scalar columns with native Arrow types, including
integer offsets. Nested or heterogeneous columns use canonical JSON with per-column
encoding documented in `schema.json`. The manifest records
schemas, prompts, recipes, model versions, source hashes, dates, failures,
coverage, costs, constraints, and file hashes.

```python
import json
from pathlib import Path
import pyarrow.parquet as parquet
rows = parquet.read_table("demo-export/terms.parquet").to_pylist()
schema = json.loads(Path("demo-export/schema.json").read_text())
columns = schema["tables"]["terms"]["parquet_columns"]
decoded = [{key: json.loads(value)
            if value is not None and columns[key]["encoding"] == "canonical_json" else value
            for key, value in row.items()} for row in rows]
```

A snapshot freezes its records. Exporting that version after collection or
annotation changes reproduces the same files without provider calls. Rejected
human annotations never delete the complete grounded inventory. Alias and semantic
relations are reversible.

Quality evaluation uses exhaustive annotation of whole held-out sources, exact
frozen-text spans, and source/group splits. Reports include precision, recall,
and false negatives by domain and language. Candidate counts and model agreement
are diagnostics, not recall. See [evaluation instructions](EVALUATION.md)
and [research motivation](RESEARCH.md).

## Verification and handoff

The build's offline checks use synthetic fixtures and fake transports in a
network-denied environment with unrelated data/credentials inaccessible. To rerun
the reviewed suite, follow [verification instructions](VERIFICATION.md).
The acceptance report demonstrates the researcher workflow, not field accuracy.
The [V6.4 harness verification results](HARNESS_VERIFIED.md) record the completed checks;
[earlier release evidence](VERIFIED.md) remains preserved. These record
artifact paths, wheel hash, and platform scope.

[Architecture](ARCHITECTURE.md) explains record identity, durability, recovery,
cache contracts, costs, and interface boundaries. [Pilot guidance](PILOT.md)
lists known limitations and the remaining steps for a separately authorized
real-world collection. Full table-record extraction, conversation preference
datasets, and automatic benchmark generation remain documented extension points.
