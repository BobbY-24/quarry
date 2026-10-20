# A short workflow for a research student

**Tell your own coding agent what to collect; stay in that conversation.**
The agent handles study selection, structured inputs, source preparation,
cost review, collection, evidence inspection, and exports through Quarry's fixed
tools. You decide the research scope and approve a concrete plan. You do not
write JSON, move bundles, manage review IDs, or open a browser to finish.

## Set up once

Ask the agent to install the reviewed local package and enable its project-local
skill/MCP connection using the [one-time setup prompt](AGENT_NATIVE.md).
After installation, the manual connection command is:

```sh
termfinder connect --host codex --workspace /path/to/research-workspace \
  --studies /path/to/research-workspace/v6-studies
```

Choose `claude` for Claude Code or `generic` for a different harness. The command
prints the files and host-specific activation steps. Reopen the trusted
workspace if required, accept the host's normal connection controls, and ask
the agent to verify a real `list_studies` call. Generic hosts may need manual
registration of the generated local definition. This is setup once per
workspace, not once per study; new sessions reopen saved studies.
Choose an existing specific workspace. Quarry creates its default studies folder;
an external studies root must already exist.

Quarry does not modify home/global agent settings, install hooks, run a persistent
service, or call paid models during connection. Matching repeats are idempotent;
conflicting configurations or changed launch gates require a fresh workspace
or an explicitly reviewed Quarry-only migration. Existing host settings are preserved.

Start with the offline fake profile and zero dollars for a rehearsal. Real
collection requires the selected provider's environment configuration, a finite
budget, and a separately authorized connection launched with `--allow-paid`.
Planning-agent charges are outside Quarry's cost ledger. Never put credentials in
the study, agent bundle, notebook output, URL, or command arguments.

## What the student does each time

1. **Describe the study.** State the exact collection unit and inclusion rule,
   permitted source folders/domains, languages, dates, source cap, mode, model
   profile, and finite budget. When the agent asks about a genuine research
   ambiguity, decide it. The agent may draft examples and fields but cannot
   enlarge those boundaries through its plan.
2. **Read one concrete plan in conversation and approve it.** The agent submits its inputs
   directly. Quarry validates them, imports the declared local documents, fetches
   only listed URLs when explicitly selected, freezes the corpus and blank
   whole-source packets, and calculates a length-based estimate. Check the
   source selection reasons, rights, exclusions, failures, effective models,
   and remaining research questions. Large tool results are previews; the
   agent retrieves all review sections and source pages before presenting a
   complete review. Approve that exact plan in the conversation. Collection and resume use the
   same review; changes to its source/configuration/prompt/cost bindings
   invalidate it. The guided path currently requires an unseen corpus for a new
   plan after processing; see the protocol limit below.
3. **Ask for evidence when needed.** For example: “Show the exact context and
   proposed meaning for this expression.” The agent searches the complete
   grounded inventory and opens bounded records/sources to show spelling, context, offsets/pages,
   source hash, dates, and extraction provenance. Optional human annotations
   can be relayed from your actual judgments and undone without deleting the
   underlying record. Agent suggestions do not change human approval.
4. **Ask for the dataset.** Say: “Save and export `pilot-v1`; show coverage,
   costs, failures, and publication findings.” Quarry writes CSV, JSONL, Parquet, annotation files, manifests, and
   publication findings. Reusing that release name or saved version reproduces
   its frozen records without a new model call. Use a new name after changes.

The next day, say: “Open `ev-language`, show remaining work and costs, and
resume its unchanged approved plan.” The agent handles the saved study and
review identifiers; resume does not reset the budget. Ask “Show a visual view”
only when useful. The optional local **Plan, Evidence, Dataset** browser shows
the same project and provides span inspection and reversible annotation forms.
For a web-chat agent without local tools, its expandable prompt/bundle import
remains a fallback; it is not the default connected-harness experience.

For websites, ask the agent to show the proposed source list before fetching.
It can inspect the whole validated proposal in conversation even when no
documents are captured yet. Fetch only those permitted URLs when authorized,
then review the frozen sources and cost estimate before collection. Failed or
pending preparation is visible; an empty ready dataset is not substituted.

