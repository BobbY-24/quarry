# Researcher acceptance evidence

V6.1 adds the ordinary agent-assisted setup described in
[AGENT_WORKFLOW.md](AGENT_WORKFLOW.md). The final 149-test suite and installed
wheel checks preserve the original term workflow below and add:

| Agent-assisted behavior | Offline evidence |
| --- | --- |
| Start from a data type and plain-language question | The browser creates a scoped brief and complete request/template for the student's own agent; all five publication-inspired briefs validate through installed public APIs. |
| Import one returned bundle | Strict validation, readable plan review and compiled collector files; stale/scope-widening/malformed/secret-bearing inputs receive safe errors and a repair request. |
| Retain exact nonterm data | Installed term/idea/opinion/sentence projects keep original contiguous spans and generated interpretations separately. Nonterm IDs retain source and span. |
| Freeze before candidate exposure | Saved corpus, family splits and blank whole-source packets are prepared before job planning. Late freezing is rejected; outside exposure remains unverifiable. |
| Inspect publication lineage | Frozen audit checks evidence/source/job/plan joins and event hashes, detects inconsistent artifacts, and flags missing archives, rights and unfinished work for review. |
| Reproduce releases | All four installed type rehearsals pause/reopen/resume, undo annotations and export each frozen version twice with byte-identical files. |

See [VERIFIED.md](VERIFIED.md) for completed checks and preserved reports.
Scripted bundles and fake-provider replies do not verify a real external-agent
round trip, source selection quality, semantic correctness or research recall.

The offline demo and `tests/test_acceptance.py` exercise a complete researcher
workflow using synthetic local sources and a fake provider. A successful run
writes `acceptance_report.json`, per-project status/estimate/evaluation reports,
complete-source labels, and immutable exports. The verification launcher adds
sandbox probes and reviewed-file hashes. These are software checks, not a claim
of measured quality on real sources.

| Required handoff behavior | Offline evidence |
| --- | --- |
| Customize all three starters | Each recipe validates and is configured into an independent project; editable examples, typed attributes, dates, scope and budgets are saved. |
| Broad and Specialists on the same fixtures | Six projects run the same HTML, Markdown, text and two-page PDF corpus with literal source communities; Specialists adds matching lenses. |
| Preserve terms, distinct senses and singletons | Both `anchor` sense hypotheses survive; GLM-only `moonstep` and DeepSeek-only `quietstack` survive in the union. |
| Inspect evidence | Every occurrence's half-open Unicode slice equals its original expression; exact contexts occur in frozen text; multilingual scripts, emoji and decomposed accents are exercised. |
| Preserve page locations | The synthetic PDF has two pages and source blocks identify both. |
| Reverse annotation/merge operations | A rejected annotation leaves the term in inventory; undo restores unreviewed status; an alias link is undone with original records retained. |
| Stop and resume | One job runs, remaining jobs stay pending, a new `Project` instance resumes, and completed jobs do not repeat calls. Core fault tests additionally cover interrupted running jobs/uncertain outcomes. |
| Show budgets and failures | A nonzero simulated-rate profile with a tiny monetary limit stops before fake dispatch and leaves pending work; malformed PDF remains a parsing failure in every frozen dataset. |
| Bound discovery and retain lineage | Explicit static search plus a synthetic fetcher rejects outside scope, records parent/query decisions, reaches a finite source/request limit and preserves pending URLs. |
| Reproduce saved dataset versions | Two exports have identical file hashes after a later annotation; both provider methods are patched to fail if export calls them. The full demo requests CSV, JSONL, Parquet and annotation bundles. |
| Measure missed terms from complete sources | Independent manually specified fixture labels include contextual mentions not returned by the fake provider; evaluation reports their false negatives by domain/language. |
| Run independently of V5 | The packaged API and resources have no sibling imports. The isolated installed-wheel check verifies startup and packaged fixtures without sibling/source `PYTHONPATH`. |

The generated report records counts to verify that records persist. Those counts
and model support patterns do not estimate recall. Source-use constraints,
unavailable-value reasons, coverage, failures, costs, profiles, recipes and prompt
versions accompany each snapshot/export manifest.

See the handoff verification results for the actual test count, full-export demo
results, installed-wheel outcome, and notebook execution status. See
`docs/PILOT.md` for the remaining field evaluation and explicit authorization
needed before real provider requests, data collection or publication.
