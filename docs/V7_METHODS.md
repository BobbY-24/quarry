# V7 research framework and falsifiable protocols

V7 is an implementation and offline engineering milestone. No real extraction,
human timing, usability, or GT performance result is claimed. Terms and contextual
senses are the primary use case. Existing typed spans remain supported where the
shared detection contract applies. Full tables, conversation datasets and automatic
benchmark construction are deferred. Nothing here asserts that NLPx investigators
requested these features or that publication acceptance is assured.

The [evaluation plan informed by Thresh](V7_EVALUATION_PLAN.md) sequences these
questions into representative workflow demonstrations, independent reproduction,
formative researcher tasks and a focused H1 case study followed by H2. It is a
proposed design, not a frozen or authorized real experiment.

## Claim / hypothesis / evidence matrix

| Hypothesis or claim | Primary contrast and outcome | Falsification / rival explanation | Required evidence and present status |
| --- | --- | --- | --- |
| H1 discovery efficiency | Mixed-model union and Specialists versus a development-selected repeated-general arm, at a common call/token/spend/time envelope. Primary: paired family difference in independently adjudicated valid source-term recall; report precision, additional valid discoveries, active review seconds and cost as constraints. | No useful gain, precision below a predeclared floor, or gains explained by extra inference, examples, context windows, model quality or review exposure. | Complete-source held-out gold, metered dispatches and blinded judgments. Synthetic mechanics only today. Union monotonicity is a deterministic property, not a research contribution. |
| H2 human effort | Assisted complete-source annotation versus unassisted complete-source annotation on unseen, disjoint families. Primary: active seconds per family; quality noninferiority is a co-required gate against independent adjudication. | Faster review fails the scientifically justified quality margin, or savings disappear when missing discoveries are allowed, prior exposure is removed or quality is adjudicated. | Independent qualified annotators; declare recall/semantic quality margin and rationale before freezing. A nonsignificant quality difference does not establish noninferiority. No human result today. |
| H3 reliability | Durable Quarry recovery versus an uninterrupted same-logical-response reference and an explicitly stateless redispatch control. Primary: retained exact evidence and repeated dispatches, with incomplete-work assessability. | Missing evidence, concealed uncertainty, nondeterministic faults, or equal recovery effort after resources are controlled. | Request-keyed fault schedules; compare source/expert evidence, missing work, reservations and dispatch ledgers. Synthetic operational observations; no provider-side exactly-once billing guarantee. |
| H4 researcher usability | Existing-agent Quarry workflow versus direct workflow, with the same harness/model or a documented matched assistance policy. Primary: setup completion plus active time; comprehension is co-required. | Benefits explained by experience, task difficulty, order, more help or existing competing-tool agent skills; scope/evidence/billing understanding declines. | About 4–6 consenting researchers for formative findings only. No recruitment or population-level superiority claim today. |
| GT platform evaluation | Approved checkpoint/runtime/hardware configurations at a fixed envelope. Throughput, memory, startup, queue, checkpoint and recovery measurements. | Apparent speed/cost benefits vanish when allocation and startup overheads are counted. | Operator-authorized allocation and accounting. Prepared inert bundle only; not automatically a novel contribution. |

For H1, select the repeated-general prompt/pass strategy only on development
families. Compare single extractors and additional-general controls beside mixed
union and Specialists. A cold-cache primary study must not reuse earlier responses;
a warm-cache extension gets a separately named arm and its cold predecessor digest.
Resource equality needs achieved usage as well as planned limits. If an arm stops
at a limit, retain its incomplete sources rather than adding resources retrospectively.

For H2, quality noninferiority requires a justified margin delta chosen by domain
experts: the lower one-sided confidence bound for assisted-minus-independent
quality must exceed minus delta. Choose confidence level, unit, missing-value
handling and multiplicity policy in the frozen contract. Pilot results estimate
variance and costs; they cannot justify choosing a margin that merely makes a
result pass. Active-time superiority alone cannot establish H2. Carry unscorable
and disputed judgments into sensitivity analyses. Semantic paraphrases require
human judgments; literal sense-label equality is only a label-convention diagnostic.

## Domains and primary sources verified 2026-10-06

The following publications motivate sampling and rubrics, not claims of dataset
reproduction. Baseline READMEs were inspected without running their code or
downloading their models/data. Before a real study, audit licensed source artifacts,
annotation instructions, baseline code paths and exposure to evaluation data.

