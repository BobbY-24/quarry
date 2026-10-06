# Browser-chat handoff and advanced research references

**V6.3's default is the [simple Plan → Evidence → Dataset workflow](SIMPLE_WORKFLOW.md).**
Your coding agent can submit and operate the inputs directly using the
[packaged skill or MCP tools](AGENT_NATIVE.md). It is no longer necessary to
copy prompt and JSON files between applications. Source preparation, corpus
freeze, length-based estimation, approval-bound collection, and combined release
are backend operations shared by the browser, CLI, Python API, and MCP server.

The handoff below remains supported for ordinary ChatGPT/Claude browser chats
without local tools. Its individual controls are under expandable help or
Advanced in the three-tab interface. For routine preparation use **Prepare
source and cost review**, then **Approve and start**; this replaces the separate
apply/import/freeze/start controls. For export use **Save and export**. Older
terminal commands below remain available for compatibility and detailed study
design. The research-specific conversations and publication caveats still apply.

Start with the research question you would normally tell your ChatGPT or Claude
agent. V6 prepares a precise handoff prompt, your agent proposes the research
inputs, and V6 shows you a checked plan before collection. You do not need to
write the recipe or source metadata JSON yourself.

For example, [name removed] could begin with:

> I want to study new expressions and changed meanings in electric-vehicle
> discussions from 2025–2026. Exclude names used only as names. Keep one-off
> expressions. I have a folder of permitted English source exports. I want terms,
> their meanings as proposals, and their original contexts.

The student chooses **Term**, **Broad**, a source folder, a maximum source count,
and a spending limit. V6 turns those choices into instructions their existing
agent can follow. The agent drafts the policy, examples, suggested attributes,
source list, and sampling/evaluation notes in one bundle. V6 remains responsible
for ingestion, execution limits, grounding, persistent progress, and exports.

