# V7 verification and implementation limits

Verified on October 6, 2026, using CPython 3.12 on macOS arm64. V7 lives in a
separate checkout and environment. V3–V6 and their saved outputs were preserved.
The starting branch included unmerged draft PR #6 (`7c3ddc7`) and was merged with
the inspected remote `main` (`96e877e`). V7 extends the existing scorer and durable
collection engine; it does not replace them.

## Completed engineering checks

| Capability | Fresh offline evidence | What the check establishes |
| --- | --- | --- |
| Regression and V7 modules | **440 tests passed** with `unittest discover` | Existing collection behavior plus contracts, adapters, ablations, review, recovery, CLI and accounting checks pass in the tested environment. |
| Independent installation | Built and installed `nlpx-termfinder==7.0.0` into `.venv-v7`; installed CLI exercised from an external temporary directory without source `PYTHONPATH` | The wheel runs without a sibling checkout or development source import. Both `quarry-study` and inherited `termfinder` help commands work. |
| Study acceptance rehearsal | Four hand-authored complete sources, ten arms, nine cold arms prediction-locked; separate warm extension | Actual Quarry Engine ablations and synthetic library-shaped LangExtract/DELM replays use the same frozen parsed corpus. Contract freezes before extraction; predictions lock before external synthetic gold is supplied. |
| Evidence and scoring | Invalid generated wording remains auditable; an entirely filtered/failed source retains false negatives; occurrence and source-term reports saved and reproduced | The shared comparison retains full-source denominators and honest null costs. Saved reports reproduce without model calls. No semantic validity follows from exact occurrence. |
| Review and timing | Full sources and original evidence in blinded packets; judgment reversal, missing-item addition and reversible removal; 30-second synthetic timer arithmetic | Views reverse without deleting packet evidence. Pauses are excluded, unknown work timing stays unavailable, and repeated exposure is rejected. The timer value is a fixture, not measured human effort. |
| Gold and amendments | Draft/frozen/amended history and immutable prediction identity; external version/hash/provenance checks; earlier gold preserved | Internal content consistency and sequencing are checked. Bare gold labels remain declared but unattested. Local files cannot prove independent custody or prior lack of access. |
| Adapter boundaries | Twelve focused adapter tests, including actual wrapper methods with injected API-shaped fake modules | Dispatch accounting, parse/alignment/filter hooks, ambiguous spans, native overlap dispositions, retries and terminal overruns are checked without importing third-party libraries. |
| Recovery | Uninterrupted reference plus 17 fault arms saved at concurrency four; tests compare selected schedules at concurrency one and four | Logical fault assignment, retained evidence, missing work, repeat dispatches, uncertain reservations and frozen exports are assessed using actual Engine/SQLite state. |
| Researcher and GT workflows | Seven measurement tests; synthetic setup/correction/comprehension log; inert GT bundle and unknown accounting import | Capture and correction schemas work. GT configuration remains operator-supplied and unauthorized to execute. Measured allocation costs, token estimates and unknown costs remain distinct. |
| Notebook and own-agent handoff | All five notebook code cells executed against the installed wheel; copyable prompts and CLI procedures | The offline researcher workflow works. The notebook contains no saved outputs, credentials or collected corpus data. |
| Dependency and artifact checks | Core/build exact pins; 81 optional wheels pinned by hash; relative links and changed packaged skill re-audited | The optional graph is a metadata-only lock for CPython 3.12/macOS arm64. It is not a transitive source-code security review. |

The full suite, wheel build/install, installed CLI/notebook and saved acceptance
runs used the reviewed [offline launcher](../tools/verify_offline.py) and
[Seatbelt profile](../tools/offline.sb). The environment contains no credential
variables; network and unrelated user-file reads are denied and probed before
execution. CPU, wall time, file size and file descriptors are bounded. A plain
subprocess timeout alone would not provide this isolation.

Generated verification reports, Projects, environments and wheels remain local
under ignored `verification/`, `.venv-v7/` and `dist/`. They are excluded from the
draft PR. Only code, documentation, dependency metadata and synthetic templates
are checked in. There were zero paid requests, model downloads, GT allocations,
participant activity, external contact or scheduled services.