| Domain | Primary publication and code | Implication for this protocol |
| --- | --- | --- |
| Community vocabulary | [NEO-BENCH, ACL 2024](https://aclanthology.org/2024.acl-long.749/) · [author repository](https://github.com/JonathanQZheng/NEO-BENCH/tree/65239f60e3d44b3d53971ed80b71fa32b71ac6e8) | Covers lexical, morphological and semantic neologisms. Its benchmark evaluates handling of collected neologisms; V7 proposes complete-source extraction evaluation. Preserve multiword expressions and contextual new senses, including singletons. |
| Multilingual culture | [Camellia](https://arxiv.org/abs/2510.05291) · [code/data](https://github.com/tareknaous/camellia/tree/35dddfb8f6ac718ba54ecd4e817a6e3eb95db890) | Entity-centric cultural bias evaluation uses nine Asian languages and translated contexts. Keep related translations in one family; cultural entity inclusion is explicit and domain-dependent. |
| Multilingual culture | [CARE, version 5](https://arxiv.org/abs/2504.05154v5) · [author repository](https://github.com/Guochry/CARE/tree/d614cfe2407ae3c4da8d4f8a58bd50f16bb0e097) | Human cultural preferences motivate native-language qualification and context-sensitive review. CARE is a preference resource, not a term-extraction benchmark. Its paper title and resource counts changed across versions; freeze the referenced version. |
| Scientific/medical jargon | [MedReadMe, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.958/) · [author repository](https://github.com/chaojiang06/medreadme/tree/7c52205d18f16b80e3ffccb4e9da88b1942df310) | Sentence readability and complex/jargon span annotation motivate established-jargon inclusion. The current README suggests remote model code; V7 does not execute it. Domain expertise and intended audience affect eligibility. |

These sources establish relevant prior work; this limited audit does not establish
novelty. A publication proposal needs a broader current literature comparison and
real measurements. LangExtract/DELM primary pins and behavior are documented in
[V7 adapters](V7_ADAPTERS.md).

## Pilot tasks, roles and stop rules

| Phase / role | Concrete task and artifact | Prerequisites / stop rule |
| --- | --- | --- |
| Lead researcher | Write question, hypotheses, primary contrast, useful precision/review-cost tradeoffs, rubric and justified H2 margin. Review every draft field with own agent. | Stop before freezing if a primary margin, unit or inclusion rule is unresolved. Spec data never authorizes spending. |
| Corpus custodian | Prepare roughly 9–12 complete development sources per domain; include negatives, long texts, repeated expressions, ambiguous senses, relevant languages and formats. Record source/raw/parsed hashes, access constraints, grouping and parsing failures. | Permission for sources; no sharing of collected text. Keep translations, reposts and threads together. |
| Custodian + lead | Propose a distinct pilot of roughly 20–30 independent families per domain, freeze held-out families before tuning. | Ranges are provisional feasibility targets, not power calculations or quotas. Do not fill quotas with correlated documents. |
| Annotation coordinator | Store gold outside planning/extraction workspace. Assign independent complete sources to qualified annotators who have not seen candidates. Archive versioned adjudication. | Independence, language/domain competence and rubric calibration. Stop when systematic disagreement makes the rubric unusable; amend prospectively. |
| Operator / existing agent | Run approved frozen arms on identical parsed text using finite envelopes, isolated caches and randomized recorded ordering. Lock predictions before gold enters scoring. | Separate authorization for paid calls/downloads/GT. Stop at any resource cap, deadline, cancellation or predefined safety/access criterion. Retain uncertain reservations. |
| Analyst | Report occurrence and source-term detection, semantic axes, false negatives, domains/languages, failures, coverage and costs. Paired family uncertainty and sensitivity to unresolved judgments. | Predictions locked; external adjudicated gold. Null metrics retain reasons. No source exclusions chosen after observing results. |
| Lead + statistician | Use pilot variance, family dependence and annotation costs to justify the next study size and analysis. | No fixed-range power claim. Freeze a new contract/amendment before new data. |
| Usability coordinator | Approximately 4–6 consenting researchers; counterbalance order across disjoint unseen tasks, keep harness/model/help policies constant and measure experience and comprehension. | Separate recruitment/participant authorization and applicable institutional procedures. Stop on withdrawal, inability to consent or unresolved privacy/access constraints. Formative scope only. |
| GT operator | Supply institutional scheduler/site configuration, approved runtime/checkpoint hashes, quantization and hardware. Import allocation accounting. | Separate allocation/download authorization. Stop at finite hours, memory, call, token, spending and deadline caps. No guessed partitions/accounts. |

## Analysis and contamination boundaries

The existing complete-source comparison includes every frozen source, including
failed, partial, pending, excluded and uncertain rows. Detection on frozen parsed
text must be labeled separately from acquisition/parsing quality: archive originals
where permitted and report retrieval/parse failures against the acquisition frame.
A parsed-text experiment cannot infer end-to-end recall for text never obtained.

Candidate review estimates precision/semantic quality but cannot estimate omissions.
Assisted review includes full text and discovery of missing items. Independent gold
uses complete-source annotation without candidates. Gold export, independent human
roles and actual prior exposure are procedural claims, not established by a local
hash chain. File validation proves internal consistency, not an authenticated
preregistration or that a reviewer followed instructions.

No agreement, frequency or candidate-count gate may remove exact grounded evidence.
No model judging stage deletes the union. Human exclusions form reversible views;
relations and original evidence remain archived. Free-text suggestions do not execute
code or change configuration. Configured provider identifiers and recorded rates are
historical declarations; validate current routing/rates before an authorized run.
