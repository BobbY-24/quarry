# Full-source semantic review, adjudication and active time

V7's `termfinder.semantic_review.ReviewWorkspace` keeps complete source text,
original candidate evidence, model suggestions and human judgments separate.
It builds on Quarry's existing evidence inspection and reversible annotations;
the research ledger adds a frozen packet, a four-axis rubric, system blinding,
timing, independent complete-source signoffs and versioned gold exports.

| Mode | Purpose | Can export recall gold? |
| --- | --- | --- |
| `candidate_review` | Judge submitted discoveries and their interpretations against full source text | No; candidate lists cannot expose omissions |
| `assisted_complete_source` | Judge candidates and inspect every complete source, adding missing observations and correcting/removing view items | No; this is the assisted experimental condition |
| `independent_gold` | Qualified humans annotate complete sources independently of system candidates, in a separate workspace | Yes, after independent review and adjudication |

An independent gold workspace must be outside the planning/extraction workspace.
It rejects saved-run inputs and begins with no candidates. Qualified independent
humans add exact source observations themselves. Do not give gold annotators
candidate packets or model suggestions. A separate coordinator controls access;
filesystem separation is not an authentication mechanism.

## Packets and semantic decisions

```python
from termfinder.semantic_review import ReviewWorkspace

review = ReviewWorkspace("planning/review")
packet = review.create_packet(
    corpus, saved_runs, mode="assisted_complete_source",
    rubric=spec["policy"]["annotation_rubric"],
)
item_id = packet["candidates"][0]["candidate_id"]
axes = {
    "eligibility": {"decision": "accept", "label": None,
                    "reason": "Fits the frozen inclusion policy."},
    "contextual_meaning": {"decision": "accept", "label": "human contextual meaning",
                           "reason": "Supported by the complete source."},
    "definition_support": {"decision": "unscorable", "label": None,
                           "reason": "No definition supplied."},
    "translation": {"decision": "unscorable", "label": None,
                    "reason": "No translation requested."},
}
decision = review.judge(item_id, axes, actor="reviewer-a")
```

Each axis accepts `accept`, `reject`, `uncertain`, `disputed` or `unscorable`,
with an explicit reason and a string label or null. An accepted contextual
meaning requires a human label. Definition support and translation can be
unscorable with a clear not-applicable reason; do not call them correct by
default. Eligibility and meaning are separate: exact source occurrence does not
establish either. Human semantic judgments can recognize paraphrases under the
rubric; exact string equality between labels remains a different, limited test.

`packet()` exposes complete frozen text, source locations and hashes, opaque
candidate pseudonyms, original observed text/offsets/language, grounding
diagnostics and separately marked model suggestions. Identical candidate
observations across arms are merged into one review item, preserving every
suggestion and its hidden origin mapping. The reviewer view excludes system,
run, model and configuration identities and randomizes candidate order. Invalid
original proposals remain visible and are never repaired automatically.

Normalized detection runs intentionally contain only the common observed-span
and interpretation fields. Attach original evidence separately with
`create_packet(..., evidence_details=details)`, using a mapping of `run_id` to
`prediction_id` to detail objects. Supported attachments are `context`,
`context_start`, `context_end`, `contexts`, `definition_quote`,
`definition_quote_reason`, `translation` and `source_locations`. They remain
under each model suggestion as `original_evidence`, carry explicit origin labels,
and are marked `human_verified: false`. Missing attachments have an explicit
unavailable reason. Details cannot supply system/model provenance, execute code,
or change the frozen detection contract.

`quarry_review_details(dataset, run_id)` builds this mapping from a saved Quarry
snapshot, retaining original occurrence context, definition quote, translation
and parser-reported page/block locations. Its prediction IDs match
`experiments.quarry_run(dataset, run_id=...)`. An exact quotation is source
evidence; whether it supports a definition or translation requires the human
rubric. The attachment's recorded location is not independently attested merely
because it is present.

`coordinator.json` retains hidden source-run/prediction mappings; keep it away
from reviewers. Content, suggestion style, multiplicity and contextual clues may
still reveal origins. Blinding is feasible system-identity masking, not a promise
of perfect anonymity. Do not include system names or secrets in interpretation
text. This API preserves supplied text rather than sanitizing away evidence.

The packet cannot be replaced through the API. Human events live in a separately
hashed, append-only history, always with `origin: human`, an actor, timestamp and
packet identity. Model suggestions cannot become human judgments automatically.
Actor identifiers should be study pseudonyms rather than credentials.

## Corrections, reversals and adjudication

`judge(item_id, axes, actor=..., supersedes=...)` appends a revised judgment and
requires the same human's latest judgment ID in `supersedes`. Earlier judgments
remain intact. An adjudication references at least two current judgments from
distinct humans and requires a third adjudicator and a reason:

```python
other = review.judge(item_id, other_axes, actor="reviewer-b")
resolved = review.adjudicate(
    item_id, adjudicated_axes,
    judgment_ids=[decision["event_id"], other["event_id"]],
    actor="adjudicator", reason="Resolved against full source context.",
)
review.reverse(resolved["event_id"], actor="adjudicator", reason="Reopen ambiguity.")
```

