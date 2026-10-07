# An auditable agent-assisted collection study

V6 separates planning assistance from evidence collection. A researcher's own
ChatGPT, Claude, or other agent can turn an idea into a proposed collection
policy and source list. V6 validates the submitted files, confines execution to
the reviewed scope and finite limits, records what actually happened, and keeps
each accepted evidence unit attached to frozen source text. A useful draft does
not become a verified scientific result merely because an agent produced it.

This protocol helps researchers prepare defensible methods and artifacts. It
does not guarantee publication acceptance, unbiased sampling, correct model
interpretations, or exhaustive extraction. The workflow is inspired by
[Thresh's configurable, inspectable evaluation interface](https://aclanthology.org/2023.emnlp-demo.30/),
without importing its implementation or providing a direct Thresh integration.

## 1. State the research contract before collection

Write the question in ordinary language, choose the evidence unit, and declare
the population you intend to study. Decide what is included, what is excluded,
what counts as a boundary case, and which interpretations need human judgment.
Record languages, communities, time interval, permitted sources, source-use
constraints, source/request/spending limits, extraction mode, and model profile.
Nonterm starter few-shots are synthetic English illustrations of the span
contract; the external agent must adapt examples and the annotation rubric to
the actual domain and languages. They are not independent evaluation gold.

Do not let a broad request such as "collect cultural opinions" silently become
permission to search every website, infer people's identities, or treat
generated answers as human opinions. An agent may explain missing decisions and
propose values; the researcher owns the final research policy. Keep unresolved
facts unavailable with a reason rather than converting plausible guesses into
metadata.

| Requested unit | Observed evidence that V6 can ground | Interpretation that remains a separate judgment |
| --- | --- | --- |
| Term | Exact spelling and context in the frozen source | Meaning, novelty, cultural association, alias equivalence |
| Idea | A contiguous passage expressing a proposed claim, explanation, or proposal | Whether two passages express the same idea; truth, importance, originality |
| Opinion | A contiguous passage containing an expressed assessment or stance | Stance target, speaker attribution, sincerity, endorsement, cultural representativeness |
| Sentence | An exact source span under the declared selection policy | Relevance, quality, readability, entailment, and ambiguous sentence boundaries |

Ideas and opinions are extractive evidence units. A generated paraphrase belongs
in a suggestion field; it must not replace the observed passage or pretend to be
a quotation. A sentence spanning discontinuous source fragments is not one
exact contiguous evidence span. Full argument graphs, conversation datasets,
table records, and automated benchmark construction remain extension points.

## 2. Preserve the planning trail

Save the original brief, generated agent instructions, returned agent bundle,
deterministic validation result, and the reviewed plan as distinct artifacts.
V6's handoff workflow retains their content hashes and associates the imported
plan with the project. Preserve any relevant external agent conversation,
model/settings information, search logs, and attachments in the study archive;
V6 cannot recover chat history that was never supplied. The bundle is retained
as submitted JSON content in canonical serialization; its hash is not a promise
to preserve the original file's whitespace. Save the original response file
separately if byte-level agent-message archival matters.

The agent should submit an input bundle, not executable code. Its source list is
a proposal. Sources become evidence only after V6 retrieves or ingests permitted
content, records its hashes and locations, and passes occurrence checks. The
researcher reviews the policy, resolved source paths/URLs, and finite budget
before import. Future changes require another versioned plan and review rather
than silently altering a released dataset's scope.

Applying a validated plan materializes its collector inputs under
`PROJECT/agent-inputs/<bundle_sha256>/`. Preserve that directory's
`manifest.json` together with the compiled `brief.json`, `bundle.json`,
`recipe.json`, `profile.json`, `sources.json`, per-source metadata files,
`sampling.json`, `evaluation.json`, `search_log.json`, `agent.json`,
`prompt.md`, and `urls.txt`. Their hashes let a reviewer join the personal
agent's submitted proposal to the concrete inputs used by the collector.

Keep the authorization record as concrete as the plan: what scope was reviewed,
which file hashes were imported, and what collection invocation or browser
session was authorized. A checked "approved" value written by an agent is not
human authorization. Input files cannot authorise paid requests, broaden a
domain allowlist or local root, execute tools, or change credentials.

## 3. Make source selection assessable

For each proposed source, record its locator, selection rationale, relationship
to the question, and any available discovery query, search tool, search time,
result order, and parent source. Save ranks or other extra search-service fields
in an external archive when they are outside the strict bundle schema.
Unknown provenance should remain explicitly
unavailable. Distinguish sources supplied by the researcher, returned by an
external search, followed from an existing document, and merely suggested from
an agent's memory. Record exclusions and access failures as well as successes.

Describe the sampling mechanism in the paper. Useful designs include a complete
list from a declared repository snapshot, a random sample from a documented
sampling frame, a fixed set of queries and date/domain restrictions, or an
explicit convenience sample. An AI-generated source list is usually a
non-probability sample unless an independently documented design establishes
otherwise. It does not establish a census of a community or literature.

The denominator for processing coverage is the submitted or discovered source
set under those limits. It is not every potentially relevant source online.
Report numbers proposed, rejected by scope, duplicates, retrieval attempts,
successfully parsed, excluded by policy, attempted by extraction, unfinished,
and included in the released dataset. Keep the permitted source limit distinct
from a quota for extracted records: there is no requirement that every source
produce a particular number of terms or spans.

Bounded V6 search/fetch is optional. A personal agent's earlier web browsing is
outside V6's request/cost counters. Account for that external activity separately
when reporting total study costs. A source's availability, publication date,
license, or truth cannot be inferred solely from an agent's description of it.

## 4. Freeze evidence and state the reproducibility boundary

Retain a source inventory with identifiers, locators, retrieval dates, available
publication dates, raw-content hashes, parsed-text hashes, parser versions,
language/community metadata, useful blocks, and use constraints. Inspect
parsing before relying on its output. PDF page locations refer to the extracted
pages; Unicode offsets refer to frozen parsed text, not original PDF/HTML byte
positions. Scanned PDFs needing OCR are visible failures until a reviewed OCR
extension or separately supplied text resolves them.

The exported evidence chain is:

```text
brief and agent handoff hashes
  → reviewed recipe/profile/source plan
  → source locator + raw/text hashes + retrieval/parser metadata
  → job/window + prompt/model provenance
  → exact expression and context spans + source locations
  → human annotation/relation history
  → frozen dataset version + exported-file hashes
```

Check a record by locating its source in the saved dataset, verifying the text
hash, and checking `source_text[start:end] == expression`. Check the context
span independently. This establishes occurrence in that frozen representation.
It does not establish that an extracted claim is true or that a meaning follows
from the quotation.

V6 snapshots preserve parsed evidence and records. A raw hash identifies the
retrieved original but does not itself preserve those original bytes. If
rerunning parsing or auditing visual layout matters, retain permitted originals
in a separate study archive with matching raw hashes. Record any redaction,
normalization, or upstream conversion and preserve its input/output lineage.
If originals cannot be redistributed, document an access procedure or an
explicit reproducibility limit rather than promising unrestricted reconstruction.
The optional source constraint `original_bytes_archive` records an archive
reference. The publication audit reads only frozen JSON and explicitly treats
that reference as an unverified declaration; it does not inspect the archive
or certify its contents.

| Layer | Repeatable operation | Limit to disclose |
| --- | --- | --- |
| Input validation and plan compilation | Same valid inputs and software produce the same validated plan content | Researcher/agent drafts can vary |
| Scope/path/limit gates | Fixed reviewed policy controls eligible operations | Gates do not certify a source's license, quality, or representativeness |
| Parsing and window planning | Frozen bytes and pinned parser/configuration define source text and windows | Live sources change; layouts and OCR can be imperfect |
| Extraction | Cached replies can be reused under their recorded contract | Fresh model calls can differ; aliases and provider software can change |
| Grounding and deterministic deduplication | Fixed frozen text and proposals produce the same occurrence checks | Exact occurrence is not semantic correctness; paraphrase merges are not automatic truth |
| Human annotation | Events and reversals remain traceable | Reviewers can disagree; judgment needs a declared rubric |
| Saved-version export | Stored records export without calling models | Parquet byte reproduction depends on the pinned writer version |

Reproduce a release by exporting its saved dataset version, not by rerunning the
agent or recollecting live URLs. Rerunning extraction is a new experiment whose
agreement with the previous run can be measured; it is not required to recreate
the original records.

## 5. Keep uncertainty, failures, and costs visible

Preserve grounded discoveries from either extractor, including single-model
discoveries. Model agreement, candidate counts, occurrence frequency, and a
model's `coverage_complete` flag are not measurements of recall. A model's
refusal or incorrect offset must not silently erase other exact grounded
discoveries. Unresolved or invalid proposals belong in the audit queue.

Budget/deadline limits, cancellation, parsing failures, malformed responses,
truncation, exhausted recovery, and uncertain API outcomes remain visible in
job/run state. Describe what was unfinished at release time. Compare successful
and failed source groups when failures could bias a language/domain analysis.
Do not convert a budget stop into a claim that enumeration finished.

Report estimates, configured rates, known token-based cost estimates, simulated
offline costs, and uncertain reservations separately. Provider invoices can
differ from configured token estimates. A lost response can have been billed;
explicit retries can duplicate billing. V6 cannot guarantee provider-side
exactly-once execution. Translation suggestions, external search, OCR, and human
annotation costs require their own accounting when used.

## 6. Evaluate independently at the source level

1. After applying the plan and completing intended source ingestion, use
   `termfinder --project STUDY freeze-corpus --name corpus-v1 --seed v6-agent-study-v1`
   or `Project.freeze_agent_corpus`. Do this before any extraction job is
   prepared for those source content hashes. V6 rejects a late freeze even when
   the earlier job attempt failed or stopped at a zero budget.
2. Inspect the saved corpus version and `human-review/<dataset_version>/`.
   V6 creates `family-map.json`, `source-splits.json`, full-source blank
   `annotation_sources.jsonl`, and held-out blank `heldout_sources.jsonl`.
   The plan's holdout fraction and recorded seed assign complete source
   families to development/train or test; validation is empty in this helper.
   Known translations, document versions, threads, or problem variants must
   have a common family ID in the submitted plan. Missing family IDs fall back
   to individual sources and do not prove independence. Small corpora can have
   an empty test split; inspect the counts before claiming recall. Fix the
   study design before outcomes are examined rather than searching for a
   convenient seed after looking at candidates.
3. Give qualified annotators complete held-out sources and the fixed inclusion
   rubric. Use blank complete-source packets, not the model's candidate list.
   Annotate all eligible spans, including negative sources with zero records.
4. Keep annotation provenance, training examples, annotator qualifications,
   disagreement handling, and adjudication rules in a separate study record.
   A file's `complete: true` flag is an annotator assertion; software cannot
   prove that a human exhaustively read the source or was blinded. The freeze
   gate checks this project's job history; it cannot verify prior human exposure
   or candidates produced by an external agent or another project.
5. Run extraction against the same frozen source identifiers and text hashes.
   Evaluate exact occurrence precision/recall and false negatives by language
   and domain. Report source-level coverage, source counts, and pending/failing
   groups beside the metrics.
6. Evaluate meanings, ideas, opinions, or sentence relevance under a separate
   adjudicated rubric. The built-in exact-span score measures detection under
   the gold boundaries; it does not measure truth or semantic equivalence.
   Optional exact sense matching requires a shared label convention, not free
   paraphrases. Discuss legitimate boundary variants and ontology disagreement.
7. If estimating uncertainty, resample independent sources or families, not
   individual dependent occurrence rows. Statistical uncertainty procedures
   and semantic scoring are external analyses; V6 does not silently supply them.

For example, after humans complete and adjudicate a separate
`heldout-gold.jsonl`, evaluate a collected release against the exact saved split.
Copy the `version_id` returned by the release snapshot and replace
`RELEASE_VERSION_ID` below with that ID; a display name such as `release-v1`
does not resolve to a saved version:

```sh
termfinder --project STUDY evaluate RELEASE_VERSION_ID HUMAN_REVIEW/heldout-gold.jsonl \
  --split-manifest HUMAN_REVIEW/source-splits.json --unit occurrence \
  --out evaluation.json
```

Replace `HUMAN_REVIEW` with the directory returned by `freeze-corpus`. Preserve
the blank original packet and use a separate file for the human gold. The
validator requires complete packets with matching frozen source hashes and
exact source spans; passing the split manifest requires coverage of exactly
its held-out sources.

For term studies, complete-source gold packets retain the compatibility key
`terms`. For idea, opinion, and sentence studies, packets declare `data_type`
and use `records` with exact `observed_text` (or the compatibility `expression`)
and source occurrences. Consult the frozen export schema for the selected unit.
Candidate review can estimate candidate quality but cannot find what the
extractor omitted. Unknown metrics remain null with a reason. A synthetic
fixture's perfect score demonstrates mechanics, not accuracy on research data.

## 7. Prepare a release package a reviewer can inspect

Export an immutable version and preserve its manifest, schemas, recipe,
prompts, model/profile versions, sources, occurrences, suggestions, annotation
history, relations, discovery decisions, jobs, audit queue, costs, and hashes.
The generic `records` and `evidence` tables cover all types; `terms` is the
lexical subset and `occurrences` is a compatibility evidence table. The full
grounded inventory and a researcher-approved subset are separate artifacts.
State which one is used in each experiment and why.

Alongside the V6 export, retain the original brief/agent bundle, the review
record, corpus/sampling statement, split/family map, independently annotated
gold, evaluation report, parser input archive where permitted, software lock
files, and any external semantic analyses. Check source-use constraints before
releasing context text or originals. Creating a local export does not authorize
publishing it. Remove secrets from externally archived agent conversations and
never include provider credentials in a reproducibility package.

## Questions a demanding reviewer can ask

| Question | Evidence and honest answer |
| --- | --- |
| Did the AI invent data? | Show exact occurrence/context spans and frozen source text. Suggestions are labeled separately. Unsupported proposals stay in audit. |
| Did it invent or cherry-pick sources? | Show proposed versus retrieved sources, search provenance and rejection decisions. State the actual sampling design; agent suggestions do not prove completeness. |
| Who chose the research definition? | Show the original brief, human-reviewed policy, version history, and the boundaries/examples fixed before evaluation. |
| Can a document change the collection plan? | Input bundles are data; scope/path/budget gates operate in deterministic code. Source/extraction text is not routed to tool execution or configuration. |
| Are your "ideas" actually generated summaries? | Release exact source passages as the observed units, with paraphrases/labels stored as model suggestions or human annotations. |
| Is the extracted opinion the author's view? | Check explicit attribution in context and human labels. Mentioned, quoted, hypothetical, and endorsed statements require separate judgments. |
| How do you know recall? | Compare against independent exhaustive annotations of complete held-out sources. Candidate counts and agreement cannot answer the question. |
| Does grounding validate meaning or truth? | No. It validates occurrence. Report separate semantic/factual adjudication under the declared rubric. |
| Did source overlap leak into testing? | Show the pre-extraction freeze event, saved corpus/split/family map, source hashes, and annotation timeline. The helper blocks late freezing against project job history; exposure outside V6 still needs a documented procedure. |
| What happened to one-model discoveries? | They remain in the complete grounded inventory. Human review creates an additional subset with reversible events. |
| Were hard sources silently removed? | Show parse/fetch failures, excluded sources, unresolved proposals, pending windows, and language/domain denominators. |
| Can I reproduce the exact release? | Re-export the saved dataset version with pinned dependencies and compare manifest file hashes. Fresh model generation is not asserted to be deterministic. |
| Can I reproduce original parsing? | Provide permitted originals with raw hashes, or clearly state access and redistribution limits. A raw hash alone is insufficient. |
| Are aliases and senses arbitrarily collapsed? | Show conservative identifiers, distinct senses/communities, and reversible human relations. Semantic equality is not inferred from string normalization. |
| Are your cost and coverage claims precise? | Separate configured estimates, actual known usage estimates, uncertain reservations, invoices, external agent costs, and measured recall. |
| Is this a reproduction of a lab dataset? | No unless a separately conducted study demonstrates it. Publications motivate the policy; an illustrative recipe is not their original collection procedure. |

## A methods paragraph to complete, not copy as a result

> We collected **[unit type]** from **[declared sampling frame and source policy]**
> during **[collection interval]**. A researcher supplied a brief to **[external
> agent/model and settings, if known]**, which proposed **[policy/source inputs]**.
> The reviewed input bundle and V6 plan are archived under **[hashes/version]**.
> V6 used **[pinned software/parser/profile/prompt versions]**, fixed scope and
> finite limits of **[limits]**, and retained the union of exact grounded
> discoveries. **[N]** sources were proposed, **[N]** parsed, **[N]** excluded,
> and **[N]** failed or remained unfinished. Meanings and research labels were
> **[model suggestions/human adjudication procedure]**. We evaluated **[N]**
> complete held-out source families against independent annotations under
> **[rubric]**, reporting **[detection and semantic metrics]**. Dataset
> **[version]** exports from stored evidence without new model calls. Our
> conclusions are limited by **[sampling, language, interpretation, parsing,
> and access limitations]**.

The workflow event hash chain checks internal consistency. It is not an
authenticated signature, an independent timestamp service, or protection
against someone who deliberately rewrites all artifacts and recomputes hashes.
Retain a trusted release digest or use the institution's normal archival
process when stronger integrity evidence is needed.

Fill the placeholders with measured facts. Do not replace them with expected
numbers or use source processing completion as a proxy for recall.
