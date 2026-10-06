# Extraction adapters and Quarry ablations

V7 implements optional, pinned LangExtract and DELM boundaries plus an offline
Quarry ablation runner. Core Quarry imports neither baseline. A configuration is
data: it cannot construct a provider, select a Python module, authorize paid
calls, execute returned tool requests or change the study policy.

The direct distributions are `langextract==1.7.0` and `delm==0.1.4`. Their wheel
hashes, reviewed source hashes and API observations are in
[the source manifest](../examples/v7/adapters/source_manifest.json). The pins were
verified by downloading primary PyPI metadata and wheels for static inspection
on October 6, 2026. DELM's pinned wheel contains an internal `__version__` of
`0.1.3`; the adapter checks its distribution metadata version, `0.1.4`.
The current website quick-start constructor differs from this older wheel, so
the integration follows the pinned source.

[requirements-adapters-lock.txt](../requirements-adapters-lock.txt) pins the
complete resolved 81-wheel graph with SHA-256 hashes for **CPython 3.12 on macOS
arm64**. [The dependency manifest](../examples/v7/adapters/dependency_lock_manifest.json)
retains each wheel's version, hash and dependency metadata. The reviewed
[metadata resolver](../tools/resolve_adapter_metadata.py) downloaded wheels under
an empty credential environment, filesystem isolation and finite bounds; no
foreign wheel code was installed or executed. Other Python versions and Linux
require a separately reviewed platform resolution. A metadata lock is not a
source-code security review or evidence that native integrations executed.

## Two explicit tracks

| Track | Shared contract | Permitted differences to record |
|---|---|---|
| Matched components | Frozen parsed text and source hashes; inclusion policy; examples; model/checkpoint declaration; finite resource ceilings; exact common scoring | Tool-specific prompt templates, chunking and schema representation remain visible. Fuzzy/partial alignment and relevance filtering are disabled. Matching a model name does not equalize provider decoding. |
| Native workflow | Same frozen corpus and complete-source gold; declared documented native settings | LangExtract chunking, multiple passes, fuzzy/partial alignment and overlap-priority merge; DELM paragraph splitting, keyword scoring, filtering, schema cleaning and outer retries. Wrapper substitutions and unavailable native capabilities are disclosed. |

Neither track proves semantic correctness through exact occurrence. Interpretations
remain model proposals; independent complete-source human annotation supplies gold.
Agreement, frequency and candidate counts do not decide whether grounded discoveries
survive Quarry's union.

## Boundary and retained artifacts

```python
from termfinder.adapters import adapter_config, RecordedBackend, run_adapter

config = adapter_config("langextract", track="matched")
packet = run_adapter(corpus, config, RecordedBackend(fixtures_by_source),
                     run_id="langextract-matched", software_revision="reviewed-sha")
normalized_run = packet["run"]
audit = packet["audit"]
```

`run_adapter` accepts an explicitly supplied backend object. The normalized run
uses the existing `experiments.py` contract and scorer. The companion audit stores
the complete configuration, actual dispatch attempts and original replies,
pre-filter proposals, native alignment/filter/merge decisions, adapter transformations,
all source outcomes, usage, uncertain attempts and missing-cost reasons. Failed,
partial, pending and entirely filtered sources remain explicit source rows.

Every parsed proposal is represented in the normalized raw population. A proposal
discarded by a native filter or merge retains its wording and receives unavailable
offsets, so the scorer excludes it and the audit states its native disposition.
Consequently the proposal audit rate measures both source support and native
filter/merge dispositions; it is not semantic precision. Malformed native proposals
remain unscorable audit items, and malformed source-output shapes become explicit
failed-source rows. Malformed raw replies remain dispatch artifacts even when no
proposal can be parsed.

`RecordedBackend` replays inert library-shaped fixtures. These are deliberately
synthetic and do not claim to be recordings from real model requests or to execute
the third-party algorithms. `LangExtractBackend(transport)` and
`DELMBackend(transport)` contain the actual lazy-imported pinned library hooks.
Replacing a backend requires reviewed code, not a path supplied by model output.

## Alignment rules declared before scoring

Offsets count Unicode codepoints in the frozen parsed text. Generated wording is
never replaced with a source substring.

