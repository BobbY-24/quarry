# Offline experiment comparison

Start here to rehearse the first experiment: score partial Broad, completed Broad,
and Specialists runs on the same frozen synthetic sources and complete-source
gold for each of the three starters. The demo
uses fake providers, creates fresh local projects, and needs no API key, model
server, network fetch, or Georgia Tech allocation. It demonstrates input/output
contracts and evaluation mechanics, not the four research hypotheses.
See [observed verification and limits](../../docs/development/reproduce.md).

For the ordered implementation plan and a real study procedure, see
[the experiment roadmap](../../docs/research/experiment-plan.md). LangExtract and DELM
adapters, semantic review-time experiments, student studies, and live compute
measurements are planned work; this directory does not run those systems.

## Run the smoke example

From the repository root, with Quarry installed in your Python environment:

```sh
python examples/experiments/offline_demo.py --out outputs/experiment-smoke
termfinder compare-experiments outputs/experiment-smoke/neologisms/study.json \
  --out outputs/experiment-smoke/neologisms/rechecked-report.json
```

Choose a new output directory for each demo run. The demo refuses to overwrite
an existing output directory. The comparison command only reads saved study
inputs and writes its report; it does not call extraction providers.

The top-level `report.json` is the engineering smoke summary. Each of
`neologisms/`, `cultural/`, and `jargon/` contains:

| File | Purpose |
| --- | --- |
| `corpus.json` | Frozen source text, hashes, domain/language, and family identifiers |
| `gold.jsonl` | Complete synthetic source annotations, independent of provider output |
| `quarry-broad-partial.json` | Saved interrupted/unfinished Broad inventory for assessing coverage and missed gold |
| `quarry-broad.json` | Normalized saved Broad run, provenance, source statuses, predictions, and stage costs |
| `quarry-specialists.json` | Normalized saved Specialists run on the same source fixtures |
| `study.json` | Relative input paths, matching unit, and analysis settings |
| `report.json` | Initial common comparison report for that cell |
| `rechecked-report.json` | Neologism report reproduced by the second command without model calls; use the other cell paths to re-score them |

Fresh project directories also preserve the underlying offline Quarry runs.
Sources are parsed once and reused as frozen text with shared identifiers within
each cell; the gold comes from independent fixture label specifications before
extraction. There are six completed arm runs and three partial run snapshots.
The simulated provider replies and labels are deliberately small. A high score,
cost difference, unique recovery, or bootstrap interval on them is not evidence
of real-model performance, power, or representativeness.

## Read the report

Each `runs[]` entry reports detection, per-source results, domain/language
breakdowns, coverage, raw-proposal validation, and costs. Read these together:

- `detection` scores exact grounded observations against the complete gold.
  Candidate counts and model agreement are not recall measurements.
- `raw_proposals` retains invalid submitted proposals in `invalid_queue` and distinguishes
  submitted, exactly grounded, invalid, and duplicate grounded observations.
  Malformed optional interpretations remain in `attribute_issue_queue`; the
  exact observation survives with a null interpretation. `accepted_predictions`
  distinguishes scoreable observations from text-supported proposals lacking
  other required fields, such as a language.
  Exact grounding is a text check, not verification of a proposed meaning. When
  a run declares `proposal_population: "grounded_inventory"`, the raw grounding
  rate is null with reason `raw_proposals_not_supplied`. Quarry's snapshot bridge
  uses that declaration; its accepted inventory cannot prove a 100% grounding
  rate for all original model proposals. Inspect its engine audit separately.
- `coverage` reports all source statuses and complete fraction. Failed, pending,
  partial, uncertain, and excluded sources stay in the gold denominator; their
  unrecovered positives are false negatives. A partial source can retain valid
  discoveries. A processing `complete` flag does not prove semantic completeness.
- Costs distinguish known subtotals, unavailable amounts, uncertain reservations,
  and their bases. Simulated costs are not bills. A zero known service rate does
  not include unmeasured human labor or local/cluster infrastructure costs.
- Pair comparisons report detection differences and unique gold recoveries.
  Optional uncertainty resamples source families, not individual occurrence rows.

Review the original source and proposal before interpreting a surprising result.
Complete-source annotations can measure omissions; reviewing candidates alone
cannot. Use a separate adjudicated rubric for meanings and inclusion decisions.

## Study file

The smoke writes a runnable file with this shape:

```json
{
  "schema_version": "1",
  "corpus": "corpus.json",
  "gold": "gold.jsonl",
  "runs": [
    "quarry-broad-partial.json",
    "quarry-broad.json",
    "quarry-specialists.json"
  ],
  "unit": "occurrence",
  "require_sense": false,
  "bootstrap_samples": 0,
  "seed": "quarry-study-v1"
}
```

Input paths are relative to and confined to the study directory. Keep a study
self-contained; do not use external paths or symlinks to bypass that boundary.
Preserve submitted inputs rather than editing an earlier study to obtain a
preferred result. Store a new version when policy, gold, or run files change.

