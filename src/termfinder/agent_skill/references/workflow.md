# Quarry connected-agent workflow and terminal/API fallback

## Connect once, then conduct each session in conversation

The researcher authorizes a specific existing agent workspace. After installing
the reviewed local package in its isolated Python environment, connect it with:

```sh
termfinder connect --host codex --workspace /path/to/research-workspace \
  --studies /path/to/research-workspace/v6-studies
```

Use `claude` for Claude Code or `generic` for a custom harness. Omitting
`--studies` uses `WORKSPACE/v6-studies`. A new studies root can be created inside
the chosen workspace; an external studies root must already exist. Do not
choose home, filesystem roots, hidden directories or symlinked roots.

`connect` copies the packaged skill and prepares only the chosen workspace's
host configuration. Codex uses `.agents/skills/v6-collect-research/` and
`.codex/config.toml`; Claude uses `.claude/skills/v6-collect-research/` and
`.mcp.json`. Generic mode exports `v6-collect-research/` and `v6-mcp.json` for
that host's documented registration procedure. Follow the returned activation
steps and verify an actual `list_studies` call. Files on disk do not establish
that a host trusted, loaded or connected them. Account access and organization
policy cannot be granted by this skill.

No global settings, hooks, persistent services, credentials or collection are
installed. Matching repeats are idempotent. Changed interpreter, studies root,
paid gate, customized skill or conflicting `v6` connection receive a diagnostic
rather than automatic replacement. Use a fresh specific workspace or explicitly
inspect and relocate/remove only Quarry's old artifacts before reconnecting; never
replace unrelated host configuration. Inline credential-bearing configurations
are refused. Never dump their contents to diagnose a conflict.
Close configuration editors while connecting: Quarry's lock coordinates its own
installers, not other applications. After a crash, inspect `.v6-connect.lock`
and confirm the setup stopped before explicitly removing a stale lock.

The default server permits only fake collection. A separately authorized real
pilot additionally needs the `--allow-paid` launch flag, secure provider
environment configuration, a finite budget and approval of the concrete plan.
Tools cannot enable that immutable launch gate. Do not append the flag to an
existing offline connection and pretend it was updated: differing definitions
conflict. A fresh pilot workspace may connect to the existing studies root.

The generated Codex prompt invokes `$v6-collect-research`; Claude invokes
`/v6-collect-research`. Study inputs and saved routing IDs are agent-managed.
The student should describe, review, approve, inspect and request exports using
ordinary language, with no mandatory browser or JSON handoff.

## Tool map for an entire connected session

The workspace launch is `termfinder-mcp --workspace STUDIES_ROOT`. An advanced
`--project STUDY_PATH` launch remains fixed to one study and does not expose
workspace selection. These modes are mutually exclusive. Neither launches an
HTTP service or executes generated tools/code.

