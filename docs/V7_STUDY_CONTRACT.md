# V7 study contract and prediction lock

V7 adds a validated study contract above the existing offline comparator. A
specification describes a proposed experiment. Reading, freezing, or amending
it never calls a provider, imports adapter code, allocates compute, or grants
authorization. Resource limits are declarations for downstream runners; this
repository API does not execute a study or attest that an external arm obeyed
its declared envelope.

`termfinder.studies.validate_study(spec, corpus=None)` checks a complete
`schema_version: "7.0"` specification and returns a defensive copy. Supplying
the frozen corpus also verifies its complete identity and hashes. The corpus
uses the existing experiment schema: each source contains its complete frozen
Unicode text, `text_sha256`, domain, language, and `family_id`.

| Field | Required content |
| --- | --- |
| `study_id`, `research_question`, `hypothesis`, `contribution` | Explicit research statements; feature counts and union monotonicity alone do not establish a contribution |
| `primary_contrast` | `left`, `right` arm IDs; `direction`; nonempty `rival_explanations` |
| `primary_outcome` | `metric`, `unit`, `analysis`, `quality_margin`, `unavailable_reason`; null margins need a reason |
| `secondary_analyses` | Predeclared bounded text analyses, including separate semantic, cost, coverage, domain and language results where applicable |
| `policy` | `inclusion`, `exclusion`, four-axis `annotation_rubric` |
| `corpus` | `corpus_id`, canonical `corpus_sha256`, complete `sources` manifest, `scope`, `acquisition_provenance` |
| Each manifest source | `source_id`, `text_sha256`, `family_id`, `split` (`development`, `calibration`, or `heldout`) |
| `gold` | `version_id`, canonical `sha256` or null with a reason, human `provenance`, `unavailable_reasons` |
| Each `arms` entry | `arm_id`, `system`, `track`, inert `configuration`, exact `provenance` |
| `repetitions`, `seeds`, `run_order` | Every arm/repetition exactly once; distinct repetition seeds; ordered rows containing `run_id`, `arm_id`, zero-based `repetition`, `seed` |
| `cache` | `regime`, `isolation`, `extension_of`, `unavailable_reason` |
| `limits` | Finite nonnegative caps for `calls`, `input_tokens`, `output_tokens`, `seconds`, `spending_usd`, `allocation_hours` |
| `stopping_rules`, `planned_exclusions` | Nonempty stop rules; exclusions each with a predeclared `rule` and `reason` |
| `unavailable_reasons` | Explicit reasons for other unavailable planned measurements or assumptions |

The arm provenance fields are `software_revision`, `model_version`,
`prompt_sha256`, `configuration_sha256`, `adapter_version`, and
`unavailable_reasons`. Every null needs a named reason. A moving model alias is
not an independently verified model revision. Matched, native, ablation and warm
extension tracks are distinct declarations; the validator cannot prove their
scientific fairness.

Corpus hashes use SHA-256 of Quarry's canonical JSON representation; text hashes
use SHA-256 of UTF-8 bytes. Freeze verifies every declared source, including
negative sources, against the complete corpus. Related families cannot cross
splits. Identical text hashes cannot cross splits even if mislabeled as unrelated
families. Humans must still identify translations, reposts and related threads.
Freeze held-out families before choosing prompts, examples, policies or models.

The bounded comparator accepts at most twenty normalized runs, so the study
validator requires `arms × repetitions <= 20`. Larger designs need explicitly
predeclared study blocks and a separate aggregation procedure. This limit is
engineering support, not a sample-size recommendation. Repeated arm runs remain
separately identified; pairwise detection output does not itself aggregate
repetitions or establish an inferential model.

`primary_contrast_results` selects the frozen primary arms within each
repetition and applies the predeclared contrast direction independently of
randomized run order. Precision, recall and F1 outcomes receive detection deltas
and available paired-family intervals. Other outcomes remain null with an
explicit requirement for their separate predeclared analysis. All-pairs output
remains available for secondary/exploratory reporting; it does not replace the
primary contrast or supply an aggregation model across repetitions.

Cold cache declarations require an explicit null extension reference with a
reason. Warm extensions must use a separately frozen study, identify the prior
cold prediction-lock hash, and label every arm `warm_extension`. The API records
the cache isolation plan; a downstream runner must create the actual isolated
caches and fresh databases. Cache declarations do not attest to cache contents.

## Immutable study revisions

