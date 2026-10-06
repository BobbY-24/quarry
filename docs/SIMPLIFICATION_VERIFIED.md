# V6.3 simple workflow — verified October 5, 2026

The released package implements **describe → approve → inspect → export**.
The researcher uses an existing coding agent for the structured setup and a
three-tab local browser for **Plan, Evidence, Dataset**. Ordinary use does not
require maintaining or transporting recipe JSON. An ordinary chat without local
tools still has an expandable prompt/bundle fallback.

This release adds the guided workflow, packaged agent skill, fixed-project MCP
server, compact browser, examples and documentation on top of V6.2. The existing
long-run engine, provider profiles, full inventory, earlier environments,
wheels and verification outputs are preserved. V3/V4/V5 are not dependencies.
See [the student procedure](SIMPLE_WORKFLOW.md), [agent setup](AGENT_NATIVE.md),
and [architecture](ARCHITECTURE.md).

## Final package and executed checks

The independent wheel is
`../dist/nlpx_termfinder-6.3.0-py3-none-any.whl` (local artifact).
Its SHA-256 is:

```text
464dd64e3b960f77b86b08b472541d4deee2579382d7071be4e0848812542ddf
```

It was built with pinned build dependencies and installed into its own
`.venv-6.3`. Runtime dependencies are `pypdf==6.19.0` and `pyarrow==25.0.1`;
build dependencies are `setuptools==84.0.0`, `wheel==0.48.0` and
`packaging==26.0`. The executed platform was macOS and Python 3.12.14.
Installation and testing used reviewed local wheels, no network, and no sibling
version imports. Official package metadata/archive checks are recorded in
`../verification/simple-build-wheel-review.json` (local artifact).

| Executed check | Result | Evidence |
| --- | --- | --- |
| Preserved V6.2 baseline | 173 tests passed before the simplification work | `../verification/simple-baseline-6.2-sandbox.json` (local artifact) |
| Final installed package suite | **234 tests passed in 18.722 seconds** | `../verification/simple-compact-installed-suite-sandbox.json` (local artifact) |
| Final wheel build and independent install | Pinned offline build and install succeeded | `../verification/simple-compact-wheel-build-sandbox.json` (local artifact), `../verification/simple-compact-wheel-install-sandbox.json` (local artifact) |
| Eight installed researcher workflows | Terms, ideas, opinions and sentences each ran in Broad and Specialists; no jobs before approval; one-job pause/reopen/resume; one-extractor retention; exact evidence; reversible review; passing frozen audit; byte-identical exports after later live annotations | `../verification/simple-compact-workflow-release-6.3.0/acceptance_report.json` (local artifact), `../verification/simple-compact-installed-demo-sandbox.json` (local artifact) |
| Installed CLI, packaged skill, stdio MCP and notebook | Guided commands passed; exported skill resources present; actual installed `termfinder-mcp` entry point initialized/listed tools/returned status; all five notebook code cells executed | `../verification/simple-compact-installed-report.json` (local artifact), `../verification/simple-compact-installed-smoke-sandbox.json` (local artifact) |
| Actual installed browser | Agent-prepared plan appeared without a reload; one-job partial state and resume; exact highlighted evidence; separate human attributes; approve/undo; named all-format export and frozen audit | `../verification/simple-compact-browser-report.json` (local artifact), `../verification/simple-compact-browser-plan-report.json` (local artifact), `../verification/simple-compact-browser-sandbox.json` (local artifact) |

All application checks ran in a reviewed, bounded macOS Seatbelt sandbox with a
clean credential environment. Denied-network and unrelated-file-read probes
passed. The browser allowed inbound loopback on port 8766 only, denied outbound
networking, and had a five-minute lifetime. It was stopped deliberately after
the completed walkthrough; its exit status 130 records that stop, not a failed
application assertion. No persistent service, real agent session, paid
collection, external message, upload or publication was launched.

## Browser observations and saved-state confirmation

The actual installed browser was exercised through these visible actions:

1. Open the fresh study. Only the collection type, question, domains, local
   folders and budget were expanded; the three main tabs and Advanced settings
   were accessible. Effective mode/profile were still displayed.
2. Submit a synthetic plan using the installed stdio MCP server while the
   browser remained open. Plan showed the exact inclusion/exclusion policy,
   one 750-character source, Specialists, fake profile, zero-dollar budget,
   parsed-length estimate and blank whole-source packet. No jobs existed.
   Preparation details and stage cost/reserve details were collapsed; the
   concrete decision and cost summary remained visible.
3. Approve with a one-job invocation limit. Progress showed three grounded
   records, one completed root, three pending roots and **partial** coverage.
   Clear the invocation limit and click Resume. Four jobs completed and four
   records remained, including two different senses of `anchor`.