`record_item("add", item, actor=..., reason=...)` lets assisted reviewers
discover missing observations while reading complete sources. `item` contains
`source_id`, `observed_text`, `language`, `start` and `end`; offsets are Unicode
codepoint offsets and must match the frozen source exactly. The returned event
contains its opaque `item_id`. `record_item("correct", item, item_id=..., ...)`
records a new view of an observation without changing earlier evidence.
`record_item("remove", item_id=..., ...)` removes it from the current view.
Reversal restores a removed or corrected view. Original packet evidence and all
earlier edits remain in history. A correction invalidates judgments tied to the
old evidence hash; adjudicators cannot silently reuse judgments about another
span.

`reverse(event_id, actor=..., reason=...)` appends a reversal of a judgment,
adjudication, evidence edit or source-completeness signoff. It never deletes the
original record. Gold export rejects reversed/superseded judgments and unresolved
eligibility or meaning instead of silently treating them as negatives.

## Active-time capture and exposure control

```python
started = review.start_session(
    actor="reviewer-a", exposure_registry="coordinator/shared-exposures",
    prior_exposure=False,
)
session_id = started["payload"]["session_id"]
review.pause_session(session_id, actor="reviewer-a", reason="Break.")
review.resume_session(session_id, actor="reviewer-a", reason="Resume source review.")
review.finish_session(session_id, actor="reviewer-a", reason="Completed task.")
measurement = review.summary()
```

Only active intervals contribute to recorded active seconds. Pauses, wall-clock
timestamps and session transitions remain inspectable. Backward timestamps and
invalid transitions are rejected. `correct_time(session_id, active_seconds=...,
actor=..., reason=...)` appends a correction after completion while retaining the
original measurement. Unfinished sessions or unmeasured active time yield null
totals with reasons, rather than invented zeroes. `summary()` also reports
additions, removals, corrections and reversals.

`semantic_summary()` (also included under `summary()["semantic"]`) reports the
latest current-evidence human judgments by axis and decision, adjudicated item
counts, judged/unjudged/pending items, and per-item disagreements. Matching human
decisions are still recorded separately until adjudication; a reversed judgment,
newer judgment or evidence correction makes an earlier resolution unavailable.
Undefined semantic quality rates remain null with a reason. These observation
judgments do not automatically establish the quality of each differing model
suggestion; any per-system semantic analysis must use the coordinator's origin
mapping and its predeclared rubric for the specific reviewed attribute.

Start the timer before reviewing content or entering judgments. A human who has
already performed review actions on a packet cannot start a fresh timed session
for it. Every judgment, adjudication, evidence edit, reversal and completeness
signoff records its active session or an explicit unavailable-time reason.
Actions entered without an active timer, including corrections after completion,
make the total incomplete and null; the measured subtotal remains visible. This
keeps untimed corrections from silently appearing as an effort saving.

Use one coordinator-owned `ExposureRegistry` for every condition. Starting a
session records the reviewer and every frozen source family before work begins.
The same actor cannot start a second task involving a previously seen family,
even in another condition or workspace. An explicit prior-exposure declaration
also rejects entry to a fresh timing condition. Pause/resume continues the same
task without re-claiming exposure. This prevents recorded task repetition from
creating artificial time savings when the shared registry and stable actor
identities are used correctly.

Prior exposure, stable identities, qualification, independence and honest timer
use remain human attestations. Using another registry or identity defeats those
checks. The timer is user-operated and based on local timestamps; it is not an
activity sensor or verified measure of attention. The protocol must standardize
what counts as active work, training, assistance, interruptions and correction
time. Counterbalance condition order on disjoint families, hold harness/model
and assistance fixed where appropriate, and record experience and task difficulty.
Participant recruitment and execution require separate authorization.

## Independent complete-source gold

Create an `independent_gold` packet with no run inputs and an explicit
`workspace_root` pointing to the planning workspace. At least two qualified
humans must independently inspect every source, including sources with no
eligible observations. `mark_complete(source_id, actor=..., qualified=True,
independent=True, note=...)` records signoffs on the current complete source
inventory. Inventory additions, removals and corrections invalidate old
completeness signoffs until humans reinspect and sign the changed inventory.

Every item requires adjudication referencing two current human judgments and a
third human. Eligible items require an accepted contextual meaning. Rejected
items remain in review history and are omitted from detection positives; uncertain,
disputed or unscorable eligibility blocks publication of gold. Source signoffs
and adjudication do not prove qualification or annotation exhaustiveness by
themselves; their provenance belongs in the study record.

`export_gold("gold-v1", actor=..., provenance=...)` creates a new directory with
an immutable `gold.json` complete-source list and a `manifest.json` recording
the gold version/content hash, packet hash, history tip and provenance. A repeated
version is rejected. Later reversals and amendments never alter earlier exported
gold versions. Export a new version after resolving corrections, then create a
documented study amendment when scoring that new gold version.

Gold uses the existing scorer's typed span format. Detection supports occurrence
and source-term units; semantic-axis judgments remain attached to gold items and
in the ledger. The current implementation supplies auditable individual judgments
and timing artifacts, not an automated noninferiority analysis, an agreement
coefficient, a statistical measure of semantic equivalence, or real user-study
results. Those require the frozen research design and authorized independent
measurements.