| Student request | Tool operation | Required behavior |
| --- | --- | --- |
| Show my studies | `list_studies(offset, limit)` | Follow `page.next_offset`; limits are 1–100, and admission scans at most 1,000 immediate entries. |
| Start a new study | `create_study(slug, brief)` | Safe lowercase slug, at most 64 characters, first character a letter; letters, digits, `_` and `-` only; no reserved Windows names. Existing folders are not overwritten. An optional brief is validated/stored and returns its normalized value/hash; call `prepare_study` for the planning prompt and starter bundle. |
| Continue a saved study | `open_study(slug)` | Select only a saved study inside the connected root. Do not switch during collection. |
| Describe my research question | `prepare_study(brief)` | Required for newly authorized inputs after study selection, even if creation supplied a brief. Returns a validated brief, planning contract/prompt and starter bundle; no source or model collection. Do not call it solely to resume an unchanged applied plan. |
| Prepare the inputs | `submit_plan(bundle)` | Save only a valid bounded proposal. Fix validation reports without bypassing the engine. |
| Show proposed websites before fetching | `inspect_plan(plan_sha256, section, offset, length)` | Read complete inert policy/source declarations and ingestion state using the submitted bundle hash; no fetch, freeze, approval or extraction. |
| Show the concrete plan | `prepare_review(fetch_remote)` | Ingest explicit sources, optionally fetch declared URLs, freeze whole-source blank packets and estimate costs. Default fetch is false. No model extraction. |
| Review the entire policy and costs | `inspect_review`, `review_sources`, `review_text` | Recover all pages and clipped fields inside the harness, as described below. |
| I approve that exact plan | `approve_review(review_id, researcher_approved, approval_reference)` | Relay an actual user decision; `researcher_approved` must be true. Recorded declaration is not authenticated human identity. |
| Collect or resume | `collect(review_id, max_jobs)` | Asynchronous, finite, hash-bound run; optional invocation cap leaves remaining jobs pending. |
| Show progress / stop | `status()` / `cancel()` | Report saved status, costs, failures and unfinished work. Sent requests can still finish or have uncertain billing. |
| Find collected data | `records(query, offset, limit)` | Bounded search/page over the complete grounded inventory. |
| Show exact evidence | `inspect_record(record_id, evidence_offset, limit)` / `inspect_source(source_id, offset, length)` | Follow evidence pages and source character ranges; source chunks have a maximum length of 12,000 Unicode code points. |
| Record my judgment | `annotate(...)` | Human relay requires `annotation_origin=human_relay`, explicit user approval and its reference. Model suggestions enter the audit queue and cannot approve or reject records. |
| Undo my annotation | `undo_annotation(annotation_id, researcher_approved, approval_reference)` | Relay the actual user request; keep history and grounded records. |
| Save/export or reproduce a version | `release(name, version_id)` / `versions()` | Local exports, manifest and publication findings. Reuse the release name or saved version to reproduce retained records; a new name freezes changed data. No upload/publication. |

No workspace study is selected initially. Create or open one before its
collection tools. One connection supports multiple saved studies, with one
active collection worker. Never clone/switch a study to evade a budget,
approval, uncertain reservation or protocol boundary.

When preparing new inputs, always call `prepare_study` after `create_study`
or `open_study`, including when creation supplied an optional brief. Creation
does not return the planning prompt or starter bundle. Reopening an unchanged
applied study follows a different path: read `status`, inspect its retained
review, and resume it. Calling `prepare_study` would reset the applied setup
and proposal; it is not a routine resume step.

## Recover the complete review inside the harness

Before fetching URLs, or when `prepare_review` has no ready `review_id`, use
`inspect_plan(plan_sha256, section, offset=0, length=8000)` with the valid
`submit_plan` result's `bundle_sha256`. Sections are `brief`, `recipe`,
`sources`, `sampling`, `evaluation`, `search_log`, `agent`, `validation`, and
`ingestion`. Follow `next_offset` until null, with a maximum chunk length of
12,000 Unicode code points and unchanged `plan_sha256`/`value_sha256` hashes.
Results identify the proposed/applied stage and `inspection_only=true`.
Ingestion distinguishes captured sources from those not captured and retains
historical parsing failures. This is complete proposal inspection, not a
freeze, cost review, permission to fetch or approval to collect. After explicit
authorized retrieval, inspect the ready frozen review before approval.

`prepare_review` and other responses may be marked `preview_only` when they
exceed the transport's finite result bound. Internal IDs can still route calls;
they are not proof that the researcher saw the complete plan. A page may have
selected every item while its nested values are still clipped.

`inspect_review(review_id, section, offset=0, limit=20)` returns bounded
top-level `items`, `section_sha256`, and `page` with `total` and `next_offset`.
Valid sections are:

```text
summary, brief, recipe, profile, sampling, evaluation, search_log, agent,
binding, costs, source_plan, source_provenance, failures, pending_sources, freeze
```

Review every applicable section and follow each page until `next_offset` is
null. `review_sources(review_id, offset=0, limit=10)` returns complete selected
source entries with `index`, `declaration`, `inspection`, and
`source_provenance`, plus the source-plan hash and page cursor. Follow all
source pages; do not assume a count summarizes the selection.