For a later real study, freeze the seed and analysis before looking at test
outcomes. A positive `bootstrap_samples` requests a deterministic paired
percentile bootstrap of micro precision/recall/F1 differences over whole source
families. Reports disclose effective replicates and null-interval reasons; fewer
than two families or undefined metrics can prevent an interval. More bootstrap
samples do not make a tiny or biased corpus a powered experiment.
The implementation caps aggregate work at five million paired family draws;
compare fewer arm pairs separately if a larger study exceeds that bound.

## Normalized adapter contract

This is an interchange contract for **saved results**. An external adapter is
responsible for running its chosen tool only under separate authorization,
retaining raw outputs and decisions, then exporting these inputs. The common
comparison command never dispatches tools or expands discovery scope.

| Input | Required information |
| --- | --- |
| Corpus | `schema_version: "1"`, `corpus_id`, `data_type`, and `sources[]` |
| Each source | `source_id`, complete `text`, `text_sha256`, `domain`, `language`, and `family_id` |
| Gold | Existing complete-source Quarry JSONL packets with source IDs/hashes and `complete: true`; use `terms` for lexical studies or typed `records` for other units |
| Run | `schema_version: "1"`, `run_id`, `system`, `data_type`, `proposal_population`, `provenance`, `source_results[]`, `predictions[]`, and `costs[]` |
| Proposal population | `raw_proposals` for all submitted model proposals, or `grounded_inventory` when only accepted evidence is supplied; raw grounding quality is unavailable for an inventory-only run |
| Provenance | `software_revision`, `model_version`, `prompt_sha256`, `configuration_sha256`, `adapter_version`, and `unavailable_reasons`; unknown values need a declared reason |
| Source result | One row for every corpus source: `source_id`, `text_sha256`, `status`, and `reason` |
| Submitted prediction | `prediction_id`, `source_id`, `observed_text`, `language`, `start`, `end`, and `interpretation` |
| Cost row | `stage`, `known_usd`, `uncertain_reserved_usd`, `basis`, and `missing_reason` |

Statuses are `complete`, `partial`, `failed`, `pending`, `uncertain`, or
`excluded`. Complete results use a null reason; every other status needs an
explanation. Do not omit a source because a native filter dropped it or a call
failed. Save paragraph/filter decisions and native alignment statuses in the
adapter's raw audit archive as well.

Observed text is original source wording. Half-open offsets use Unicode code
points, so `source.text[start:end] == prediction.observed_text`. Generated
interpretations can be strings or null and never replace the observed evidence.
Do not repair a mismatch by inventing source text. Preserve the submitted
proposal for audit and let the common grounding check expose it. Source hashes,
schema errors, and conflicting source inventories require correction of the
input contract, not selective deletion of inconvenient sources.

Every run has a row for `discovery`, `parsing`, `extraction`, `specialist`, and
`translation`. A knowingly unused stage has explicit zero cost; unavailable
amounts use null plus `missing_reason`. Bases are `simulated`, `token_estimate`,
`provider_invoice`, or `not_metered`. Keep uncertain reservations separate from
known charges. Add separately measured external-agent/search, reviewer labor,
and compute allocation rows or preserve their raw records in the study archive.
The snapshot bridge adds unavailable `external_planning`, `human_review`, and
`infrastructure` rows for non-simulated studies; it does not silently treat them
as free. Populate those rows only from actual measurements and disclose scope.

For exact sense matching, first create shared human interpretation labels in
the complete gold. Free model paraphrases are not automatically comparable
labels. `source_term` is available only for term studies and measures lexical
presence per source; it is a different outcome from exact occurrence detection.

## Notebook/API use

After running the demo, score its saved study from a notebook:

```python
from pathlib import Path
from termfinder.experiments import compare_study

study_path = Path("outputs/experiment-smoke/neologisms/study.json")
report = compare_study(study_path)
report["runs"]
```

The notebook's current directory must be the repository root for that relative
path; otherwise use the saved study's absolute path. `compare_study` reads files
and performs deterministic validation/scoring. It does not run providers.

For an already frozen Quarry dataset, the export adapter is
`termfinder.experiments.quarry_run(dataset, run_id="my-run", software_revision="COMMIT_SHA")`.
Use a fresh arm-only project with unchanged configuration across pauses/resumes;
the bridge rejects mixed historical configurations. If job planning is incomplete
or its completion is unavailable, completed individual jobs do not make a whole
source complete. Direct in-memory
comparison uses `compare_experiments(corpus, gold, runs, ...)`. Preserve returned
normalized files with their corpus/gold and provenance rather than regenerating
them from mutable live project state. See [complete-source gold preparation](../../docs/research/evaluation.md)
and [the publication evidence chain](../../docs/research/publication-protocol.md).

## Before a real pilot

Use development-only calibration to fix research policy and adapter behavior,
then freeze independent family-grouped test sources and complete human gold.
Predeclare the primary contrasts, finite budgets, cold/warm cache conditions,
semantic review rubric, and uncertainty analysis. Submit the concrete model,
account/allocation, scope, resource limits, and expected costs for explicit live
authorization. The roadmap provides the phased procedure; the smoke provides
engineering evidence only. Do not launch a paid collection, scheduler job,
model installation, or persistent service from an agent-generated study file.
