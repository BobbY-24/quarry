# Evaluation design informed by Thresh

Design proposal, October 6, 2026. This document specifies a sequence of evidence
to collect; it is not a frozen study, execution authorization or a result. It
narrows the broader [H1–H4 methods](V7_METHODS.md) for a first systems paper and
a subsequent empirical study. Current checks and limitations remain in
[V7_VERIFIED.md](V7_VERIFIED.md).

## What Thresh actually contributed

The [Thresh system paper](https://aclanthology.org/2023.emnlp-demo.30.pdf)
demonstrates 11 existing frameworks, configurable span/annotation interfaces,
bidirectional data conversion and deployment routes (§§1, 3–5). Its Python
loader checks annotation/configuration consistency. It does not report a
controlled annotation-time or quality-superiority study.

The [current author repository](https://github.com/davidheineman/thresh#demo-data-sources)
documents samples of 50 annotations from existing datasets and explicit exceptions;
these demonstrations are not 11 newly recruited annotation studies. Repository
documentation inspected today is not evidence of its exact 2023 state.

A real application is documented in the companion
[SALSA paper](https://aclanthology.org/2023.emnlp-main.211.pdf): its interface uses
Thresh; it reports about 19,000 edit annotations on 840 simplifications. Six
undergraduates received tutorials, exercises, two onboarding rounds and feedback.
Three annotators selected spans, a fourth adjudicated, then the initial three
classified/rated edits. Agreement was assessed before adjudication (§§2, 3).

Our interpretation: demonstrate representative tasks and preserved data, make the
workflow independently reproducible, and show one genuine scientific application.
These sources do not establish Thresh's controlled speed advantage or guarantee
publication acceptance. No Thresh code/conversions were executed in this audit.

## One central systems claim

Proposed claim: **Researchers can use their existing agent to configure and
complete bounded term-and-sense studies while retaining traceable evidence,
explicit incomplete work and reproducible reviewed results.**

Evidence must show actual task completion and preserved artifacts across differing
requirements. Ease-of-use, extraction superiority and annotation-time savings
remain separate empirical questions. H3 supplies engineering evidence; H4 supplies
formative workflow evidence; H1/H2 require their own scientific comparisons.

## 1. Demonstrate representative workflows

Create six small case packs using hand-authored fixtures first, then permitted
domain sources after authorization. Two or three complete sources per case is
a proposed engineering scope, not a sample size for extraction-quality claims.
Choose different demands rather than matching Thresh's number of frameworks.

| Case | Variation to configure | Evidence to inspect |
| --- | --- | --- |
| Community expressions | New words, multiword terms and ordinary-word exclusions | Single-extractor discoveries survive union; excluded interpretations remain reversible. |
| Contextual senses | One expression with different meanings and ambiguous uses | Source occurrences remain distinct; meanings stay proposals until human judgment. Detection alone does not verify distinct senses. |
| Multilingual culture | Unicode/no-whitespace text, translation-linked families | Exact codepoint locations; translations remain one family; qualified native-language review is required. |
| Scientific/medical jargon | Established jargon rather than novelty | Domain-specific eligibility and intended audience are explicit; no novelty requirement is silently imposed. |
| Long/repeated text | Expressions repeated across windows and contexts | No duplicate inflation or arbitrary first-occurrence selection; full source and parser provenance remain inspectable. |
| Negative/partial work | Negative source, malformed wording, wholly filtered source and interruption | Negative and failed sources stay visible; unsupported proposals and unknown costs remain auditable. |

Each pack must contain its task brief, source/permission manifest, configuration,
rubric, frozen specification, raw replies, normalized runs, audit, reversible
review history, snapshot and recomputable report. Log configuration changes and
any required package-code edits. A case requiring bespoke code is disclosed as
wrapper engineering, rather than called configuration-only support.

Acceptance concerns operational correctness: every exact retained observation
traces to its frozen text; no unsupported proposal is silently repaired; immutable
versions survive live edits; saved metrics and artifact identities reproduce.
Archive case failures and unsupported requirements. Real quality is evaluated later.

## 2. Validate actual boundaries and independent reproduction

Before live inference, review the optional import trees and execute the pinned
LangExtract/DELM implementations with fake transports under the reviewed
credential-free OS isolation. Current API-shaped tests do not satisfy this gate.

Check native versus wrapped results for supported paths: Unicode and repetition,
multi-pass/chunk inference, fuzzy mismatch, overlap priority, schema cleaning,
relevance filtering, entirely filtered sources, retries and interrupted parsing.
Every internal dispatch must appear in the meter; exhausted envelopes must stop
new attempts; unavailable usage/cost must remain unavailable. Record package hashes,
wrapper changes, omitted SDK modes and native orchestration differences.

Ask an independently authorized operator to install the wheel in a clean supported
environment using only the released instructions. Give them case packs and
expected invariants, not a transcript of author commands. They prepare/freeze,
run offline, recover, add a missing item, reverse a judgment, export and recompute.
Record installation failures, help requests, documentation defects and interventions.
Publish permissible synthetic reproduction artifacts; keep collected data private.
Fix failures and repeat affected tasks. Distinguish independent completion from an
author-assisted demonstration. Current local installation checks are not independent
operator reproduction, nor verification of every advertised platform.

## 3. Conduct a formative researcher evaluation (H4)

After separate participant authorization and applicable procedures, use roughly
4–6 consenting researchers with varying relevant experience. This estimates
workflow breakdowns and feasibility; it cannot establish population superiority.

Compare Quarry's controlled workflow with an appropriate direct CLI/Python
workflow. Both receive the same existing agent/harness/model, task information,
training and assistance allowance. The direct condition may use existing skills
and templates. Do not compare agent-assisted Quarry with an artificially unaided
competitor. Document preparation/wrapper effort for both conditions.

Each participant receives matched but disjoint unseen task families; counterbalance
condition order. Provide synthetic sources and fake inference to isolate workflow
from model quality and cost. Give equal finite task caps, chosen after an author
dry run and frozen before participant sessions. Observe the following tasks:

| Task | Objective completion criterion |
| --- | --- |
| Prepare a study | Valid question, inclusion rule, family split, primary contrast and finite resource limits; unresolved assumptions explicitly recorded. |
| Freeze and collect | Correct source/configuration hashes and traceable fake run; no scope expansion from source/model text. |
| Inspect and correct | Identify an unsupported meaning; add an omission from full text; reverse an exclusion without deleting original evidence. |
| Recover interrupted work | Resume the declared work and explain remaining uncertainty without expanding caps. |
| Reproduce and explain | Recompute the frozen report; correctly explain occurrence versus meaning, candidate review versus complete-source recall, and uncertain dispatch versus free/exactly-once billing. |

Record completion, active time/pauses, interventions, agent correction loops,
help usage and human-coded comprehension using `ResearcherLog`. Keep a coordinator
answer rubric outside participant agents' context. Record harness/model changes
and missing timing rather than inventing values. Report individual outcomes and
recurring failure categories, plus workflow revisions and their follow-up checks.
Satisfaction comments supplement these observations; they do not replace them.

## 4. Run one scientific case study (H1)

Start with community expressions and contextual senses in one clearly defined
language/community. Use the other domains as workflow demonstrations initially.
Develop the rubric and baseline on approximately 9–12 complete development
sources, then propose a distinct pilot of 20–30 independent source families.
These are feasibility ranges, not power calculations; include negative sources,
ambiguous senses, repeated expressions and long documents. Group translations,
threads and reposts before splitting. Freeze held-out families before tuning.

Use qualified independent complete-source annotation with no model candidates.
Retain original independent spans/judgments and assess disagreement before
adjudication. A separate adjudicator resolves conflicts, preserving uncertainty.
Keep gold with a custodian outside the planning/extraction workspace; predictions
must lock before scoring receives it. Ordinary annotator agreement is a diagnostic,
not a gate for deleting model discoveries.

Start with five cold arms: **A**, **B**, **A+A**, **B+B**, and **A+B**. Select the
general extractor and repeat strategy on development families only. Freeze one
primary mixed-versus-development-selected-repeat contrast; the other arms diagnose
whether gains arise from a stronger model rather than complementarity. Specialists,
their additional-general control, native baseline workflows and warm extensions
come later or in separately specified secondary studies.

Repeated general extraction needs a credible strategy: develop general-pass prompt
variation or controlled stochastic decoding, then apply the declared pass-specific
prompt schedule fairly. The current identical-prompt, temperature-zero prototype
does not establish a strong repeated-general baseline. Recorded seeds are not
executed stochastic seeds. Do not tune a weak baseline to favor mixed extraction.

Match frozen text, examples, eligibility rules, input coverage and pass schedule.
Choose one principal resource comparison prospectively (for example a common
verified spending cap), with finite call/token/time caps as well. Record achieved
attempts, tokens, latency and cost; different model tokenizers/prices mean all
resources may not match simultaneously. Report remaining differences and resource
frontiers. Retain stopped sources and uncertain reservations. Three provisional
repetitions of these five arms would fit the current 20-run contract bound, but
repetition count and decoding control must be justified before freezing.

Report occurrence and eligible source-term detection, source coverage, false
negatives, unsupported proposals, valid additions and precision separately. Use a
family-clustered paired recall contrast, predeclared precision/review-cost constraints,
and interval estimates. Retain negative families in the evaluation frame; undefined
metrics remain null. Account for repetitions without treating repeated outputs from
one family as independent families. A pilot estimates variance/costs for a later
confirmatory study; completing the protocol does not require a positive effect.

For contextual-sense claims, add blinded **suggestion-specific** judgment and a
coordinator-held mapping from each system suggestion to independently adjudicated
canonical gold senses. Different generated meanings attached to one span need
separate judgments. Literal label equality and a shared observation judgment cannot
establish semantic equivalence or per-system correctness. Definition support and
translation quality remain separate outcomes. Human adjudication time collected
here does not itself establish assisted annotation savings.

## 5. Test annotation effort separately (H2)

Compare assisted and unassisted complete-source annotation using the same review
interface, rubric, contextual access and help policy; vary candidate assistance.
Keep the final reference gold independently adjudicated by separate people. Each
annotator sees a family in only one condition; different annotators can evaluate
the same families across conditions. Counterbalance order and model annotator/family
effects. Both conditions can discover omissions, correct spans and record uncertainty.

Capture active time and pauses. Predeclare a scientifically justified quality
noninferiority margin with domain experts, primary quality endpoint, confidence
level, missing-data policy and precision/false-inclusion constraints. Require that
quality gate alongside any time improvement. A nonsignificant quality difference
does not pass it. Use pilot variance to size the later study. Keep eligibility,
sense correctness and unsupported definitions distinct. No margin is chosen here.

## Required implementation gates and ownership

| Before | Owner and remaining work | Required artifact |
| --- | --- | --- |
| Real native boundary tests | Integration engineer: review the imported dependency tree, execute actual pinned libraries with fake transports, compare native/wrapped outputs. | Isolated acceptance report with package hashes, every dispatch and disclosed omissions. |
| Live controlled arms | Operator/engineer: implement enforced live runner; carry decoding/schema/temperature/seed controls into the transport contract or freeze/attest transport settings; capture returned model/checkpoint and finish/truncation metadata. | Reviewed transport and arm schedule with enforceable limits and full accounting. Current prepared Quarry runner is fake-only. |
| Semantic H1 | Annotation lead/analyst: implement suggestion-specific blinded units, canonical sense matching, per-system semantic analysis and unresolved-item sensitivity. | Tested semantic scoring specification. Current `score` is detection-only; current observation-level summaries cannot supply this outcome. |
| Human H2 | Domain lead/statistician: justify the margin, plan assignments and implement the noninferiority/annotator-family analysis. | Prospectively frozen analysis and independently held reference gold. |
| Comparative H3 | Reliability engineer: add stateless redispatch control with the same responses and caps if claiming a comparative advantage. | Full retained/missing-work/redispatch comparison. Current reference/fault suite does not provide that control. |
| Participant tasks | Study coordinator: separate authorization, applicable consent/procedures, qualified role assignment and counterbalanced task packs. | Private role/exposure records, task rubric and versioned measurements. No recruitment/contact is initiated by this plan. |

## Paper artifacts and immediate next steps

The systems paper should contain a workflow figure, task/capability matrix, one
reproducible end-to-end example, native integration report, failure/recovery table,
formative task outcomes and candid unsupported cases. The scientific case study
adds independent annotation procedures, pre-adjudication disagreement, fixed
comparisons, resource/outcome plots and representative successes and failures.
Author statements, unit-test counts and screenshots do not substitute for those
observations. GT performance remains a separate platform evaluation.

Next engineering work is to prepare the six synthetic case packs and close the
native/semantic/decoding gates above. After that, obtain authorization for independent
operator and researcher sessions, then select permitted case-study sources and
freeze a pilot contract with real budgets. This document starts none of those
activities. Model calls, downloads, participants, allocations, external contact,
services and publishing collected data retain their separate authorization boundaries.
