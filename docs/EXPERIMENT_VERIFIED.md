# Offline experiment-scaffold verification

This verifies the first comparison layer, not the scientific hypotheses in
[the roadmap](EXPERIMENT_ROADMAP.md). No live model, search, scheduler, student
study, or publication of collected data was performed.

The regression suite passed 382 tests. After the final contract-validation
changes, all nine experiment tests passed again. The hand-computable cases check
one recovered occurrence and two misses, including a failed positive source;
negative-source false positives; Unicode offsets; duplicate predictions; literal
sense labels; invalid proposal retention; unavailable/uncertain costs; and paired
family resampling with undefined metrics kept explicit.

The smoke demonstration completed three recipe cells with fresh Broad and
Specialists projects, the same four frozen synthetic sources, three source
families, independently authored fixture labels, and saved partial Broad results.
All six completed arms resumed successfully; a later completed resume made zero
provider calls. Re-scoring each saved study reproduced its report exactly. These
are fake-provider measurements, not actual extraction quality or model costs.

A wheel was built from a separate source copy using pinned cached dependencies
and installed into a new environment. The actual installed `termfinder
compare-experiments` entry point reproduced the saved neologism report from a
separate working directory without source imports. The CLI branch performs no
project creation or model dispatch.

Every execution used the reviewed macOS Seatbelt launcher with an empty
credential environment, finite CPU/wall limits, network denied, and unrelated
file reads denied. Isolation probes passed before the requested code executed.
Local receipts and outputs are under ignored `verification/` paths:

- `experiment-scaffold-suite-sandbox.json`
- `experiment-scaffold-validation-final-sandbox.json`
- `experiment-scaffold-smoke-release-sandbox.json`
- `experiment-build-installed-sandbox.json`
- `experiment-wheel-receipt.json`
- `experiment-smoke-release/report.json` and the three recipe reports

The checks do not establish semantic accuracy, independent human gold, recall on
real communities, baseline adapter parity, API billing guarantees, participant
usability, or performance on Georgia Tech compute. LangExtract/DELM adapters,
blinded semantic/timing review, a request-keyed comparative fault runner, and
live measurements remain planned work. The current snapshot bridge supplies an
accepted inventory; raw-generator grounding rates require the separate raw
proposal archive and are unavailable from that inventory alone.