## Reproduce the offline checks

Install the core with the README commands, then run these in a reviewed isolated
environment. Supply your own trusted interpreter and runtime roots to the
macOS launcher; the paths below are placeholders, not institutional configuration.

```sh
env -i PATH=/usr/bin:/bin /TRUSTED/PYTHON -I -S tools/verify_offline.py \
  --python .venv-v7/bin/python --runtime-root .venv-v7 \
  --base-runtime-root /TRUSTED/RUNTIME --source \
  --report verification/full-tests.json --timeout 300 -- \
  -m unittest discover -s tests -v

# Omit --source for installed-wheel verification.
env -i PATH=/usr/bin:/bin /TRUSTED/PYTHON -I -S tools/verify_offline.py \
  --python .venv-v7/bin/python --runtime-root .venv-v7 \
  --base-runtime-root /TRUSTED/RUNTIME \
  --report verification/installed-notebook.json --timeout 120 -- \
  tools/check_v7_installed.py
```

The installed checker deliberately verifies this `.venv-v7` environment and
executes only the authored synthetic notebook. Equivalent Linux/container
isolation needs separate configuration and verification. Fresh demos generate
new UUIDs and timestamps; reproducibility means recomputing saved frozen results,
not identical bytes across independent generations.

Useful offline commands, inside the same reviewed isolation:

```sh
quarry-study demo --out NEW_DEMO_DIRECTORY
quarry-study compare NEW_DEMO_DIRECTORY/comparison.json --out recomputed.json
quarry-study faults --out NEW_FAULT_DIRECTORY --concurrency 4
python tools/check_v7_artifacts.py
```

## Measurements and integrations still pending

LangExtract 1.7.0 and DELM 0.1.4 direct sources were statically inspected, and
replaceable native library hooks are implemented. Their imported dependency
trees have **not** been fully reviewed or executed. API-shaped tests and replay
fixtures do not establish native algorithm behavior. Before any native execution,
review the pinned import tree and run isolated library smoke tests with fake
transports. A live transport must enforce the meter's limits, avoid hidden SDK
retries, and capture returned model/checkpoint/finish metadata. Declared transport
flags and model names are not external attestation. See
[adapter limitations](V7_ADAPTERS.md).

The prepared Quarry ablation executor is fake-provider-only. Generic runners can
be supplied explicitly, but own aggregate enforcement and realized resource
attestation. Common ceilings do not establish equal achieved inference resources.
Current schedule seeds record ordering and identity; they do not implement
stochastic decoding control. Warm results stay outside primary cold contrasts.

Recovery interventions reopen real state at controlled boundaries. They are not
arbitrary process-kill tests or evidence of provider-side exactly-once billing.
The proposed stateless redispatch control in H3 has not been implemented as a
comparative study arm. Virtual waits and simulated prices are not human recovery
time, real cloud charges or platform latency.

Semantic summaries preserve decisions and uncertainty, but do not compute an
empirical per-system semantic-quality estimate or H2 noninferiority test. The
study scorer executes the declared detection contrast; semantic, timing, usability
and GT outcomes remain null with reasons. H1–H4 require qualified independent
humans, actual metered extraction and prospectively frozen analysis choices.
Formative researcher tasks, consent and institutional procedures are proposed;
no recruitment was performed. GT bundles do not select a scheduler/site or submit
work. Publication novelty, extraction superiority, human-effort savings, usability
and GT performance are unestablished. The [methods and pilot protocol](V7_METHODS.md)
define prerequisites, rivals and stop rules for separately authorized studies.

The inherited harness connection and configurable profiles remain available.
V7 study operations currently use the CLI/Python APIs; no new study-specific MCP
tool surface is claimed. Historical profile rates and moving aliases were
inspected as declarations, not verified as current prices or routing. Python
3.11/3.13, Linux and optional dependency execution are not validated by this
CPython 3.12/macOS arm64 run.
