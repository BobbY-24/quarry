# Public-research-inspired student recipes

See [the named student walkthroughs](../../docs/NLPX_STUDENT_GUIDE.md) and [the complete shared procedure](../../docs/LAB_PROTOCOL.md).

There are 11 proposed, researcher-editable recipe JSONs and 11 matching batch-metadata examples. [catalog.json](catalog.json) maps public student names, research anchors, filenames and routing labels. These are proposed applications, not assignments, PI requests, deployed lab studies or reproductions of the cited datasets.

Every few-shot sentence is synthetic and explicitly labeled. No datasets were downloaded for these examples. Configure/ingest/estimate using the CLI; a real corpus still needs its own observed text. Custom recipe IDs are not a general `FakeProvider` extraction demo; rehearse with `examples/offline_demo.py` and shipped starters.

Each template starts Broad, uses `glm-deepseek`, has two additive specialist lenses, limits calls/time/concurrency, and sets total/stage spending to zero. Discovery is disabled. `local-only.invalid` is a reserved nonresolving sentinel host that restricts URL ingestion; it is not an actual research source. Deliberately edit the scope, dates, languages, community routes, field descriptions and finite budgets before an explicitly authorized live pilot. Provider credentials stay only in configured environment variables.

Batch metadata has null rights/origin/date placeholders with reasons. Fill them for the actual inputs. Put external document identifiers/families under `constraints` or maintain a source-ID mapping; arbitrary new metadata keys are not automatically preserved. Split with an external family mapping before tuning, and annotate complete held-out sources independently of candidates.

The example attributes use supported string fields; choice lists described in field text are an annotation rubric, not engine-enforced enums. Unavailable values stay null. Human annotation should supply adjudicated values separately from model suggestions.