4. Open `moonstep`. Evidence displayed the literal context and Unicode
   code-point offsets `[151, 159)`, a source-supported explanatory quote, and
   a separately labeled model-proposed interpretation. Set Approved, enter a
   human note and `innovation_type`, save, then Undo. Status returned to
   Unreviewed, the human attribute disappeared from the active view, and the
   annotation event remained in history.
5. Save `browser-rehearsal-v1` in Dataset. The interface reported a frozen
   version, 44 exported payload files, and passing evidence integrity checks.
   Its limitations remained visible. Save with the same name again: the same
   version was re-exported without model calls.

The saved-state check independently verifies four exact spans, two retained
`anchor` senses, the inactive human annotation with its retained attributes,
four completed jobs, the approved review and the passing frozen audit. It
compares all **45 files including `manifest.json`** across another re-export;
every byte hash matches and no jobs or runs are created. The interface's count
of 44 refers to payloads listed in the manifest, excluding the manifest itself.
The state check cannot prove that UI clicks occurred; the observations above
document those separately.

An earlier installed browser rehearsal also verified that an unsaved student
brief survives an incoming MCP plan, with an explicit **Load the agent's saved
plan** action. Those preserved reports use the initial V6.3 layout. Automated
UI regression checks cover this behavior in the final package.

Two fixture-check corrections are retained transparently: the synthetic MCP
helper must choose the starter recipe ID in the **brief**, rather than change
it in a returned plan; V6 correctly rejected the changed identifier. The saved
state checker initially counted the 44 payload files as the whole directory,
omitting `manifest.json`; the corrected check covers all 45. Earlier unsuccessful
sandbox reports remain alongside the successful corrected reports. Neither
correction changed the released collector code.

## Reliability and research boundaries covered

The suite includes exact grounding and Unicode offsets, separate senses and
community uses, deterministic deduplication, retention of single-extractor
discoveries, bounded truncation recovery, schema validation, cache identity,
budget/request admission, timeouts and retries, cancellation and interruption
recovery, uncertain provider outcomes, source/discovery bounds, failures,
paginated inspection, annotation undo, frozen exports and cost accounting.
The three starter term policies remain covered in both extraction modes.

Additional guided and agent tests reject stale or altered source/configuration
reviews, dispatch before approval, scope/profile/budget expansion, invalid or
secret-bearing plans, forged dates, symlink escapes, malformed/oversized JSON,
unauthorized paid transport and annotation-origin confusion. They check bounded
MCP result previews, fixed-project tools, source-scoped job dispatch, lock
ownership, cancellation during review validation, streamed packet hashing,
automatic preparation provenance and pre-dispatch approval timing.

The guided route freezes source families and blank complete-source packets
before any extraction jobs. Approval records are hash-bound declarations, not
authenticated signatures. Model annotations are audit suggestions; explicitly
relayed human annotations require a declared decision reference. The complete
grounded inventory always remains alongside an optional approved subset.

## What remains unverified or intentionally limited

- These scripted plans, synthetic documents and fake provider responses prove
  software contracts. They do not measure actual student usability, sampling
  quality, semantic accuracy or recall, or prove parity of usability with
  Thresh or Paper2Agent. No real Claude/Codex account connection was exercised.
- Installation and isolated checks on Linux remain documented, not executed
  in this macOS build. The browser/MCP service is for one local researcher;
  it is not a multi-user authenticated deployment.
- An unchanged captured plan can resume without its original local file.
  Changing recipe/profile/budget after jobs exist needs the advanced protocol
  or a separate study. Newly added sources require an explicit incremental
  research protocol; previously seen text cannot become newly blind gold.
- Original source bytes and verified redistribution rights must be retained
  separately. Text-bearing PDFs are supported; image-only PDF OCR, full table
  record extraction, conversation dataset construction and automatic benchmark
  generation remain extension points.
- Occurrence validation does not prove proposed meaning, truth, novelty,
  readability, sentence completeness or speaker identity. Blank packets are
  not gold. Recall requires independent exhaustive annotation of complete
  held-out sources and grouped splits, using the frozen rubric.
- Provider rates/model availability need verification before a real pilot.
  Token-derived actual costs are not invoices; external planning-agent costs
  remain unknown. Cancellation cannot retract an already dispatched request,
  and uncertain retries cannot guarantee exactly-once billing.

The next field acceptance step is a finite, explicitly authorized pilot with
a real student's existing agent and permitted corpus. Check setup/task
completion time, plan comprehension and evidence access; obtain independent
complete-source annotations, then report precision, recall and false negatives
by domain/language. Follow [PILOT.md](PILOT.md) and
[PUBLICATION_PROTOCOL.md](PUBLICATION_PROTOCOL.md) before publication claims.
