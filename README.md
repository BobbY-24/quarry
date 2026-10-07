![Quarry: Your agent. Your sources. Traceable data.](assets/github-banner.svg)

# Quarry

**Turn a research idea into source-traceable data through your own agent.**
Collect terms and senses—or source spans expressing ideas, opinions and sentences.

[Quick start](#quick-start) · [Examples](#examples) · [Your models](docs/guides/compute.md) · [GT compute](docs/guides/gt-compute.md) · [Docs](docs/README.md)

<picture>
  <source media="(max-width: 760px)" srcset="assets/workflow-mobile.svg">
  <img src="assets/workflow.svg" alt="Describe a study with your agent, review the plan, collect grounded discoveries, and export a dataset with source evidence.">
</picture>

## Quick start

Paste into **Claude Code, Codex or another local coding agent**:

```text
Set up Quarry from https://github.com/BobbY-24/quarry.
Read src/termfinder/agent_skill/SKILL.md, install the package, and connect
Quarry to this agent in my research workspace. Preserve existing settings.
Start with the offline connection and confirm a list_studies tool call.
```

Python 3.11–3.13 · macOS/Linux · [Patched SQLite required](docs/reliability/compatibility.md).

## Installation on macOS or Linux

<details>
<summary>Prefer manual setup? Copy these commands.</summary>

```sh
gh repo clone BobbY-24/quarry
cd quarry
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-build-isolation .
mkdir -p research-workspace
```

**Claude Code**

```sh
termfinder connect --host claude --workspace "$PWD/research-workspace"
```

**Codex**

```sh
termfinder connect --host codex --workspace "$PWD/research-workspace"
```

Open your agent in `research-workspace`, follow its trust/reload steps, then
call `list_studies`. [Connection help and upgrades →](docs/guides/agent-setup.md)

</details>

The default connection is a synthetic offline rehearsal. Real extraction uses
**your API, local model or approved GT compute**, with configured models and an
authorized `--allow-paid` connection. Keep keys in the runtime environment.
[Configure compute →](docs/guides/compute.md)

## Examples

Paste a request; your agent prepares the recipe and inputs.

**New expressions and changed senses**

```text
Create a Quarry study from my permitted ./corpus discussion exports.
Use the neologisms recipe, English, Broad, at most 30 sources and a $10 cap.
Exclude entity-only names; keep singletons and distinct senses.
Show the sources, policy and cost before collection.
```

**Multilingual cultural vocabulary**

```text
Use Quarry's cultural recipe on my permitted Arabic and Hindi sources.
Include cultural expressions and entities. Preserve original scripts
and distinguish translations from observed text. Prepare a bounded plan.
```

**Scientific and medical jargon**

```text
Use Quarry's jargon recipe on my permitted ./papers PDFs with Specialists.
Keep established terminology, page locations and exact contexts.
Use our reviewed GT profile; show sources, costs and resources before submission.
```

[NLPx research examples and student walkthroughs →](docs/guides/nlpx-students.md)

## Keep working in the same conversation

```text
Show the original passage and source for this term.
Mark this sense as needing review, then undo that annotation.
Reopen my study and resume unfinished work within its saved limits.
Save pilot-v1 and export CSV, JSONL, Parquet and annotation files.
```

Every record retains source evidence. Model-proposed meanings remain suggestions;
measure recall against complete held-out sources. [Research protocol →](docs/research/publication-protocol.md)

## Documentation

[Agent setup](docs/guides/agent-setup.md) · [Recipes](docs/guides/recipes.md) · [Sources](docs/guides/sources.md) · [GT procedure](docs/guides/gt-compute.md)

[Notebook](examples/simple_student_workflow.ipynb) · [CLI/Python](docs/reference/cli-python.md) · [More diagrams](docs/reference/diagrams.md) · [Evaluation](docs/research/evaluation.md) · [Limitations](docs/research/pilot.md)

[All documentation](docs/README.md) · [Reproduce](docs/development/reproduce.md) · [Contribute](CONTRIBUTING.md)

```text
src/       collector, interfaces, recipes and packaged resources
tests/     offline regressions and immutable compatibility fixtures
examples/  working notebooks, study recipes and compute templates
docs/      user guides, research protocol and reliability contracts
tools/     bounded reproduction and maintenance scripts
assets/    project artwork
```

Workflow inspired by [Paper2Agent](https://github.com/jmiao24/Paper2Agent).
[Recovery and reliability](docs/reliability/recovery.md) · [MIT license](LICENSE).
