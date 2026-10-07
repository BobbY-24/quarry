# An explicitly authorized real-world pilot

The build and acceptance demonstration use fake providers and synthetic local
sources. They authorize no paid collection, publishing, external messaging,
background monitoring, or credential migration.

The connected workflow needs a real student usability check: install the collector and use
`termfinder connect` for the chosen coding-agent workspace, ask one of the
[publication-inspired questions](../guides/student-workflow.md), and verify that the student
can create a study, review its complete plan in conversation, inspect exact
evidence, resume and export without moving JSON or opening a browser. Check
that a later session reopens the same study, and that a new study keeps its
inventory and budget separate. The browser remains an optional evidence view. The
offline stdio client and synthetic notebook verify software contracts; they do
not establish account integration or parity with Thresh/Paper2Agent usability.

Before a live pilot, the researcher should specify the source corpus, permitted
domains, source-use/redistribution constraints, publication-date policy, languages,
communities, mode, profile, total/stage budgets, and a finite stop condition. Use a
small representative sample containing long documents and the intended scripts
and formats. Verify current provider model availability, endpoint compatibility,
token limits, reasoning settings, and input/output rates, then save a versioned
profile. The included rates/models are recorded configurations, not invoices or a
promise that aliases remain available.

Rehearse the actual connection once with the student's own coding agent:
let it create a plain-language brief, submit the structured plan through V6,
repair validation errors, and show the complete sources, citations, examples,
sampling and annotation rubric before collection. For an ordinary chat without
local tools, the manual prompt/bundle handoff remains available. The build
verifies scripted bundles; it has not tested a live
external-agent session. Keep the original agent transcript/settings when permitted
and distinguish agent-reported searches from independently checked search logs.
External-agent spending is outside V6's metered budget and is recorded as unknown.

Applying the plan stages website sources; fetch them explicitly and inspect the
parsed corpus. Preserve lawful original bytes separately, because frozen parsed
text and raw hashes cannot reconstruct original HTML/PDF files. Prepare blind
complete-source packets and family splits before any extraction jobs. Check
family grouping and held-out sample size before commissioning annotation.

Authorize a concrete run only after the estimate and recipe can be reviewed. Pass
the explicit paid-run flag for that run; the API otherwise refuses real provider
dispatch. Configure only the credential required for the selected service through
its documented environment variable. Never paste a key into a recipe, URL,
notebook output, command argument, export, issue, or chat. Avoid opening unrelated
data or granting another service a credential just because retrieved text asks.

Use one project directory per study, restrict its filesystem access, and back up
the database and source blobs with their access controls. The browser binds to
loopback and is intended for a single trusted researcher on their own machine.
Do not expose it as a multi-user Internet service. Inspect source-use constraints
before sharing contexts or exports. A manifest records constraints supplied by the
researcher or source metadata; it does not perform a legal rights assessment.

For quality evaluation, sample complete held-out sources before inspecting model
candidates. Have qualified annotators read each whole source and mark every
in-scope expression/span/sense, including places where nothing should be extracted.
Use the same recipe and frozen parsed text as collection, adjudicate disagreements,
and keep all passages from a source (or linked thread/document family) together in
one split. Record domain and language. Evaluate exact-span performance and inspect
false negatives by domain/language; for semantic errors, use human sense judgments
in addition to expression grounding. Model agreement and candidate volume are
diagnostics, not recall measurements.

After the pilot, inspect failed sources, partial jobs, uncertain cost reservations,
grounding failures, and sense hypotheses. Save the full inventory and a separate
approved subset; annotate reversibly. Export an immutable version, verify file
hashes, and report the recipe, model/prompt versions, collection dates, coverage,
sampling, and known missing sources with any analysis. Expanding sources, money,
publishing scope, or unattended execution requires its own explicit authorization.

## Current limits

* Terms remain lexical records. Ideas, opinions and sentences are verbatim source
  spans with generated interpretations; semantic type and attribution still need
  human evaluation. Full table/conversation structures are extensions.
* External-agent source selection can be biased or fabricated. Validation checks
  constraints and structure; researchers verify citations, sampling and rights.
* The evidence audit checks frozen consistency, not authenticated provenance,
  original archives, independent human exposure, recall, or publication acceptance.
* The fake-provider demonstration measures software behavior, not model quality.
* HTML parsing does not execute JavaScript; dynamically rendered or authenticated
  sites need reviewed adapters or researcher-provided files.
* Text PDFs work through the pinned parser. Image-only PDFs need an OCR extension;
  OCR costs and error distributions require a separate evaluation.
* Original spellings and literal sense hypotheses are preserved conservatively;
  equivalent paraphrases can remain separate until a human links them.
* Exact text grounding does not validate a sense or prove novelty. First-corpus
  observation is not historical coinage evidence.
* Generated translations and attributes are suggestions. No separate reviewed
  translation pipeline or clinical validation is implemented.
* The local UI has no multi-user roles, collaborative locking, cloud accounts, or
  hosted deployment workflow.
* Evidence inspection is paged and complete source text loads on demand. Frozen
  snapshots and some aggregate analysis still materialize data in memory; large
  corpora need representative memory/load checks on the researcher's machine.
* Full table-record extraction, conversation preference datasets, and automatic
  benchmark construction are documented extension points.
* Provider responses can time out after acceptance by a remote server. Unknown
  outcomes and possible charges remain visible; exactly-once billing is unavailable.