```python
from termfinder.studies import StudyRepository

repository = StudyRepository("planning/study")
repository.create(spec, actor="researcher")             # draft
repository.freeze(actor="researcher", corpus=corpus)   # frozen
repository.lock_predictions(corpus, saved_runs, actor="researcher")

report = repository.score(
    corpus, saved_runs, "/external-gold/gold-v1/gold.json",
    workspace_root="planning", bootstrap_samples=1000, seed="predeclared-seed",
)
```

This code performs local data operations only. `saved_runs` must follow the
predeclared run order, have the arm's exact declared provenance, and retain an
outcome for every source. Partial, failed, pending, uncertain and excluded
outcomes require reasons. Invalid proposals are preserved and audited by the
existing comparator; the lock does not repair or delete them.

`freeze` requires the full corpus. A draft or amended revision cannot be locked
or scored. `amend(new_spec, reason=..., actor=...)` creates a new amended revision;
it preserves the study identity and all previous revisions. Freeze that revision
before another run. Earlier prediction locks remain bound to their earlier
frozen revision. The amended revision requires its own prediction lock and
cannot reuse a previous lock silently.

Revisions are exclusively created files in `revisions/`, with hashes linking
each version to its predecessor. Locks are exclusively created files in `locks/`
and cover the frozen revision, full corpus, complete saved runs and run order.
The API cannot replace an existing version. History replay detects ordinary
file tampering and missing/changed sequence links. A person with filesystem
write access can rewrite and rehash a whole chain; use independent custody or a
committed frozen artifact for stronger assurance.

## External gold and scoring

`score` verifies the immutable prediction lock before opening the gold file. Gold
must resolve outside the declared planning/extraction workspace, including
through symlinks; the study repository must be inside that workspace. A gold
file inside the workspace is rejected. This ordering and path check do not prove
that a human has never seen gold. Use coordinator-managed access and an
independent annotation protocol.

The external gold file must contain complete-source packets for every held-out
source exactly once, including exhaustive negative-source annotations. The
entire corpus remains locked, while confirmatory detection uses held-out families.
Keep development analyses separate and explicitly exploratory. If gold contains
a development corpus as well, prepare a separately versioned held-out gold
export for confirmatory scoring; do not modify earlier gold artifacts.

Gold hashes, when known before freeze, refer to canonical JSON content. When the
hash is initially unavailable, the frozen spec must say why; the report records
the exact received gold content hash and file hash. The predeclared gold version
and provenance are operator declarations unless accompanied by independently
held export metadata. `score` reads an adjacent `manifest.json` when present,
or an explicitly supplied `gold_manifest_path`. Its version must match the frozen
declaration, its content hash must match the received gold, and its provenance
must be explicit. A mismatch blocks scoring. With bare fixture labels and no
manifest, `declared_gold_version` records the declaration while actual
`gold_version` and actual provenance remain null with unavailable reasons;
`gold_version_status` marks them `declared_unattested`. A matching manifest is
content/version binding, not a signature or proof of custodial independence.
No scorer can infer qualification or gold exhaustiveness from the labels alone.

The existing comparator preserves failed-source gold positives in recall
denominators and reports null metrics with reasons. The V7 scoring path always
sets `require_sense=False`: literal free-text label equality cannot establish
semantic equivalence. Occurrence and source-term detection are distinct outcomes;
semantic, active-time, recovery and usability outcomes require their own
predeclared analysis. A detection report generated for those studies is an
ancillary artifact, not their primary analysis.

`scope: frozen_parsed_text` evaluates extraction on identical frozen text. A
claim about acquisition/parsing requires `scope: end_to_end` with explicit
acquisition provenance and its separately measured outcomes, including parse
failures. Changing that field cannot manufacture end-to-end measurements.

For H2, investigators must choose and scientifically justify a quality margin
before an empirical freeze, declare an appropriate noninferiority analysis, and
use independent adjudication. An arbitrary nullable field or failure to find a
significant quality difference does not establish noninferiority. The schema
supports an explicitly inapplicable margin for studies such as detection or
usability; it does not select a scientific margin automatically.

## Offline evidence

The focused tests use hand-computable synthetic sources and saved runs. They
exercise all-resource cap validation, full-corpus hash/family integrity,
draft/frozen/amended history, prediction lock identity, external-gold custody,
held-out selection, and failed-source denominators. They do not measure real
extraction quality or verify empirical blinding, gold qualification, resource
matching, novelty, power or provider invoices.