The agent's progress report shows pending, partial, failed, cancelled, deferred, and
uncertain work with its costs and recovery options. Cancellation stops further
dispatch; an already sent request can finish or have an uncertain bill. Resume
does not reset a budget. Uncertain-request retries follow the saved finite
recovery policy and record their billing risk; providers may charge twice. Original
files are not needed to resume an unchanged fully captured plan, but retain
their bytes and permissions separately for parser replay and publication.

**Protocol limit:** the guided path reuses an unchanged pre-extraction freeze.
It refuses to present previously processed text as a newly blind corpus. After
jobs exist, changing the recipe, provider profile, or budget needs the advanced
execution/evaluation protocol or a separate study; it does not automatically
reuse that old freeze for a new plan. Incremental plans can add unseen sources
while retaining the earlier inventory. Do not merge their held-out splits or
claim independent blindness without a separately specified research protocol.

## Three publication-inspired student examples

These are proposed extensions guided by published NLP research. They are not
assignments, evidence of adoption, or reproductions of the cited datasets. All
actual corpus files, rights, languages, and hypotheses belong to the researcher.

### Expressions and changing senses

[NEO-BENCH](https://arxiv.org/html/2402.12261v4) motivates a vocabulary study.
A researcher can tell their agent:

> Use Quarry for terms in my permitted dated EV-community exports. Find new
> expressions and changed senses. Exclude names used only as names. Retain
> one-off uses and different community senses. Use Broad, the GLM + DeepSeek
> profile, at most 30 sources and a $10 cap. Show me the sources and estimate
> before collection. Do not start a paid run until I approve this plan.

The agent proposes a neologism recipe with examples of a novel expression, an
established spelling with a changed sense, and a name to exclude. Quarry checks the
scope, imports the text, and freezes the source families before extraction.
The researcher reviews complete held-out sources for the rubric independently of the
candidate list. He then inspects each expression's literal occurrence and
proposed sense. A term seen once by only GLM remains retained if grounded.
His dataset reports first observation in this corpus; it makes no claim that
the date is the expression's actual coinage date.

### Cultural expressions and entities

[Camellia](https://arxiv.org/abs/2510.05291) motivates cultural vocabulary and
entity collection. A researcher can tell their agent:

> Use Quarry for culturally situated entities and expressions in these permitted
> unmasked Arabic, Chinese, Japanese, and English passages. Include established
> names, keep original scripts, and preserve contextual senses. Cultural
> association needs a supporting passage or remains unknown. Use Specialists
> with the GLM + DeepSeek profile, at most 25 sources and a $15 cap. Prepare the
> source and cost review first.

The agent changes the inclusion rubric to retain cultural entities and routes
specialists by the declared communities. Quarry keeps exact original-script spans
and distinct senses; it does not transfer a neologism exclusion to this study.
The researcher reviews translations and cultural attributes separately from the observed
text. Bilingual annotators label complete held-out source families using the
frozen rubric. The export distinguishes original contexts, any proposed
translations, supported definitions, and model-proposed meanings. The $15 is a
user-selected cap, not a promised cost or permission to start a paid experiment.

### A medical-readability student or RA: jargon and sentences

[MedReadMe](https://arxiv.org/abs/2405.02144) motivates a medical-document
workflow. The student can tell their agent:

> Use Quarry to collect established medical jargon from my permitted text-bearing
> PDFs. Keep page locations, definitions that the source explicitly supports,
> and the original context. Do not infer that an occurrence is hard to read.
> Use Broad and a $10 cap for at most 12 documents. Show failures and the
> PDF-length estimate before I approve collection.

For a sentence study, the student changes the collection unit to **Sentence**
and asks for complete source sentences under a specified readability rubric.
The agent drafts a separate recipe, keeping readability labels for human
annotation. Quarry preserves exact sentence spans and page provenance; it does not
turn a model's readability suggestion into an observed judgment. Image-only
PDFs show a parsing failure and need a separately reviewed OCR extension.
Humans annotate complete source documents, with documents/versions grouped in
the split, before evaluating omissions. Vocabulary collection and sentence
collection remain separate releases with different units and rubrics.

An opinion alternative inspired by [CARE](https://arxiv.org/abs/2504.05154)
collects exact attributed assessments or preferences. It does not create
preference rankings or infer a speaker's demographic identity. An idea study
collects exact passages expressing claims or proposals, with qualifiers intact.

## Where reliability and rigor live

| Researcher's experience | Quarry's enforced behavior | What it cannot establish |
| --- | --- | --- |
| Ask the agent for a plan | Versioned schemas; source/language/date/domain/budget bounds; no execution of extraction payloads | An agent's source-selection claim or search log is true |
| Review one concrete plan | Frozen sources, grouped splits, blank complete-source packets, cost assumptions, hash-bound approval | Who actually approved, independent blindness outside Quarry, or sampling representativeness |
| Start or resume | Project admission lock, persistent jobs, bounded workers, retries, timeouts, caching, budget reservations | Exactly-once provider billing or bit-identical future model responses |
| Inspect Evidence | Exact Unicode offsets/locations, source hashes, grounded union, reversible annotations and relations | Correct proposed meaning, factual truth, or historical novelty |
| Save and export | Immutable dataset version, audit findings, file hashes and reproducible records | Permission to redistribute source text or publication acceptance |
| Evaluate quality | Deterministic comparison to complete-source gold; precision, recall, and false negatives by domain/language | Recall from candidate counts, model agreement, or candidate-only review |

The full inventory remains available alongside the human-approved subset. Keep
blind held-out annotators separate from candidate review, retain source-family
grouping, and report the sampling/rubric and adjudication process. Generated
meanings, translations, and model annotations remain suggestions. See the
[publication protocol](PUBLICATION_PROTOCOL.md) and
[evaluation procedure](EVALUATION.md) for the advanced analysis steps.

## How close this is to Thresh and Paper2Agent

| Tool | Routine user path | Setup and research boundary |
| --- | --- | --- |
| [Thresh](https://aclanthology.org/2023.emnlp-demo.30/) | Configure a typology and data, then use the annotation interface | Fine-grained human annotation and deployable interfaces |
| [Paper2Agent](https://github.com/jmiao24/Paper2Agent) | Install a skill/connect tools, then request scientific work through a coding agent | Building paper-derived tools needs their code/environment and verification |
| Quarry | Install/connect once, then ask the same agent to prepare, review, collect, inspect and export | One workspace connection manages multiple studies; deterministic collection/evidence/recovery gates remain underneath; the browser is optional |

Quarry follows Thresh's visible task-focused annotation direction and Paper2Agent's
agent-to-tool interaction. Its tools are fixed collector operations; it does
not execute an agent-generated research program. The shorter flow is
implemented and exercised offline. Equality of usability has not been measured:
a real student session with a chosen Claude/Codex client is a remaining field
acceptance check. The primary repositories above explain each comparison;
they should not be read as claims that either tool lacks research rigor.

## Rehearse and use the API

Run the synthetic acceptance walkthrough with no credentials:

```sh
python examples/simple_workflow_demo.py --out simple-demo
```

It exercises four data types in Broad and Specialists, frozen review, approval,
partial work/resume, single-extractor retention, exact Unicode evidence,
annotation undo, and byte-identical saved exports. It uses scripted plans and
fake replies; it measures software behavior, not semantic quality or usability.

For a saved study and an input bundle prepared by the agent:

```sh
termfinder --project studies/my-study review-plan --bundle agent-plan.json
termfinder --project studies/my-study approve-review REVIEW_ID
termfinder --project studies/my-study run-review REVIEW_ID --offline
termfinder --project studies/my-study release research-v1
```

`REVIEW_ID` is returned by `review-plan`; coding agents manage it automatically.
For notebooks, the same operations are available without CLI parsing:

```python
from termfinder import Project
from termfinder.workflow import prepare_review, approve_review, run_review, release_dataset

project = Project("studies/my-study")
review = prepare_review(project, bundle=agent_bundle, fetch_remote=False)
# Display the readable review. The researcher's actual decision precedes this call.
approve_review(project, review["review_id"], approval_origin="notebook")
progress = run_review(project, review["review_id"], max_jobs=1)  # fake profile rehearsal
progress = run_review(Project(project.path), review["review_id"])  # resume
release = release_dataset(project, "research-v1")
```

Real profiles require `allow_paid=True` in an explicitly authorized pilot. A
fake profile does not provide useful extraction for arbitrary research text.
The [working notebook](../examples/simple_student_workflow.ipynb) includes a
synthetic agent-plan surrogate, evidence inspection, and release reproducibility.