For clipped nested values, use
`review_text(review_id, section, json_pointer="", offset=0, length=8000)`.
The optional RFC6901 pointer addresses a value within that saved section.
For example, `/0/why_selected` within `source_plan` reads the first source's
selection reason. A pointer never opens a file or URL. Empty pointer selects
the entire section. Strings return original text; other values return canonical
JSON. The result includes `text`, `representation`, `start`, `end`,
`total_characters`, `next_offset`, `value_sha256` and `section_sha256`.
Request chunks up to 12,000 characters and continue until `next_offset` is
null. Concatenate only chunks with unchanged hashes. If the review is stale,
stop and prepare its current version before inspection or approval.

The student sees readable inclusion/exclusion rules, model/mode settings,
complete source selection with provenance/problems, dates/rights limitations,
cost assumptions and reserves, hard spending cap, evaluation freeze and
unresolved research decisions. Keep internal JSON and cursors out of the
ordinary product flow. A browser or local file view is optional; neither is
required to finish a complete conversational review.

## Terminal/file fallback without MCP

When the client has local terminal/file tools but no MCP connection, export
the installed instructions into a fresh local directory:

```sh
termfinder agent-skill --out ./v6-collect-research
```

This exports instructions only; it does not register a connection or start
collection. The agent can read the exported skill, manage the inert inputs in
the selected study, and operate the public CLI/API. Do not ask the student to
write dictionaries or transport bundles. Do not misreport a CLI invocation as
a connected MCP call. An ordinary web chat without local tools uses the
separately documented prompt/bundle fallback in the package's
`docs/AGENT_WORKFLOW.md`.

The Python API uses the same deterministic planning gates:

```python
from termfinder import Project
from termfinder.workflow import prepare_review, approve_review, run_review, release_dataset

project = Project("studies/my-study")
setup = project.prepare_agent_setup(brief)  # actual user-authorized finite bounds
validation = project.validate_agent_bundle(bundle)
assert validation["valid"]
review = prepare_review(project, bundle, fetch_remote=False)
# Inspect the complete returned review and retained inputs. Only after the
# researcher's actual approval, relay that decision with its reference:
approval = approve_review(
    project, review["review_id"], approval_origin="agent_relay",
    approval_reference="Reference to the actual approving user message",
)
result = run_review(project, review["review_id"], allow_paid=False)
release = release_dataset(project, "pilot-v1")
```

`brief` and `bundle` are agent-authored dictionaries under the returned
contract, never executable code. `allow_paid=False` permits fake collection
only. Fake is a synthetic rehearsal, not a general local extractor or quality
measurement. A real provider additionally requires explicit authorization and
the selected profile's environment variables. Keep keys out of files, prompts,
URLs, reports, notebook outputs and command arguments.

Use installed `termfinder --help` and subcommand help for exact terminal options.
The guided operations are `review-plan`, `current-review`, `approve-review`,
`run-review`, and `release`; the agent handles returned IDs. The browser's
Plan, Evidence and Dataset tabs are an optional view of these same saved
artifacts. Do not require manual engine changes for ordinary recipes.

## Research and recovery boundaries

The workspace root is a logical tool boundary. Guards reject observed
directory and database replacements, but SQLite and other legacy operations
still open filesystem paths. These checks are not an operating-system sandbox
against malicious concurrent changes by the same user. Use a researcher-owned
workspace and avoid concurrent untrusted writers.

If a task stops at a budget, cancellation, circuit breaker, partial response
or uncertain request, explain the saved state and remaining work. Keep the
collector's finite retry policy and unknown reservations; do not erase jobs,
silently switch models, release reserves or add a second retry loop. Changed
review bindings require a fresh concrete decision. Previously processed text
cannot become newly blind held-out gold through a changed guided plan.

For source-level evaluation, humans independently annotate entire frozen
held-out sources, including eligible spans absent from extraction. Use
`evaluation.validate_gold`/`evaluation.evaluate` or the documented CLI workflow,
source/family grouped splits and the actual human rubric. This planning agent
must not manufacture gold or infer recall from counts or agreement. Archive
original bytes separately for parser replay and confirm source-use rights.

Always separate source observations, generated meanings/translations, model
suggestions and human annotations. Grounding proves occurrence, not semantic
truth, actual coinage, representative sampling or recall. Frozen dataset
exports can be reproduced without model calls; synthetic protocol tests do
not establish usability in a real host or accuracy in a real corpus.
