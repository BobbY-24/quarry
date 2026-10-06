# Build verification — October 5, 2026

The current **V6.4.0 own-harness workflow** is documented in
[harness verification](HARNESS_VERIFIED.md): 277 final installed-package tests,
project-local connection files for Codex/Claude/generic, complete browser-free
stdio workflows across independent studies, reconnect/resume, full plan and
evidence inspection, visible source problems, immutable exports, eight typed
API workflows and the installed CLI/notebook checks. Real host accounts and
student usability remain untested. The earlier **V6.3.0 simple agent workflow** is documented in
[simplification verification](SIMPLIFICATION_VERIFIED.md): 234 installed-package
tests, eight complete synthetic workflows, installed CLI/MCP/notebook checks,
and an actual browser walkthrough. The **V6.2.0 long-run release** is documented
in [resilience verification](RESILIENCE_VERIFIED.md). Earlier evidence below
is preserved as historical release verification.

## V6.1 agent-assisted collection release

The final independent wheel includes the plain-language brief form, handoff for
the researcher's own agent, strict returned-plan validation and repair feedback,
compiled input files, Terms/Ideas/Opinions/Sentences, pre-extraction source-family
freeze and blank annotation packets, and a frozen publication consistency audit.
The original V6.0 evidence and wheel below remain preserved.

| Check | Result | Saved evidence |
| --- | --- | --- |
| Final source suite | **149 tests passed in 10.701 seconds**; includes all three starter term policies in Broad/Specialists and the added handoff, typed-record, browser, and publication-audit tests | `verification/agent-release-suite-sandbox.json` |
| Final wheel build/install | Built with pinned local dependencies and installed in separate `.venv-6.1`, with no network, credentials, or sibling imports | `verification/agent-release-build-sandbox.json`, `verification/agent-release-install-sandbox.json` |
| Installed student briefs and notebook | All five research-inspired briefs prepared, validated, applied and froze a synthetic source; nine reviewed new notebook code cells executed from a fresh directory against the installed package | `verification/agent-release-installed-report.json`, `verification/agent-release-installed-sandbox.json` |
| Installed four-type rehearsal | Term, idea, opinion and sentence each retained exact evidence; one-job pause/reopen/resume completed; annotation undo retained history; frozen audits passed; all exported file bytes matched across two exports | `verification/agent-workflow-release-6.1.0/acceptance_report.json`, `verification/agent-release-demo-sandbox.json` |
| Actual installed browser | Readable plan, estimate and progress; exact opinion text and offsets; suggestion labels; missing explanatory quote reason; approve/undo; frozen integrity audit; all-format 44-file export | `verification/agent-release-browser-report.json`, `verification/agent-release-browser-sandbox.json` |

The final wheel is `dist/nlpx_termfinder-6.1.0-py3-none-any.whl`, SHA-256:

```text
1fa19cce60266c2eb0fcc9ef5cd30dd5bfea32018cd99ff9d4e81d8d50513eca
```

Every executed application check used the reviewed bounded macOS sandbox with
an empty credential environment, denied outbound network and denied unrelated
file reads. The browser allowed loopback inbound access only and stopped after
its finite five-minute lifetime. All assistant/provider replies were scripted
fixtures; no external ChatGPT/Claude session or paid provider was invoked.

The new tests additionally reject stale briefs, scope/budget/type/profile
expansion, forged retrieval dates, symlink escapes, malformed nested input,
recognized secrets, unresolved choices and configuration races. They verify
literal source grounding, all profile/mode/type template routes, stable term
compatibility, separate nonterm source identities, frozen plan/source/provenance
joins, tampering diagnostics, and blank source-family evaluation packets before
any job planning. These are software checks, not research accuracy measurements.

The external-agent round trip with a real student's account remains untested.
Actual agent planning and fresh extraction are nondeterministic; external-agent
costs are explicitly unmetered by V6. Exact-span checks establish occurrence,
not meaning, truth, novelty, attribution, representativeness or recall. Original
bytes must be archived separately for parser replay; a stored archive reference
is a declaration, not an independently checked archive. Independent exhaustive
held-out human annotation, source rights and a finite authorized pilot remain
required before publication claims. See `docs/PUBLICATION_PROTOCOL.md` and
`docs/PILOT.md`. Linux execution, OCR and multi-user deployments remain outside
the completed macOS verification.

## Preserved V6.0 build evidence

Completed checks used reviewed V6 code, synthetic local sources, fake providers
and fake fetchers. macOS Seatbelt denied external networking and unrelated
user/temporary file contents; each launcher invocation first passed denied-network
and unrelated-file marker probes. Child processes had a clean credential-free
environment and finite resource/wall-clock limits. No paid experiment,
publication, external message, or persistent scheduled job was launched.

| Check | Result | Saved evidence |
| --- | --- | --- |
| Complete offline unit/acceptance suite | Final reviewed source suite: 88 tests passed in 6.038 seconds | `verification/unit-sandbox.json` |
| Researcher workflow demo | All three starters × Broad/Specialists, 11 acceptance checks passed | `verification/demo/acceptance_report.json`, `verification/demo-sandbox.json` |
| Immutable exports | CSV, JSONL, Parquet and annotation bundles exported twice from each saved version; file bytes/hashes match after later annotations | `verification/demo/*/export-one`, `verification/demo/*/export-two` |
| Independent package build and install | Wheel built and installed from reviewed local dependencies, with no network | `verification/build-sandbox.json`, `verification/install-sandbox.json` |
| Installed CLI and notebook | Packaged CLI completed setup/ingestion/estimate/pause/resume/evidence/snapshot/version listing/all exports. Eight reviewed notebook code cells executed from a fresh temporary directory without source `PYTHONPATH`. Packaged recipes, profiles, fixtures and browser assets were present. No paid requests. | `verification/installed-sandbox.json`, `verification/installed-report.json` |
| Actual local browser | Packaged browser passed Specialists selection/cost estimation, one-job pending interruption/resume, exact CJK/combining-mark evidence highlights, approve/undo with retained history, frozen all-format export, and final regression checks for annotation draft/profile edit persistence and repeated export. | `verification/browser-report.json`, `verification/browser-sandbox.json`, `verification/browser-evidence.jpg` |

The wheel is `dist/nlpx_termfinder-6.0.0-py3-none-any.whl` with SHA-256:

```text
9e4563247c6b850067b816ba6af64e6e9f03372ca5037f9e0142322ece6fce52
```

Runtime dependencies are pinned to `pypdf==6.19.0` and `pyarrow==25.0.1`;
build dependencies are pinned in `requirements-build.txt`. The verification
interpreter is Python 3.12.14 on macOS. Linux installation/container instructions
are documented and still need execution on the target Linux machine.

The demo verifies exact Unicode spans and original contexts, PDF pages, distinct
literal senses, both single-extractor discoveries, resume/cache behavior,
reversible rejection/alias annotations, visible malformed-PDF failures, budget
admission stopping before dispatch, bounded discovery lineage/scope, and saved
version reproduction without model calls. Independent complete-source synthetic
labels report missed contextual mentions; these demonstrate false-negative
measurement and are not quality estimates for GLM, DeepSeek or Gemini.

Production limits remain explicit: the browser currently polls the full inventory
and source text, so large corpora can become slow or memory-heavy. Use the CLI/API
for large collections until pagination and incremental evidence loading are added.
The local UI is a single-researcher loopback interface. Field accuracy, source-use
permissions, model availability/rates, multilingual PDF/OCR calibration, and a
complete held-out annotation study require a separately authorized real pilot.
See `docs/PILOT.md`.
