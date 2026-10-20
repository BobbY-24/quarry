# Complete-source evaluation

For paired comparisons, failure denominators, stage costs, and the ordered study
plan, see [the experiment roadmap](EXPERIMENT_ROADMAP.md) and
[the runnable offline comparison](../examples/experiments/README.md).

Human review of extracted candidates can estimate their quality, but cannot
measure missed terms. Freeze a held-out source split before recipe/prompt tuning,
then annotate every complete source in that split. Keep a document family or
conversation thread together if one source would otherwise reveal another.

For an approved agent plan, click **Prepare blind source review** or run
`termfinder --project my-study freeze-corpus` before collection. This creates the
saved corpus version, source-family splits, and blank complete-source packets in
the project's `human-review/VERSION_ID/` directory. Any extraction job already
planned for matching source content blocks this blind preparation. V6 cannot
verify exposure outside the tool. Inspect small-corpus splits: the test set can
be empty. Unknown family IDs default to individual sources; review related pages
before treating that grouping as independent.

```sh
termfinder --project my-study split DATASET_VERSION --out splits.json
termfinder --project my-study export DATASET_VERSION annotation-pack --formats annotation
```

`annotation_sources.jsonl` contains full frozen source text, locations, source
hashes, blank `terms`, and `complete: false`. Annotators read the whole text,
add every in-scope expression and occurrence, and mark `complete: true` only when
the source has been exhaustively reviewed. Empty `terms` is valid for a fully
reviewed negative source. `annotation_candidates.jsonl` is a separate convenient
review file; it cannot substitute for the complete-source labels.

For `idea`, `opinion`, or `sentence` recipes, packets use `records` and `data_type`
instead of `terms`. Each record has `observed_text`, language, and exact
`occurrences` (or flat start/end for a single span). Annotation must define the
unit and inclusion policy independently. Matching uses exact source/span/language;
`source_term` is restricted to lexical term recipes. Generated interpretations are
separate from observed wording; requiring an exact shared interpretation label is
an optional stricter measure, not a semantic equivalence test.

A gold JSONL packet has this shape:

```json
{
  "source_id": "SOURCE_ID_FROM_EXPORT",
  "text_sha256": "EXACT_FROZEN_TEXT_HASH_FROM_EXPORT",
  "complete": true,
  "terms": [
    {
      "expression": "moonstep",
      "language": "en",
      "sense": "optional adjudicated sense label",
      "occurrences": [{"start": 120, "end": 128}]
    }
  ]
}
```

The sample offset above illustrates the schema and is not a real fixture offset.
Use half-open Unicode code-point spans such that
`source_text[start:end] == expression`. UTF-8 bytes and browser UTF-16 indices are
different units. The validator rejects mismatched source hashes, invalid spans,
duplicate source packets, and candidate-only/incomplete annotations.

```sh
termfinder --project my-study evaluate DATASET_VERSION heldout-gold.jsonl \
  --split-manifest splits.json --unit occurrence --out evaluation.json
```

`occurrence` reports exact source/span/language matches. `source_term` reports
NFC-normalized expression/language presence per source. Neither default measures
whether the proposed meaning is correct. `--require-sense` adds exact sense-label
matching and requires every gold term to have a shared human label; unconstrained
paraphrases can lower that score even when semantically equivalent. Use a
separate adjudicated sense rubric when that distinction matters.

Reports include precision, recall, false negatives and their source contexts,
and domain/language breakdowns. Undefined metrics are null with an explicit
reason. Passing a split manifest asserts that annotations cover exactly its test
sources; the program cannot prove annotators were blinded or that a corpus is
representative. Include sampling and annotation procedures in the study report.

`examples/gold_specs.json` manually lists in-scope expressions in the complete
synthetic fixture corpus independently of provider output. The offline demo turns
these labels into exact frozen-source packets and reports missed occurrences.
Those synthetic metrics demonstrate the workflow; they are not research claims
about GLM, DeepSeek, Gemini, or any real community.
