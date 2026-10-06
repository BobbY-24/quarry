# Research rationale

V6 is a term-collection tool for researchers working in Georgia Tech's NLPx lab
with [name removed] and [name removed]. The publications below inform product choices. This
implementation does not claim that the PIs requested these features, reproduce
their datasets, or provide a new validated benchmark. The starter examples and
offline corpus are synthetic.

## Evolving vocabulary

[NEO-BENCH](https://arxiv.org/html/2402.12261v4) studies lexical, morphological,
and semantic neologisms, including existing spellings with new senses. Its
collection combines multiple kinds of sources. These distinctions motivate V6's
neologism recipe, separate sense records, explicit date policy, and preservation
of single-extractor discoveries. V6 does not implement the paper's Google Trends
filtering or infer a word's emergence date. `first_observed_in_corpus` describes this
corpus inventory; it is not a claim about first use anywhere.

## Cultural vocabulary and entities

[Camellia](https://arxiv.org/abs/2510.05291) evaluates entity-centric cultural
biases across Asian languages. The [official dataset repository](https://github.com/example/camellia)
separates entities from masked contexts and pairs them with English translations.
This motivates an entity-inclusive cultural recipe, original-script evidence,
explicit language and community metadata, and translations stored as generated
suggestions. The neologism recipe's entity exclusion is unsuitable for this task.

[CARE](https://arxiv.org/abs/2504.05154) investigates culturally specific questions,
responses, and native human preferences. Its [official repository](https://github.com/example/CARE)
describes question, response, cultural category, associated culture, and human
rating fields. V6 consequently keeps human annotations distinct from model
suggestions and permits project-specific attributes. A term inventory does not
construct CARE-style question/response preference data. The repository uses an
alternate title; the link here uses the supplied arXiv record.

## Scientific and medical vocabulary

[MedReadMe](https://arxiv.org/abs/2405.02144) uses sentence readability ratings and
fine-grained complex-span annotations in medical text. This motivates collecting
established jargon and retaining exact spans and page locations. A technical
term need not be a recent coinage. V6's `reader_difficulty` attribute is a model
suggestion, not a calibrated readability score or a medical recommendation.

## Structured research and coverage

[Schema-Driven Information Extraction from Heterogeneous Tables](https://arxiv.org/html/2305.14336v5)
uses human-authored schemas to define structured outputs across heterogeneous
tables. It motivates researcher-editable typed attributes. V6 preserves table
text as source structure but leaves full row/column record extraction to a later
extension.

[LLMEvalDB](https://arxiv.org/html/2502.18791v3) demonstrates evolving literature
analysis through structured extraction from research papers. It motivates V6's
incremental source inventory, durable lineage, and immutable dataset snapshots.
Automatic benchmark generation remains an extension.

[Gavel](https://arxiv.org/html/2601.04424v4) evaluates source-based factual coverage
in long-context summarization and reports omission as a substantial issue. The
product inference is to make unfinished coverage explicit and evaluate terms
against human annotation of complete held-out sources. Inspecting only extracted
candidates cannot identify terms that were never proposed. V6 does not implement
Gavel's evaluation agents.

All links were inspected during the build on October 5, 2026. No external dataset
records or model weights were downloaded or executed for the offline handoff.