* LangExtract positions remain native. Accept only a native interval whose exact
  original source substring equals the original generated wording. Native fuzzy,
  partial, token-level case-insensitive or punctuation-normalized alignments that
  do not satisfy that check remain auditable unscorable proposals.
* DELM does not supply native character positions. Explicit model chunk offsets
  are labeled `adapter_verified_model_chunk_offsets` and verified exactly. Wrong
  offsets remain unavailable; they are not repaired by searching elsewhere.
* Without DELM offsets, derive an occurrence only when the exact wording appears
  once within an unambiguously mapped chunk. Repeated terms or repeated stripped
  paragraphs remain ambiguous. No first-occurrence choice or source-text rewrite
  is permitted.

These policies differ from Quarry's existing exact-context grounding, which can
retain every exact occurrence within repeated contexts. Predeclare this difference
and report occurrence and source-term detection separately. To compare occurrence
recall, instruct every arm to enumerate repetitions and use explicit positions
where its contract supports them. Do not interpret alignment-policy differences
as a model-quality result.

## Native library audit and wrapper engineering

The pinned LangExtract [annotation source](https://github.com/google/langextract/blob/70cfb988cc25f15d8b04a1e57bd52a777207c0c6/langextract/annotation.py)
merges sequential passes with earlier-pass overlap priority. V7 observes parsed
and aligned objects before that merge and compares them with final emitted object
identities. The audit distinguishes retained objects from overlap-discarded or
interrupted-workflow objects. Pass start/completion and each inference prompt
carry a pass index. [LangExtract 1.7.0](https://pypi.org/project/langextract/1.7.0/)
uses DP exact alignment and LCS fuzzy alignment by default; legacy difflib behavior
must not be assumed from older documentation. Native positions do not themselves
establish exact substring support or semantic validity.

The [DELM paper](https://arxiv.org/abs/2509.20617) describes configurable extraction
pipelines and cost/coverage trade-offs. The pinned
[DELM package](https://pypi.org/project/delm/0.1.4/) uses `ExtractionManager`, an
outer `RetryHandler`, and Instructor calls with `max_retries=0`. V7 invokes its
schema generation, chunk extraction, outer retries, paragraph splitter, keyword
scorer and `NestedSchema` cleaning. Each original item and cleaned item are
retained. Cleaning can discard required null/missing fields, disallowed values or
case-insensitive `validate_in_text` failures. A source whose entire relevance
population was filtered still contributes all its gold positives to recall.

The DELM wrapper applies a validated numeric score threshold instead of accepting
arbitrary `DataFrame.query` expressions. It bypasses the automatic provider
factory, dotenv loading, global price lookup and native disk orchestration.
Its injected client validates raw JSON using the native Pydantic schema, rather
than reproducing Instructor's provider-specific structured-decoding modes.
LangExtract similarly uses a custom `BaseLanguageModel`, rather than a native
cloud SDK. These engineering differences belong in native-workflow reports.

## Actual dispatch accounting and limits

A supplied transport must declare `single_attempt=True` and `honors_limits=True`.
Its `dispatch(request)` receives the exact library prompt, source identity,
logical request, model/checkpoint declaration, per-call input/output limits,
remaining timeout and spending reservation. It returns raw text, reported token
usage and cost measurement/basis or explicit unavailable reasons. It must not
perform hidden SDK retries. Exception messages are never copied because they can
contain credentials; safe error types remain auditable.

The meter reserves calls, input/output tokens, time and money before every actual
attempt, including DELM outer retries and LangExtract chunk/pass calls. Unknown
usage retains the full token reservation; unknown costs retain the full monetary
reservation and remain `null`, never a measured zero. Known subtotals remain
visible alongside unavailable totals. Simulation, token estimates and invoices
must be separate runs. A discovered per-call transport overrun terminally stops
further attempts and retains the returned reply.

The prompt admission byte bound is conservative for ordinary byte/subword
tokenizers; validate the exact checkpoint tokenizer before a live study. Declared
transport flags are not external attestation. Enforce request/output limits in a
reviewed transport and bound synchronous calls with OS/process supervision.
This adapter task ran no model calls. Live model executions need separate user
authorization, dependency/code review, only the authorized service credential,
and an appropriately isolated runtime.
The current injected reply envelope does not attest returned model identifiers,
checkpoint checksums or provider finish/truncation reasons. Its model version is
the operator's declaration. Capture and verify that metadata in a reviewed live
transport before making checkpoint-controlled or truncation claims.

## Quarry arms with actual Engine execution

```python
from termfinder.ablations import prepare_quarry_ablations, run_prepared_quarry_ablations

plan = prepare_quarry_ablations(corpus, frozen_master_documents, output_directory,
                               recipe=recipe, profile="fake", passes=3)
# Review/freeze plan and the real normalized_pre_run provenance before extraction.
results = run_prepared_quarry_ablations(corpus, plan, expectations=fixture_labels)
```

`prepare_quarry_ablations` creates separate fresh cold Projects and source-only
snapshots without dispatch. Every imported source must preserve its frozen text,
hash, parser provenance and source ID. Preparation returns a hash-checked plan
and real configuration/prompt provenance. Running rejects a changed plan or saved
Project configuration. The convenience `run_quarry_ablations` combines these
steps for an offline mechanics demonstration.

The manifest includes every single extractor, development-selected repeated
general extraction, broad mixed-model union, general plus specialist lenses,
additional-general controls with matching pass counts for specialists and mixed
union, and a separately labeled warm extension. Repeated schedules use distinct
expert IDs; the actual existing Quarry Project/Engine controls collection and
keeps the union. Synthetic expectation restrictions map original extractor/lens
IDs to the scheduled expert IDs, preserving single-model discoveries.

Cold arms have independent databases/caches and equal declared arm ceilings.
Metering occurs at every actual `FakeProvider.complete` call under the real
Engine. Both active extraction and specialist stages may use the common total
spending ceiling; the Engine's shared budget prevents double expenditure.
Realized resource equality is an observed accounting result, not a property of
equal ceilings. The prototype is fake-provider-only; it is not a paid runner.
Schedule seeds are recorded, but current Quarry fake/HTTP decoding does not
implement stochastic seed control. Controlled stochastic repetitions remain a
prerequisite for real inference studies.

Warm extension begins only after a cold parent's immutable snapshot. It reuses
the parent Project and appends general work. Its separately labeled normalized
view uses current-configuration completion with inherited evidence and cumulative
parent-plus-extension costs; the original full run history and snapshot remain
in the audit. Incremental dispatches are reported separately. This view never
enters an equal-resource cold contrast by implication.

`make_ablation_manifest`, `union_runs`, and `execute_ablations` also support an
explicit integration runner. Generic runners own aggregate budget enforcement,
cache creation and realized resource attestation; manifest declarations alone
do not enforce those actions. Union deduplicates exact observations, preserves
all contributor IDs and retains unsupported proposals in its audit.

## Verification and remaining work

The offline tests exercise malformed replies/proposals, fuzzy mismatch,
overlap-discarded proposals, ambiguous repeats, incorrect offsets, all-filtered
denominators, uncertain calls, null accounting, terminal transport overruns,
configuration integrity, unique single-extractor discoveries and actual Quarry
warm extension. Verification uses the reviewed empty-environment macOS Seatbelt
runner, with network denial and unrelated-file-read probes plus finite bounds.

API-shaped fake modules also exercise the actual `LangExtractBackend` and
`DELMBackend` wrapper methods: native-shaped inference, pass/parse/alignment
hooks, overlap disposition, schema cleaning, relevance filtering and outer
retry dispatches. These validate wrapper plumbing against the statically reviewed
API shapes; they do not execute or certify the third-party implementations.

Optional pinned library import trees and provider SDK dependencies have not been
fully reviewed or executed. Direct wheel provenance and static API inspection
are verified; synthetic shaped replay does not validate third-party algorithm
behavior. The metadata lock pins the resolved Python 3.12/macOS arm64
wheel graph but does not certify its code or other platforms. Before publication,
review that imported dependency graph, perform isolated pinned-library boundary
smoke tests with fake transports, then authorize and measure actual model runs.
Neither wrapper establishes extraction quality, usability, novelty, allocation
performance or provider-side exactly-once billing.
