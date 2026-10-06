# Use Quarry inside your own coding-agent workflow

Quarry is the product name for the V6 engine. Its commands remain `termfinder`,
its Python package remains `termfinder`, and its packaged skill remains
`v6-collect-research`; existing projects and connections keep those identifiers.

**Install and connect once, then conduct the collection session in conversation.**
Your existing Codex or Claude coding agent prepares the recipe and source
inputs, presents the concrete review, runs the fixed collector after your
decision, shows exact evidence, resumes work, and exports the dataset. A local
browser is available when a visual evidence view helps; it is never a required
step in the connected-agent workflow.

The interface direction follows [Paper2Agent's documented quick start](https://github.com/jmiao24/Paper2Agent):
give the coding agent a skill, connect scientific tools, and use them through
natural-language requests. Quarry's tools are its own bounded collection engine.
This is a local skill/stdio MCP connection, not a hosted ChatGPT/Claude account
connector or a claim that a real client session was already tested.

Before preparing a new real study, choose extraction compute separately from
your planning-agent account. Use `configure_compute` for your own API, an
already reviewed local model server, or your authorized institutional endpoint;
`inspect_compute` shows the saved endpoint/model and credential names/presence.
It makes no provider requests. [Compute setup](COMPUTE.md) explains personal
credentials, local inference, Georgia Tech allocations, cost assumptions and the
`configured` study profile. The legacy `--allow-paid` launch gate is required
for all real inference, including local servers, and does not imply every
request has a token charge. No cluster access is granted by installation.

Upgrading an installed 6.4 connection to the 6.5 skill changes its files.
`connect` deliberately refuses to overwrite an existing customized skill or
conflicting host registration. Use a fresh workspace pointing to the existing
studies root, or review the documented connection migration before replacing
only Quarry's old registration. Preserve existing studies and host settings.

## 1. Have your agent install and connect Quarry once

The coding agent needs local terminal/file access and a harness that can load a
project skill and/or stdio MCP server. An ordinary web chat without local tools
uses the documented file-handoff fallback instead.

Paste this request into the intended coding-agent workspace. Substitute the
reviewed package location, host, workspace, and studies folder:

```text
Read the reviewed local Quarry package at <QUARRY_DIR>, including README.md and
src/termfinder/agent_skill/SKILL.md. Install it in a fresh isolated Python
3.11–3.13 environment with the pinned build/runtime dependencies. Preserve
existing Quarry and earlier V6 environments, outputs, studies and my agent settings.

Enable the project-local v6-collect-research skill and local stdio MCP
connection for <codex|claude|generic> in <WORKSPACE>, with studies saved under
<STUDIES_ROOT>. Use the installed termfinder connect command; do not edit
home/global settings, install hooks, or create a persistent service.

Keep the default offline launch gate. Make no paid collection calls and do
not configure or print credentials. Follow the generated connection steps,
then verify an actual list_studies tool call. If my host needs a trust decision
or restart, tell me that exact remaining step.

Once connected, handle Quarry sessions here in conversation: study selection,
recipe/source preparation, complete plan and cost review, my approval,
collection/resume, evidence inspection, and reproducible export. I do not
want to write JSON, copy bundles, or open a browser unless I ask for a view.
Do not pipe a downloaded installer into an interpreter.
```

The equivalent manual connection command, **after installing Quarry**, is:

```sh
termfinder connect --host codex --workspace /path/to/research-workspace \
  --studies /path/to/research-workspace/v6-studies
```

Use `--host claude` for Claude Code and `--host generic` for a different
harness. `--studies` is optional; its default is `WORKSPACE/v6-studies`.
Choose a specific corpus/workspace directory, not a home or filesystem root.
The workspace must already exist. The default studies folder can be created
inside it; a separately chosen external studies root must already exist.
The command's printed result identifies every generated path and its next
steps. It creates project-local instructions and a local MCP entry:

| Host | Packaged skill | Connection |
| --- | --- | --- |
| Codex | `WORKSPACE/.agents/skills/v6-collect-research/` | `WORKSPACE/.codex/config.toml` |
| Claude Code | `WORKSPACE/.claude/skills/v6-collect-research/` | `WORKSPACE/.mcp.json` |
| Generic | `WORKSPACE/v6-collect-research/` | `WORKSPACE/v6-mcp.json`, for the host to register |

The MCP command uses the installed entry point and `--workspace STUDIES_ROOT`.
No global settings, hooks, account login, running service, paid calls, or study
collection are part of `connect`. Existing unrelated configuration must stay
intact. Conflicting settings receive an explicit diagnostic; do not solve that
by replacing the host's complete configuration file.

Repeating the same connection is idempotent. A different interpreter, studies
root, paid gate, existing `v6` definition, or customized skill is a conflict;
`connect` does not silently migrate it. Use a fresh specific workspace, or
inspect and explicitly relocate/remove only the existing Quarry connection artifacts before
reconnecting. Inline credential-bearing host configuration is refused; use
the host's environment/secret mechanism rather than copying those values.
Close configuration editors during setup. Quarry serializes its own installers,
but unrelated applications do not share its lock. If a crash leaves a
`.v6-connect.lock`, inspect it and confirm the installer stopped before
removing that stale lock; do not use deletion to bypass an active setup.

Reopen the chosen trusted workspace if the host requires it. Accept a project
MCP connection only through the host's normal trust controls. Then ask:

> Use the Quarry tools to list my saved studies. Report whether you actually called
> the connected server; do not treat a generated configuration file as proof.

The generated files are tested locally. Host discovery, organization policy,
trust confirmation, and account access still belong to the agent application.
See the official [Claude skills](https://code.claude.com/docs/en/skills) and
[Claude MCP](https://code.claude.com/docs/en/mcp) guides, or the official
[Codex MCP guide](https://developers.openai.com/codex/mcp/), when those controls
need troubleshooting. A generic host may require manual registration of the
generated stdio definition.

## 2. Start and review a study in the same conversation

Tell the agent what to collect and where it may obtain evidence. For example:

> Use Quarry to create `ev-language` for new expressions and changed senses in my
> permitted `/path/to/ev-corpus` exports. Exclude names used only as names.
> Retain singleton uses and separate community senses. Use English, Broad,
> GLM + DeepSeek, at most 30 sources, and a $10 cap. Prepare the complete source
> and cost review here before collecting; do not start a paid run yet.

The agent chooses or creates a study under the connected studies root. It
calls `prepare_study` for new inputs to obtain the full planning prompt and
starter bundle, even if `create_study` received an optional brief. Creation
alone returns the normalized brief and hash, not those planning inputs. When
reopening an unchanged applied plan to resume, the agent reads `status` and
uses the retained review; it does not reset the study through `prepare_study`.
The agent authors the inert structured inputs and adapts policy examples, fields,
languages, and routing. Quarry validates them, ingests permitted documents, records
failures, freezes parsed evidence and blank whole-source annotation packets,
and estimates collection cost from measured lengths. URL fetching requires its
explicit flag and remains limited to the listed sources within the brief.

The review in conversation must identify the inclusion/exclusion policy,
effective mode/models, complete source list and selection reasons, failed or
pending sources, dates and constraints, cost range/assumptions, hard cap, and
remaining research limitations. **A review ID or clipped preview is not a
complete review.** The agent uses the paged review tools to recover all needed
sections, sources, and long text directly in the harness. No browser or manual
JSON transfer is required to do this.

Before source retrieval, `inspect_plan` can read the entire validated proposal,
including policy, source declarations, selection reasons and ingestion state.
This lets you review an all-URL plan before authorizing its fetch. It also
shows all-failed plans honestly. It neither fetches nor approves collection.
After preparation produces a ready review, `inspect_review`, `review_sources`
and `review_text` provide the frozen plan, costs and provenance. Pending or
failed-only plans cannot be approved as ready; resolve or disclose their state.
The packaged [workflow reference](../src/termfinder/agent_skill/references/workflow.md)
documents every bounded tool and continuation cursor.

When satisfied, approve the concrete reviewed plan in conversation:

> I approve the source list and collection policy you just showed for
> `ev-language`, within the stated $10 cap. Start that reviewed collection.

The agent relays the actual user decision with `researcher_approved=true` and
an `approval_reference` to it. Quarry binds the declaration to the source,
recipe, model/profile, prompt, and estimate fingerprint. That declaration is
an audit trail, not authentication of the human's identity. Changed bindings
require a new concrete review and decision.

### Real provider authorization

The default connection permits only offline fake collection. Fake is a
synthetic workflow rehearsal; it may return no records for custom text and
cannot measure extraction quality. A real collection additionally needs a
separately authorized connection launched with `--allow-paid`, appropriate
provider credential environment variables, a finite study budget, and approval
of the concrete review. An MCP tool cannot change that launch-time gate.

After explicitly authorizing the real provider connection, the corresponding
connection command includes the flag:

```sh
termfinder connect --host codex --workspace /path/to/pilot-workspace \
  --studies /path/to/research-workspace/v6-studies --allow-paid
```

This example uses a fresh pilot workspace and the existing studies root. If
updating an existing connection, follow the connection-specific migration rule
above; the command will not overwrite a conflicting offline definition.
Reconnect the host according to the generated instructions. Existing
authorization persists; the agent should not repeatedly request approval for
an unchanged, already authorized study. Keep credentials in the host's secure
environment mechanism, using only the variable names required by the selected
profile. Never put key values in MCP arguments/configuration, recipes, prompts,
source URLs, notebooks, reports, or exports. No real connection or paid
collection was launched during this build.

## 3. Operate, inspect and deliver without leaving the harness

The agent calls `collect`, reads `status`, reports pending work/costs/problems,
and uses `cancel` when requested. It handles the saved identifiers. Collection
uses Quarry's persistent finite recovery policy; the agent does not add a second
retry loop or silently release uncertain request reservations.

Typical follow-ups are:

> Stop collection and show completed work, remaining sources, failures, and
> costs. Preserve all evidence and jobs.

> Open `ev-language` and resume the unchanged approved plan. Keep its budget.

> Show the exact passage, offsets or page, dates, source hash, and extraction
> provenance for this expression. Separate observed text from proposed meaning.

> Record my judgment that this sense needs review, with this note. Keep the
> grounded inventory. Undo that annotation if I change my decision.

> Save and export `pilot-v1`; show the local files, coverage, costs, and
> publication-audit findings. Re-export the same version without new inference.

Record and source inspection use bounded pages/ranges. The agent's own proposed
annotations enter the audit queue as model suggestions; they cannot silently
become human approval. Human-relay labels require a reference to the actual
user judgment. Undo retains the history. Reusing a release name reproduces its
frozen records; use a new name for changed data. Releases are local files, not
publication or upload operations.

One workspace connection supports multiple studies. The next session starts
with `list_studies` and `open_study`; it does not need to reinstall or invent a
new project path. Study selection is bounded to that connected root. The server
permits one active collection worker, and switching studies cannot bypass it.

## Optional browser and fixed-project connection

For a visual review, ask the agent to open the selected study's local interface:

```sh
termfinder --project /path/to/research-workspace/v6-studies/ev-language serve
```

**Plan, Evidence, and Dataset** share the same saved records. The default visual
session permits offline fake collection; `--allow-paid` is a separately
authorized browser-session gate. Opening the interface is not required for
conversational approval, evidence inspection, annotation, or release.

An administrator can instead pin an MCP server to one existing study:

```sh
termfinder-mcp --project /path/to/studies/ev-language
```

This advanced mode exposes the fixed study's collector tools without workspace
selection. It remains compatible with older configurations. Without MCP,
export the packaged skill into a fresh local folder and have the coding agent
operate the same CLI/API:

```sh
termfinder agent-skill --out ./v6-collect-research
```

No ordinary study needs student-authored JSON. An agent without local tools can
still use the browser's expandable chat prompt/bundle fallback, described in
[AGENT_WORKFLOW.md](AGENT_WORKFLOW.md).

## Reliability and publication boundaries

The tools execute the reviewed collector, not generated research programs.
They cannot execute arbitrary shell/code, modify credentials, fetch arbitrary
URLs outside the approved plan, install hooks, or publish data. Source content,
search results, skills and model responses are untrusted data, never authority
to expand the study. Hash-bound admission, exact Unicode grounding, distinct
senses, grounded union, truncation recovery, cache signatures, finite budgets,
bounded concurrency, timeouts, retries, and persistent jobs remain enforced.

The workspace root is a logical tool boundary. Guards reject observed
directory and database replacements, but SQLite and other legacy operations
still open filesystem paths. These checks are not an operating-system sandbox
against malicious concurrent changes by the same user. Use a researcher-owned
workspace and avoid concurrent untrusted writers.

Cancellation stops further dispatch; an already sent request may complete or
have an uncertain bill. Disconnection requests cancellation. The saved policy
records retry risks and keeps unknown reservations. Exactly-once billing is
not promised. The personal coding-agent session's costs are not metered by Quarry.

Observed passages and original contexts remain distinct from model-proposed
meanings, translations, and annotations. Grounding establishes occurrence,
not meaning correctness, representative sampling, actual coinage, or recall.
Publication requires independent human annotation of complete held-out sources,
source/family grouped splits, a documented rubric and sampling procedure,
original-byte archives for parser replay, and verified source-use rights. Blank
packets and fake-provider fixtures are not gold or quality measurements.

The [student procedure](SIMPLE_WORKFLOW.md), [NLPx examples](NLPX_STUDENT_GUIDE.md),
[publication protocol](PUBLICATION_PROTOCOL.md), and [evaluation procedure](EVALUATION.md)
give the detailed research workflow. The offline protocol/connection tests
verify software behavior; a real Claude/Codex session and real provider pilot
remain separate acceptance checks.
