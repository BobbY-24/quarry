# Research ideas your own agent can turn into V6 inputs

These briefs are starting conversations, not hand-written extraction recipes.
The browser form can create the same information without editing JSON. V6
generates the request for your existing ChatGPT, Claude, or other agent; that
agent returns one policy/source bundle for V6 to check and import.

| Starting point | Choose | Tell your agent | Publication motivating the example |
| --- | --- | --- | --- |
| [Jonathan's community vocabulary](jonathan-neologisms.brief.json) | Term | Include new expressions and shifted senses; exclude entity-only names; keep singleton evidence | [NEO-BENCH](https://arxiv.org/abs/2402.12261) |
| [Tarek's cultural entities](tarek-cultural-entities.brief.json) | Term | Include established food entities; preserve original script; label proposed association | [Camellia](https://arxiv.org/abs/2510.05291) |
| [Geyang's cultural opinions](geyang-cultural-opinions.brief.json) | Opinion | Collect explicitly expressed assessments; preserve attribution and source origin | [CARE](https://arxiv.org/abs/2504.05154) |
| [Medical sentences](medical-sentences.brief.json) | Sentence | Collect complete source sentences containing jargon for independent readability annotation | [MedReadMe](https://arxiv.org/abs/2405.02144) |
| [Legal ideas](legal-ideas.brief.json) | Idea | Collect exact clauses expressing obligations or case facts; preserve qualifications | [GAVEL](https://arxiv.org/abs/2601.04424) |

These are proposed pilots informed by publications, not the students' assigned
projects or reproductions of the papers' datasets. The two alumni projects are
lab precedents. No research data has been collected for these examples.

All examples permit only a researcher-owned `./corpus` folder, use the reserved
`local-only.invalid` domain, allow at most 15 sources, and set extraction spending
to zero. They prepare a plan and expose budget stops without authorizing paid
collection. Replace the folder/scope and choose a finite budget in a new reviewed
brief for a real study; do not ask the agent to widen them in its response.

## Ordinary browser use

1. Start V6's local browser: `termfinder --project my-study serve`.
2. Choose Terms, Ideas, Opinions, or Sentences in the agent setup form. Describe
   the question and provide permitted folders/domains and finite limits.
3. Click **Create request for my AI agent**, then **Copy agent request**.
4. Paste it into your own agent. Attach the downloaded template or handoff files
   when convenient. The agent writes the recipe, source metadata, and study
   notes; the researcher supplies the scientific decisions and permission scope.
5. Bring back the JSON bundle and click **Check plan**. Use **Copy correction
   request** if it needs repair. Read the policy, source list, and limitations.
6. Click **Apply this plan** for local sources. **Fetch reviewed website sources**
   is a separate explicit action for remote sources.
7. Inspect parsed evidence and estimate costs. Before collection, click
   **Prepare blind source review**. V6 saves the corpus, grouped source-family
   split, and blank full-source/held-out annotation packets together. Give the
   held-out packet to independent annotators before viewing candidates, then
   collect within an explicitly authorized finite budget. Save/export the
   release version after evidence review and independent evaluation.

The student does not manually maintain the individual downstream JSON files.
The returned bundle remains inert data, and V6 checks it server-side before
configuration or ingestion. The external agent is not logged in or called by V6.

After applying a plan, **Generated collector input files** shows the local
`my-study/agent-inputs/<bundle_sha256>/` directory. It contains the recipe,
profile, source list and per-source metadata, original brief/bundle in canonical
JSON, sampling/evaluation/search notes, agent metadata, prompt, URL list, and
hash manifest. V6 creates these files; the researcher does not edit them one
by one.

## A terminal example with a saved brief

From the V6 checkout after installation:

```sh
mkdir -p my-study/corpus
cp examples/agent_workflow/jonathan-neologisms.brief.json my-study/brief.json
cd my-study
# Put permitted source files in corpus/ before asking the agent to list them.
termfinder --project . prepare-agent --brief brief.json --out handoff
```

Copy `handoff/prompt.md` into your own agent, attach the other handoff files, and
save its returned JSON as `returned-bundle.json`. Then:

```sh
termfinder --project . validate-plan returned-bundle.json --out validation.json
# Read the plan; fix all errors or unresolved questions with the repair prompt.
termfinder --project . apply-plan returned-bundle.json
termfinder --project . ingest-plan
termfinder --project . estimate
termfinder --project . freeze-corpus --name corpus-v1 --seed v6-agent-study-v1
```

These commands contain no provider credentials and make no model request.
`ingest-plan` explicitly retrieves eligible remote URLs if the reviewed plan
contains them; these local-only examples do not. Source listing by an external
agent may use that agent's separately authorized browsing and cost account.

`freeze-corpus` reports a `human-review/<dataset_version>/` directory with
`family-map.json`, `source-splits.json`, `annotation_sources.jsonl`, and
`heldout_sources.jsonl`. Blank packets require complete human annotation;
they are not gold labels. The freeze must precede any extraction job for those
content hashes, including a failed or budget-stopped attempt. Small collections
can have an empty held-out split. Unknown families fall back to individual
sources, and prior exposure outside this project cannot be verified by V6.

For a release after collection, annotation, and held-out evaluation:

```sh
termfinder --project . snapshot release-v1
# Copy the returned version_id; replace RELEASE_VERSION_ID below with that ID.
termfinder --project . publication-audit RELEASE_VERSION_ID --out publication-audit.json
termfinder --project . export RELEASE_VERSION_ID release --formats csv,jsonl,parquet,annotation
```

The display name `release-v1` is not a lookup alias. Use the returned `dataset_…`
version ID for every audit, evaluation, and export.

## What to ask the agent to get right

Ask for sources actually inside your authorized folder or domain scope, not
invented locators. Each source needs its reason for selection, available search
provenance, original/generated content origin, and any known source-use limits.
Unavailable facts remain null with reasons. The agent should explicitly report
sampling limitations and any blocking research question it cannot resolve.

Nonterm starter few-shots are synthetic English illustrations of the span
contract. Ask the agent to adapt the rubric and examples to the actual domain
and languages; do not treat those examples as independent gold labels.

Terms retain exact spelling and contextual senses. Ideas, opinions, and
sentences retain exact contiguous passages. Summaries, meanings, translations,
stance labels, and cultural associations belong in suggestion fields until
reviewed. The deterministic check establishes that text appears in the source;
it does not prove truth, semantic type, sentence completeness, or representativeness.

Read [the six-step agent workflow](../../docs/AGENT_WORKFLOW.md) for examples and
[the publication protocol](../../docs/PUBLICATION_PROTOCOL.md) for complete-source
evaluation, evidence lineage, reviewer questions, and reproducibility limits.