This interaction is inspired by
[[name removed], [name removed], and [name removed]'s Thresh](https://aclanthology.org/2023.emnlp-demo.30/):
a configurable research definition should produce an interface the researcher
can inspect and test. Thresh addresses fine-grained human evaluation; V6 uses
that design direction for an agent-assisted collection handoff. V6 does not
depend on Thresh or directly exchange its annotation format.

## The student sees six steps

### 1. Describe what you want

Open the local V6 browser and start at **1 · Describe the study in your own words**.
Under **What do you want to collect?**, choose the data type,
write the question in ordinary language, and set the language/community, source
domain or local folder, collection limits, model profile, and Broad or
Specialists mode. Start with one research question and a small source set.

| Choose | Use it when you want | Example |
| --- | --- | --- |
| Term | Expressions, entities, jargon, and contextual senses | A community-specific meaning of an established spelling |
| Idea | Source passages that explicitly express a claim, proposal, or explanation | A legal obligation with its qualifiers intact |
| Opinion | Passages explicitly expressing an assessment or stance | A stated preference about a cultural practice |
| Sentence | Whole sentence spans selected by the research policy | A medical sentence containing technical vocabulary |

Every type keeps exact source evidence. A generated explanation can accompany
it as a labeled suggestion. For ideas and opinions, you are collecting passages
that express the proposed concept, not asking a model to invent an abstract
inventory and call that observed data.

The source folder and domains are limits chosen by the researcher. Do not put
credentials, account tokens, private system folders, or unrelated personal
documents in the handoff. Use permitted source exports and source-use metadata.
The personal agent cannot enlarge these limits through its returned files.

### 2. Give the prepared request to your own agent

V6 generates a handoff containing:

| File | What it is for |
| --- | --- |
| `prompt.md` | Instructions to paste into the student's own agent |
| `brief.json` | The structured version of the student's choices |
| `bundle-template.json` | The response shape the agent must fill |
| `contract.json` | The input rules the agent can check against |

Click **Create request for my AI agent**. The second step, **Give this request
to your AI agent**, provides **Copy agent request**, **Download request**, and
**Download bundle template**. Copy the prompt and attach the other files if the
agent supports attachments.
The agent can ask clarifying research questions, propose an inclusion rubric,
write useful positive/negative/boundary examples, suggest project attributes,
and identify sources within the fixed scope. This planning uses the student's
existing agent account; it is outside V6's extraction-provider cost counters.
Synthetic English starter examples for ideas, opinions, and sentences explain
the exact-span contract. Ask the external agent to adapt the rubric and examples
to the actual domain and languages before applying the plan.

Ask the agent to distinguish verified browsing results from suggestions based
on memory, retain queries and selection reasons, and leave unknown dates,
models, rights, or provenance unavailable rather than inventing them. An agent
without browsing can still prepare a policy around researcher-supplied files.
The returned source list is a proposal, not a dataset and not evidence that
the whole relevant community has been covered.

### 3. Bring back one bundle and inspect the checked plan

At **3 · Bring back the agent's plan**, save the agent's JSON response as a
file or paste it into the browser and click **Check plan**. You do
not need to separate the response into individual recipe, source metadata,
sampling, and evaluation files yourself. V6 validates them together.

Validation checks the schema and recipe, the matching brief hash, model profile,
the source count, URLs/domains, local paths and authorized roots, and the
researcher-defined limits. Unsupported keys, attempts to expand scope, invalid
paths, recognized credential fields/value patterns, or unresolved blocking
questions prevent import. Never supply credentials; pattern checks cannot
recognize every possible secret.
Source text and model output remain data; a returned instruction or tool call
cannot execute code or modify V6's configuration.

If validation fails, use **Copy correction request** to bring the provided
repair prompt back to the same agent.
Correct the bundle and validate again. A new research question or wider source
scope should begin with a new brief rather than disguising that change as a
repair. Validation does not fetch the proposed sources or bill extraction APIs.

Read the plain-language plan: what will be collected, from which sources,
under what policy, using which profile/mode, and within which limits. Review
the sampling limitations and planned evaluation. The agent's answer is a draft;
the researcher's decision to apply the checked plan is what makes it the study
configuration. API collection still requires its separate explicit authorization.

Applying also prepares every collector input in your project folder:
`agent-inputs/<bundle_sha256>/`. Open **Generated collector input files** to find
that directory and its file list. It contains the brief, original submitted
bundle in canonical JSON, recipe, profile, sources, per-source metadata,
sampling/evaluation/search notes, agent metadata, prompt, URL list, and a hash
manifest. You do not need to split or maintain these files manually.

Sampling and evaluation notes are recorded study intentions. V6 can prepare the
grouped split and annotation packets, but it does not automatically create a
sampling frame, a blinded annotation team, or semantic gold labels. Execute and
document those procedures against the actual frozen corpus before claiming
the resulting metrics.

### 4. Import sources, check them, and collect

Click **Apply this plan** to configure the study and ingest eligible local
files. For remote sources, **Fetch reviewed website sources** is a separate,
explicit action. URL ingestion retrieves only the approved, in-scope locations
under V6's fetch limits. Check full source text, locations,
language/community metadata, and parsing failures. A URL suggested by the
agent becomes evidence only if usable content was actually retrieved.

Inspect the cost estimate after ingestion so it uses actual document lengths
and windows. A link-count estimate alone is a range. Large multilingual PDFs
need their own token/parsing assumptions. Conservative request reservations can
block dispatch even when a typical-length estimate is smaller than the limit.

Before **Collect / resume**, click **Prepare blind source review**. This saves
the corpus version, assigns whole source families to development or held-out
groups using the plan's holdout fraction and a fixed seed, and creates blank
full-source annotation packets. Unknown family IDs fall back to individual
sources; the researcher must identify related versions, translations, threads,
or problem variants in the plan rather than relying on that fallback.

Open the reported `human-review/<dataset_version>/` folder:

| File | What the researcher does with it |
| --- | --- |
| `family-map.json` | Check that related sources stay together |
| `source-splits.json` | Keep the recorded seed and source assignments fixed |
| `annotation_sources.jsonl` | Complete-source blank packets for the full selected corpus |
| `heldout_sources.jsonl` | Give these blank complete-source packets to independent annotators |

Do this before any extraction job is prepared, including a zero-budget or
failed attempt. V6 rejects a late freeze if those source content hashes have
already entered job planning in the project. It cannot tell whether a researcher
or an external agent previously saw model candidates elsewhere. The blank
packets are not gold: humans must annotate every eligible span in each complete
held-out source, including sources with no eligible records. Small corpora can
produce an empty held-out split; inspect the counts and address that limitation
before claiming recall.

Arrange independent complete-source gold annotation as described in
[the publication protocol](PUBLICATION_PROTOCOL.md). Once the concrete
corpus and finite budget are authorized, run collection. Broad retains the
grounded union from both extractors. Specialists adds attention lenses while
preserving grounded discoveries from either model, including singletons.

The progress view shows pending, complete, failed, partial, budget-stopped, and
uncertain work. Resume continues eligible unfinished jobs. Do not interpret a
model's enumeration-complete flag as measured recall. A lost provider response
can have been billed; uncertain outcomes require an explicit resolution before
retry rather than silently assuming the previous call was free.

### 5. Inspect evidence and add optional annotations

Open a record and follow it back to its source. Read the exact original passage,
its surrounding context, and available heading/page locations. Compare the
observed text with proposed meanings, attributes, and translations. Verify
attribution and qualifiers before using an opinion or idea in an analysis.

You can approve, reject, or request review, add human attributes, and link
aliases or distinct senses. These annotations and relations are reversible.
The complete grounded inventory remains available beside the approved subset.
Neither a human rejection nor model disagreement silently removes its evidence.

For evaluation, have annotators read complete held-out sources using the fixed
rubric and blank gold packets. Candidate review is useful for evidence quality;
it cannot measure what collection missed. Exact-span precision/recall measures
detection under the annotation boundaries. Meaning, semantic equivalence,
stance, readability, or factual truth requires a separate human rubric.

### 6. Save a release and export it

Save a dataset version, run its publication audit, and read the issues and
limitations. The audit checks the stored evidence chain and deterministic
consistency; it is not a publication approval or a quality score. Resolve errors
and document remaining limitations, including partial processing, source-use
constraints, missing originals, and independently annotated gold.

Export CSV, JSONL, Parquet, and annotation files from that saved version. The
manifest contains schemas, recipes, prompts, provider/model provenance, source
hashes, processing status, costs, constraints, and file hashes. Applied agent
workflow lineage is included in the frozen dataset and its export. Generic
`records` and `evidence` exports cover all four unit types; `terms` remains the
lexical subset and `occurrences` remains a compatibility evidence table.
Re-exporting
the same version makes no model calls. Fresh extraction can change; it is not
how you reproduce the released records.

## Five realistic starting conversations

These are proposed uses informed by existing NLPx research. They are not
assignments from the students or PIs, and do not reproduce the named datasets.
The included briefs use a zero spending limit and local-only scope so a student
can prepare and review a plan before authorizing collection.

### [name removed]: new community terms

[NEO-BENCH](https://arxiv.org/abs/2402.12261) studies model robustness to
neologisms. [name removed] chooses **Term**, supplies dated community exports, and
tells their agent: "Include new forms and changed senses; keep one-off uses;
exclude entity-only names." The agent produces a neologism policy and a source
plan inside the approved folder. [name removed] checks that it distinguishes shifted
senses from ordinary uses, then collects and reviews exact contexts, using complete
held-out sources to measure missed terms and exports a term/sense inventory for
later understanding experiments. First observation in this corpus is not a
verified coinage date.

Start with [`community-neologisms.brief.json`](../examples/agent_workflow/community-neologisms.brief.json).

### [name removed]: cultural entities in original script

[Camellia](https://arxiv.org/abs/2510.05291) motivates collecting culturally
associated entities. [name removed] chooses **Term**, begins with permitted Urdu food
descriptions, and asks their agent to include established food names. The agent
drafts category and association attributes while preserving original scripts.
[name removed] checks that named entities are eligible and that masked answers absent
from the source are excluded. Native reviewers inspect original contexts and
adjudicate cultural associations; uncertain meanings stay proposals. The export
supports later cultural tasks without pretending to generate the benchmark.

Start with [`cultural-entities.brief.json`](../examples/agent_workflow/cultural-entities.brief.json).

### [name removed]: expressed cultural opinions

[CARE](https://arxiv.org/abs/2504.05154) examines cultural preferences. [name removed]
chooses **Opinion** and supplies permitted passages about a specified set of
cultural practices, asking the agent for explicit assessments and preferences,
retaining quotations, attribution, and human/generated source origins. V6
collects exact passages; stance targets and cultural associations remain
suggestions until adjudicated. Independent reviewers distinguish mentioned,
endorsed, hypothetical, and generated views. The resulting evidence inventory
can support a separate preference analysis; it is not human preference labels
or a claim about the population.

Start with [`cultural-opinions.brief.json`](../examples/agent_workflow/cultural-opinions.brief.json).

### Medical research: sentences for human readability annotation

[MedReadMe](https://arxiv.org/abs/2405.02144), by [name removed] and [name removed], studies
medical sentence and span readability. A researcher chooses **Sentence**,
supplies permitted patient-facing documents, and asks the agent for complete
sentences containing medical jargon. V6 retains original sentences, surrounding
contexts, and page locations. Qualified annotators rate difficulty separately;
a model suggestion is not a human readability score or medical advice. The
researcher evaluates detection on whole held-out documents and exports a
sentence pool for a separately designed readability study.

Start with [`medical-sentences.brief.json`](../examples/agent_workflow/medical-sentences.brief.json).

### Legal research: ideas supported by explicit clauses

[GAVEL](https://arxiv.org/abs/2601.04424) motivates legal summarization coverage
work. A researcher chooses **Idea**, supplies permitted legal documents, and
asks for exact passages expressing obligations, procedural claims, or case
facts. The agent drafts inclusion rules requiring qualifiers and attribution.
V6 grounds the passages rather than storing generated summaries as quotations.
Human adjudication decides whether passages express equivalent facts and how
they map to an external coverage checklist. Term/span recall and summary
coverage are distinct evaluations; this export does not establish legal truth.

Start with [`legal-ideas.brief.json`](../examples/agent_workflow/legal-ideas.brief.json).

## The same workflow from a terminal

The browser is the ordinary starting point. These commands are useful for an
agent that already works in a terminal or a student continuing a saved project.
`brief.json` is created by the form or copied from an example. Run preparation
from the study directory so a relative `./corpus` root refers to that study's
own folder. Put only permitted files in it.

```sh
termfinder --project . prepare-agent --brief brief.json --out handoff
# Paste handoff/prompt.md into your agent; attach its other input files.
# Save the agent's JSON answer as returned-bundle.json.
termfinder --project . validate-plan returned-bundle.json --out validation.json
# Read the checked plan; use its repair prompt if validation fails.
termfinder --project . apply-plan returned-bundle.json
termfinder --project . ingest-plan
termfinder --project . estimate
termfinder --project . freeze-corpus --name corpus-v1 --seed v6-agent-study-v1
termfinder --project . status
```

For preparation directly from a short idea, the equivalent explicit scope is:

```sh
termfinder --project . prepare-agent \
  --idea "Collect new expressions and shifted senses in my dated EV documents" \
  --data-type term --policy neologisms --language en \
  --community ev-community-pilot --domain local-only.invalid \
  --local-root corpus --max-sources 15 --budget 0 --out handoff
```

The zero-dollar examples are preparation templates, not paid run instructions.
To collect with real providers, prepare and review a finite-budget plan for the
actual corpus, set credentials through the documented environment configuration,
then use the CLI's explicit `collect --allow-paid` option or an explicitly
authorized browser session. Use the shipped synthetic offline demo for a
provider-free rehearsal; it demonstrates workflow mechanics, not research
accuracy for a custom recipe.

After collection and annotation:

```sh
termfinder --project . snapshot release-v1
# Copy the returned version_id; replace RELEASE_VERSION_ID below with that ID.
termfinder --project . publication-audit RELEASE_VERSION_ID --out publication-audit.json
termfinder --project . export RELEASE_VERSION_ID release --formats csv,jsonl,parquet,annotation
```

`release-v1` is the version's display name. Audits, exports, and evaluation take
the returned `dataset_…` version ID; they do not resolve display names.

Use `freeze-corpus` above for the agent-assisted setup; it prepares the source
snapshot, grouped splits, and blank packets together. See
[the shared lab procedure](LAB_PROTOCOL.md) for cancellation/resume, CLI/API
usage, and reversible annotations; its manual split procedure is an advanced
alternative. See [the publication protocol](PUBLICATION_PROTOCOL.md) for the
evidence package, sampling statement, hostile-review questions, and honest
reproducibility limits.

## Continuing from a notebook

The same handoff methods are available through `Project`. This preparation and
plan review makes no model call:

```python
import json
from pathlib import Path
from termfinder import Project

project = Project("my-study")
brief = json.loads(Path("brief.json").read_text(encoding="utf-8"))
request = project.prepare_agent_setup(brief)
request["prompt"]  # Copy this value to the student's own agent.

bundle = json.loads(Path("returned-bundle.json").read_text(encoding="utf-8"))
report = project.validate_agent_bundle(bundle)
report  # Read errors, repair_prompt, warnings, and the plan summary.

# After the researcher has reviewed a valid plan:
assert report["valid"]
project.apply_agent_bundle(bundle)  # Imports eligible local sources only.
project.estimate()
review = project.freeze_agent_corpus("corpus-v1", seed="v6-agent-study-v1")
corpus_version = review["version_id"]
review  # Shows the saved review folder, source families, splits, and blank packets.
```

If the reviewed plan contains URLs, `project.ingest_agent_sources()` explicitly
fetches eligible remote sources; do so before `freeze_agent_corpus` to include
successfully retrieved URLs in the frozen corpus. Later use `project.publication_audit(version)`
and `project.export(version, "release")` with a saved dataset version. Existing
collection, resume, annotation, and evaluation APIs use that same project.

## What this layer currently does and does not do

Implemented: a brief-driven agent handoff, one strict returned bundle,
deterministic plan validation/repair feedback, fixed scope and finite budgets,
explicit plan application and ingestion, retained hashed workflow lineage,
compiled collector input files, grouped corpus/split/blank-packet preparation
before extraction, source-grounded typed evidence, a publication consistency audit, and frozen
exports through the same V6 engine.

The student runs the external agent and provides its result. V6 does not log in
to ChatGPT or Claude, automatically read their history, or obtain their search
logs. It does not execute submitted scripts, contact authors, publish datasets,
guarantee source licenses, build a complete benchmark, or prove an idea/opinion
interpretation. Thresh format conversion, full gold span editing in the browser,
semantic evaluation, authenticated source connectors, external OCR, structured
tables, and conversation dataset construction remain documented extensions.

The type label is a collection instruction. Deterministic grounding does not
prove that a passage expresses an idea or opinion, that an apparent sentence is
grammatically complete, or that an attributed speaker actually endorses it.
Those are research judgments. `interpretation` is labeled model-generated;
unavailable values retain null and an appropriate reason.
