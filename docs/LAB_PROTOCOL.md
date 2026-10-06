# A student’s complete Quarry research procedure

This protocol explains the common workflow behind the named examples in
`examples/lab_recipes/`. Those examples are proposals informed by published
research, not assignments from Wei Xu or Alan Ritter, approved lab deployments,
or reproductions of the papers’ datasets. A student owns the research question,
sampling decisions, source permissions, annotation rubric, and interpretation.
Quarry supplies a durable inventory of terms/senses or explicitly selected idea,
opinion, and sentence spans, with inspectable source evidence.

**The ordinary entry path is the [simple workflow](SIMPLE_WORKFLOW.md): tell your
coding agent the study, review the complete plan in conversation, inspect
evidence, and request a saved dataset. The one-time
[packaged skill/MCP connection](AGENT_NATIVE.md) lets the agent create and reopen
studies and submit inputs directly. A browser is optional. You do not need to
write, maintain, or transport recipe JSON.**
Use the [student starting requests](NLPX_STUDENT_GUIDE.md#start-in-ordinary-language)
for research-specific examples. Read the [publication protocol](PUBLICATION_PROTOCOL.md)
before collection to plan independent whole-source gold annotation and explain
the human, agent, model, and deterministic parts of the pipeline.

The six steps below apply to every student and RA. The numbered technical
sections that follow preserve the original `jonathan-zheng.json` vocabulary
walkthrough as a detailed reference and advanced manual alternative. Another
profile's recipe and metadata can be attached to the personal agent as examples
instead of edited by hand. Keep separate study directories and protect them like
the original research data: they contain source text, contexts, and annotations.

## The shared research procedure

1. **Describe the study to your connected agent.** After installation and
   one-time workspace connection, ask it to create or reopen a named study. Choose
   Term, Idea, Opinion, or Sentence and write the research question in ordinary
   language. Set permitted languages, communities, dates, domains or local source
   folders, source limits, a finite spending limit, Broad or Specialists, and a
   model profile. The unit determines what exact source span is collected. A
   community label describes the sample, not a speaker's demographic identity.

2. **Let your own agent prepare inputs.** The project-local Quarry skill and workspace
   tools handle recipe and source files. For a chat without local
   tools, use the expandable prompt/bundle handoff in Plan. Attach
   the relevant student recipe as an optional reference. Ask the agent to draft
   criteria, positive/negative/boundary examples, attributes, scoped source
   suggestions, selection reasons, family IDs, and sampling/evaluation notes.
   Unknown dates or provenance stay unavailable. The agent runs in your existing
   account; Quarry does not connect to or bill that planning account.

3. **Prepare one readable plan in conversation.** The coding agent submits the bundle directly;
   a browser-only chat uses import and **Check plan**. The agent can repair
   validation errors within the existing bounds. Quarry validates scope and schemas and
   materializes the individual collector inputs; you do not need to separate
   the bundle into JSON files yourself. Unresolved blocking questions prevent
   application. Validation is not verification of the agent's research claims.

4. **Approve the concrete source and cost review.** The agent uses Quarry to
   import declared local files, fetch only listed websites when
   explicitly selected, freezes complete sources and grouped splits before
   any extraction job, and estimates parsed-length costs. Inspect metadata,
   page locations, failures, permissions, scope, modes, models, and assumptions.
   It reads the full paged review, discloses any clipped detail, and presents
   the concrete source list and estimate. State your decision in the conversation;
   the agent relays it with the bound review ID. Check the frozen family split and give blank complete
   held-out sources to independent human annotators. Blank packets are not gold,
   and a small corpus may have no held-out sources. Collection requires separate
   authorization for the concrete corpus and finite budget; resume eligible
   pending work and investigate failed, partial, or uncertain outcomes.

5. **Inspect evidence and optionally annotate.** Follow each record to its exact
   source passage, context, offsets, and available pages/headings. Separate source
   text from proposed meanings, translations, and attributes. Review attribution
   and qualifiers for opinions and ideas. Approvals, rejections, human attributes,
   and alias/sense links are reversible, with the full grounded inventory retained.
   Evaluate against exhaustive human annotations of whole held-out sources;
   candidate-only review cannot find omissions. Exact occurrence checks do not
   establish correct meanings, opinions, factual truth, or historical novelty.

6. **Save and export a dataset version.** Ask the agent to release a named version.
   Quarry saves a version,
   runs its publication evidence audit, and exports every supported format.
   Document errors and limitations. Retain the
   complete records/evidence, optional approved subset, manifests, provenance,
   and source-use constraints. Re-exporting that saved version makes no model
   calls. The audit checks evidence consistency; independent annotations and the
   research rubric establish quality. Follow the publication protocol to report
   precision, recall, false negatives, grouped splits, costs, and remaining gaps.

Geyang's original Term recipe remains a cultural-vocabulary study. The new
Opinion example is an alternative for explicit assessments/preferences and
needs a separate span, attribution, and human judgment rubric; it does not
construct CARE preference rankings or training pairs. The other named profiles
retain their vocabulary focus unless the researcher deliberately defines a
different collection unit.

## Detailed technical reference

The sections below explain installation and the research decisions behind the
default flow. File-copying and JSON-editing commands are optional manual
alternatives, not onboarding requirements. For the agent path's browser labels,
supported terminal equivalents, and generated input files, use
[AGENT_WORKFLOW.md](AGENT_WORKFLOW.md).

## 1. Install Quarry and rehearse without credentials

Clone **BobbY-24/quarry** onto a macOS or Linux machine.
Quarry retains the V6.4 engine's `termfinder` CLI/Python namespace and
`v6-collect-research` skill identifier; the product name does not change those APIs.
Use an installed Python 3.11, 3.12, or 3.13; this example uses Python 3.13:

```sh
cd quarry
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-build-isolation .
termfinder --help
```

Installation obtains pinned dependencies from the configured package index.
For disconnected machines, prepare inspected wheels for that machine’s Python
and platform, then use the offline installation instructions in the README.
No V5 installation, provider SDK, or database server is required.

For your own study, open a fresh project in the local browser:

```sh
termfinder --project studies/my-study serve
```

Open its printed loopback URL and begin with **1 · Describe the study in your
own words**. The six-step flow configures the project through the checked agent
bundle. No provider request is made just by opening the interface. Stop the
browser server with Ctrl-C when done.

To rehearse before working with real source documents, use the shipped synthetic
corpus:

Choose a fresh output directory for each rehearsal. If `lab-training` already
exists, replace it in every command below; the demonstration preserves existing
outputs rather than overwriting them.

```sh
python examples/offline_demo.py --out lab-training
termfinder --project lab-training/neologisms-broad status
termfinder --project lab-training/neologisms-broad inspect
termfinder --project lab-training/cultural-specialists serve
```

Open the printed loopback URL. Inspect terms, exact contexts, PDF locations,
annotations, and saved versions. Stop the browser server with Ctrl-C when done.
The demonstration deliberately includes a malformed PDF, so visible parsing
failures are expected. Its acceptance report explains the checks.

`FakeProvider` recognizes the supplied fixtures and shipped starter recipe IDs.
It is **not** a general offline extractor. Running a custom named recipe against
real documents with `--offline` cannot establish extraction quality. Keep this
synthetic rehearsal separate from the study described below.

## 2. Research-policy decisions and the advanced manual alternative

In the default flow, tell your agent these research decisions and inspect how
the checked plan encodes them. Attach the named recipe and metadata as references
if useful. If you prefer direct file configuration, copy the example before
editing it:

```sh
cp examples/lab_recipes/jonathan-zheng.json jonathan-recipe.json
cp examples/lab_recipes/jonathan-zheng.metadata.json jonathan-metadata.json
```

The named examples begin with local sources, disabled discovery, and zero total
and stage spending. These settings permit preparation and estimates while
preventing paid extraction. They are starting policies, not ready-to-run paid
experiments.

Make these decisions explicit in the browser/agent request, or in the complete
JSON if using the advanced manual route. The policy examples below describe
Term studies; other units need a rubric for their exact sentence or passage
boundaries, attribution, and eligibility:

* **Research question and criteria:** define which expressions and senses count.
  A neologism study can exclude entity-only names; cultural collection can
  include entities; jargon collection includes established technical language.
* **Sampling scope:** specify source languages, researcher-defined communities,
  publication-date interval, unknown-date policy, and permitted domains. A
  community label describes source selection; it must not infer a person’s
  demographic identity.
* **Examples:** supply positive, negative, and boundary examples from suitable
  material. Every example expression must occur literally in its example text.
  Include difficult cases such as a familiar spelling with a specialized sense,
  an entity-only mention, or an unexplained abbreviation. Examples guide
  extraction; they are not an exhaustive list or evaluation gold.
* **Fields:** retain expression, language, sense, and context. Add typed project
  attributes under `output.attributes`, using `string`, `number`, `integer`,
  `boolean`, or `array`, with `required` and `description`. Unknown values should
  remain null; requiring a field must not invite invention.
* **Limits:** keep finite source/call/time/concurrency limits. A spending budget
  constrains work; it does not imply a target number of terms.

For example, a neologism project can add `innovation_type` and a historical
verification note. A cultural project can request an entity category and an
optional transliteration. A medical project can request an abbreviation
expansion and a difficulty hypothesis. Model-produced attributes remain
suggestions; human attributes are recorded separately during annotation.

For an agent-produced plan, ask the agent to keep specialist routes consistent
and inspect the validated result. In the manual route, specialist lenses contain
an `id`, profile model alias such as `glm` or
`deepseek`, a research lens, and literal `communities` routes. Update **both** the
recipe community list and lens routes when changing source labels. The same
label must appear in source metadata or that specialist pass will not run.
Broad general extractors still run in Specialists mode.

Keep original contexts separate from generated translations. A grounded
definition quote is observed source text, but exact grounding does not verify
its semantic interpretation. Novelty remains a research hypothesis: first
observation in this corpus is not a historical coinage date.

For the advanced manual route, create the project and validate configuration:

```sh
termfinder init studies/jonathan-zheng --recipe jonathan-recipe.json \
  --profile glm-deepseek --mode broad
```

`init` configures an existing project as well as a new one. It makes no provider
request and preserves earlier inventory. For the blind study below, use a fresh
study directory with no prior extraction. Reconfiguring a previously used project
does not remove its candidate records or restore a blind evaluation setup.
Invalid recipes fail early. Change recipe `version` when research
policy changes, and save each reviewed configuration. Model identifiers,
endpoints, rates, and model versions belong in a profile rather than engine code.

## 3. Ingest sources in metadata-homogeneous batches

The default agent bundle supplies per-source metadata; applying the checked
plan handles eligible local files and remote fetching remains an explicit
action. The following commands are the advanced manual alternative.
Update `jonathan-metadata.json` to describe the actual source batch. Supported
metadata includes language, community, domain, publication date, title,
retrieval date, and source-use constraints. Do not use a paper’s publication
date as the date of an unrelated underlying community post.

```sh
termfinder --project studies/jonathan-zheng ingest corpus/thread-001.md \
  corpus/thread-002.txt --metadata jonathan-metadata.json
termfinder --project studies/jonathan-zheng status
```

One metadata object applies to **every** file or URL in that invocation. Separate
calls are necessary for different communities, languages, dates, or constraints.
Use `mul` for an actually multilingual source when appropriate; still specify
the permitted expression languages in the recipe. Do not turn a mixed-language
source into an English document merely because the researcher reads English.

For scientific or medical documents:

```sh
termfinder --project studies/jonathan-zheng ingest corpus/article.pdf \
  --metadata article-metadata.json
```

Quarry supports text-bearing PDF, HTML, text, and Markdown files. Supply file paths,
not a directory. PDF page blocks survive parsing. Offsets address Unicode code
points in frozen parsed text, not bytes in the PDF or HTML. Inspect parsing
failures before extraction. Image-only PDFs need a separately reviewed OCR
workflow; Quarry does not invoke one automatically.

URL ingestion is an explicit fetch operation:

```sh
termfinder --project studies/jonathan-zheng ingest --url-list urls.txt \
  --metadata web-metadata.json
```

Before using it, deliberately replace the example’s local-only domain sentinel
with the permitted hostnames and reapply the recipe with `init`. Every redirect
must also remain in scope. An empty domain list permits explicit public URL
ingestion; it is not a local-only restriction. URL lists contain one URL per
line, with optional blank lines and `#` comments. Authenticated sites,
JavaScript rendering, and commercial search connectors are extensions.

Do not assume official research dataset JSON or CSV is directly ingestible.
Prepare a reviewed conversion to supported text that preserves record identity
and genuinely observed source contexts. Never fill a masked context with an
invented entity and label the result observed evidence. Preserve the conversion
and dataset constraints alongside the study.

## 4. Review estimates and freeze the corpus before extraction

```sh
termfinder --project studies/jonathan-zheng estimate
termfinder --project studies/jonathan-zheng estimate --links 100
```

The first command uses parsed inventory lengths and actual community routes.
The second gives count-only scenarios with assumptions, not a confidence
interval or a term-yield prediction. For an explicit count/length scenario:

```sh
termfinder --project studies/jonathan-zheng estimate --links 100 \
  --average-chars 20000 --cache-hit-rate 0
```

For script or PDF workloads, the API exposes additional planning assumptions:

```python
from termfinder import Project

project = Project("studies/jonathan-zheng")
estimate = project.estimate(
    chars_per_token=2,
    output_tokens_per_window=1500,
    recovery_fraction=0.2,
    parsing_usd_per_source=0,
    translation_usd_per_source=0,
)
```

Those numbers are illustrative assumptions to replace with pilot measurements.
Inline translation suggestions are billed within extraction output. OCR and a
standalone translation pipeline are not implemented simply because their
planning costs can be represented.

Inspect `request_reserves_usd` as well as projected totals. Quarry conservatively
reserves the configured model’s full input ceiling plus recovery output cap.
A very small stage budget can prevent any dispatch even when the ordinary token
estimate appears to fit. Set a reviewed **finite** total budget and relevant
stage budgets in `execution`; replace the examples’ zero defaults only after
approval for the concrete run. Verify current model availability, endpoint
compatibility, and rates, then save a reviewed profile and reapply it:

```sh
termfinder init studies/jonathan-zheng --recipe jonathan-recipe.json \
  --profile reviewed-profile.json --mode broad
```

For an approved agent plan, use **Prepare blind source review**, or its terminal
equivalent, before any extraction jobs are prepared:

```sh
termfinder --project studies/my-study freeze-corpus \
  --name corpus-v1 --seed v6-agent-study-v1
```

This saves the plan's source-family grouping, a fixed split, and blank
complete-source annotation packets. It rejects a late freeze for source content
already used in extraction job planning. Check unknown family IDs and an empty
held-out split before proceeding. The gate cannot establish whether people or
an external agent already saw candidates elsewhere.

The advanced manual alternative below requires the researcher to establish
equivalent independence and family grouping. Before any extraction jobs or
candidate inspection, freeze the ingested corpus:

```sh
termfinder --project studies/jonathan-zheng snapshot corpus-v1
termfinder --project studies/jonathan-zheng split CORPUS_VERSION \
  --seed jonathan-study-v1 --out source-splits.json
termfinder --project studies/jonathan-zheng export CORPUS_VERSION \
  blind-annotation-pack --formats annotation
```

Replace `CORPUS_VERSION` with the returned `version_id`. The pre-extraction
annotation packet from this fresh study contains full frozen sources and no
extracted candidates. A snapshot of a reused project may already contain
candidates; give annotators only the blind source packets and ensure they have
not inspected previous candidates for the held-out sources.
Save the split before recipe/prompt tuning. Small collections can produce an
empty test split; inspect it before proceeding.

## 5. Keep document families together and annotate whole sources

For the default agent workflow, include source `family_id` values in the checked
plan and inspect the generated `family-map.json` and `source-splits.json` from
**Prepare blind source review**. Related threads, versions, translations, and
paper/problem variants must stay together. The following API procedure is the
advanced alternative for a manually prepared source map.

Default manual splits group by source ID. For related threads, versions, translations,
or paper families, maintain a researcher-owned `family-map.json` mapping each
source ID to a stable family identifier. Arbitrary ingestion metadata such as
`thread_id` is not retained automatically; setting it does not enable a CLI
grouping field. Use an external mapping with the supported API:

```python
import json
from pathlib import Path
from termfinder import Project
from termfinder.evaluation import source_splits

project = Project("studies/jonathan-zheng")
dataset = project.dataset("CORPUS_VERSION")
family_map = json.loads(Path("family-map.json").read_text(encoding="utf-8"))
grouped_sources = [
    dict(source, family_id=family_map[source["source_id"]])
    for source in dataset["sources"]
]
splits = source_splits(grouped_sources, seed="jonathan-study-v1",
                       group_field="family_id")
Path("family-splits.json").write_text(
    json.dumps(splits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
```

Replace the version placeholder in Python too. This changes the split input,
not the original evidence records. The API can also set split ratios. Freeze
the chosen manifest and family mapping once, before tuning.

Give qualified annotators only the selected test-source packets from
`annotation_sources.jsonl`. They read each **entire** source, mark all in-scope
expressions and occurrences, record distinct senses as appropriate, and set
`complete: true` only after exhaustive review. A fully reviewed source with no
terms has an empty `terms` array. Preserve source IDs and text hashes.

Gold spans must satisfy `text[start:end] == expression` using half-open Python
Unicode code-point offsets. UTF-8 bytes and browser UTF-16 indices differ. Save
adjudicated packets as `heldout-gold.jsonl`. Candidate-only review cannot identify
unproposed terms; the browser is not a complete-source gold-span editor. Use a
qualified annotation workflow and document disagreements and adjudication.

## 6. Run a bounded Broad pilot and resume explicitly

The reviewed Fireworks profile names `FIREWORKS_API_KEY`; the separate Gemini
profile names `GEMINI_API_KEY`. Configure only the selected service’s credential
through the named environment variable using the approved credential workflow.
Do not put values in recipes, shell command arguments, notebook output, or
exports. Configuring and estimating a real profile do not dispatch requests.

After explicit authorization for the concrete corpus and budget:

```sh
termfinder --project studies/jonathan-zheng collect --allow-paid --max-jobs 2
termfinder --project studies/jonathan-zheng status
termfinder --project studies/jonathan-zheng resume --allow-paid
```

The first invocation leaves remaining jobs pending. Completed work and caches
persist across processes. To request cancellation from another terminal:

```sh
termfinder --project studies/jonathan-zheng cancel
```

Inspect `status`, source failures, jobs, audit proposals, coverage, stage costs,
and the stop reason before resuming. Budget exhaustion leaves work pending.
Truncation recovery keeps grounded partial discoveries; unresolved partial
work remains visible. Coverage is processing coverage, not measured recall.
Reported provider-token costs are estimates, not reconciled invoices.

Known failed or unresolved partial extraction jobs can be requeued:

```sh
termfinder --project studies/jonathan-zheng retry-job JOB_ID
```

A parsing failure has no extraction job to retry: fix or replace the source and
ingest it again. An uncertain API outcome requires a deliberate decision:

```sh
termfinder --project studies/jonathan-zheng resolve-uncertain JOB_ID
```

That closes the unresolved outcome without another request. If a further
attempt is separately authorized:

```sh
termfinder --project studies/jonathan-zheng resolve-uncertain JOB_ID \
  --retry --acknowledge-possible-duplicate-billing
```

Queueing alone does not dispatch. Unknown reservations remain in the budget;
remote acceptance cannot guarantee exactly-once billing.

## 7. Add Specialists or compare independent arms

Save a Broad snapshot before adding lenses. Reapply the same research policy
with Specialists and inspect the new estimate:

```sh
termfinder --project studies/jonathan-zheng snapshot broad-v1
termfinder init studies/jonathan-zheng --recipe jonathan-recipe.json \
  --profile reviewed-profile.json --mode specialists
termfinder --project studies/jonathan-zheng estimate
```

After authorization for the extra passes, resume with `--allow-paid`. Broad
discoveries remain; routed specialist passes add evidence and candidates. Counts
of additions do not measure recall. Never delete singleton discoveries merely
because the other model omitted them.

For an experimental Broad/Specialists comparison, create two clean projects
using the same source files, metadata, policy, reviewed profile, and held-out
annotation rubric. Ingest the identical corpus into each, change only mode,
and freeze each result. Separate projects avoid mixing an existing inventory
with a comparison arm; provider nondeterminism still applies. Compare evaluated
precision, recall, false negatives, and costs, not only term counts. Keep Gemini
as a separately identified arm if studying it.

## 8. Inspect evidence, annotate, evaluate, and release a version

```sh
termfinder --project studies/jonathan-zheng inspect --term TERM_ID
termfinder --project studies/jonathan-zheng inspect --source SOURCE_ID
termfinder --project studies/jonathan-zheng serve
```

Check original spelling, exact context and offsets, page/heading locations,
source hashes, proposed meaning, definition quotation, and each extractor’s
provenance. An expression can be grounded while its proposed meaning is wrong.
Generated translations and attributes are not original evidence. Record human
judgments separately:

```sh
termfinder --project studies/jonathan-zheng annotate TERM_ID approved \
  --note "Checked complete source and contextual interpretation." \
  --attributes human-attributes.json --actor researcher-name
termfinder --project studies/jonathan-zheng undo-annotation ANNOTATION_ID
termfinder --project studies/jonathan-zheng relate TERM_A TERM_B alias
termfinder --project studies/jonathan-zheng undo-relation RELATION_ID
```

Annotation returns its ID; relation creation returns its ID. `rejected` and
`needs_review` are also supported statuses. `semantic_merge` and `distinct_sense`
are supported relation kinds. Undo retains history, and rejected terms remain
in the complete inventory. The loopback browser supports the same reversible
review; paid browser dispatch requires a separately authorized `serve
--allow-paid` session. It is not a shared hosted annotation platform.

Freeze the collection and evaluate against complete held-out labels:

```sh
termfinder --project studies/jonathan-zheng snapshot extraction-v1
termfinder --project studies/jonathan-zheng evaluate EXTRACTION_VERSION \
  heldout-gold.jsonl --split-manifest family-splits.json \
  --unit occurrence --out evaluation.json
termfinder --project studies/jonathan-zheng export EXTRACTION_VERSION \
  releases/extraction-v1 --formats csv,jsonl,parquet,annotation
termfinder --project studies/jonathan-zheng versions
```

Use `source-splits.json` if no family mapping was needed. Gold must cover
exactly the declared test sources. Inspect precision, recall, false-negative
contexts, and domain/language breakdowns. `--unit source_term` measures term
presence per source. `--require-sense` adds exact shared sense-label matching;
it does not judge semantic equivalence of free-text paraphrases.

The export manifest records recipes, prompts, profiles, sources, hashes,
collection dates, processing failures, coverage, costs, and supplied constraints.
Retain complete inventory alongside the approved subset. CSV is convenient for
inspection; JSONL/Parquet preserve distinctions that CSV cells cannot. Read
`schema.json` for nested JSON encoding and reversible spreadsheet escaping.
Re-exporting the same saved version to a fresh directory calls no models and
reproduces its records. Review source-use restrictions before sharing contexts.

For an update, ingest newly permitted sources, resume within a newly reviewed
finite budget, inspect results, and save `extraction-v2`. Preserve v1 and its
evaluation. Changed source text or parser output requires new frozen-text gold
spans. Changes in criteria require a new recipe version and careful comparison;
do not tune on held-out false negatives and continue calling that test set
unseen. Record sampling and remaining failures in every research report.
