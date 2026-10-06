"""Packaged researcher CLI. Network model calls require --allow-paid."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str, allow_nan=False))


def _recipe(value):
    from .config import load_recipe, starter_recipe
    return starter_recipe(value) if value in {"neologisms", "cultural", "jargon"} else load_recipe(Path(value))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="termfinder", description="Quarry: research collection with durable evidence, resume, and frozen datasets")
    p.add_argument("--project", default=".", help="Project directory containing project.sqlite3 (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Configure a project from a validated starter recipe or JSON file")
    init.add_argument("path", nargs="?", help="New or existing project directory")
    init.add_argument("--recipe", default="neologisms", help="neologisms, cultural, jargon, or recipe JSON path")
    init.add_argument("--profile", default="fake", help="fake, glm-deepseek, gemini, or profile JSON path")
    init.add_argument("--mode", choices=("broad", "specialists"))
    compute = sub.add_parser("configure-compute", help="Configure your own API, local model, or institutional endpoint; no network requests")
    compute.add_argument("--backend", choices=("api", "local", "institutional"), required=True)
    compute.add_argument("--preset", choices=("glm-deepseek", "gemini"), help="Packaged API routing and rates; reads only the configured environment-variable names")
    compute.add_argument("--base-url", help="OpenAI-compatible endpoint; no credentials or query parameters")
    compute.add_argument("--model", help="Exact served model identifier for a custom endpoint")
    compute.add_argument("--model-version", help="Pinned model/revision declaration for reproducible provenance")
    compute.add_argument("--credential-env", help="Credential environment-variable NAME only; never supply a key value")
    compute.add_argument("--input-per-million", type=float, help="USD per million input tokens")
    compute.add_argument("--output-per-million", type=float, help="USD per million output tokens")
    compute.add_argument("--context-limit-tokens", type=int, default=32768)
    compute.add_argument("--max-output-tokens", type=int, default=8192)
    compute.add_argument("--response-format", choices=("json_object", "none"), default="json_object", help="Use none if the custom server does not support the response_format parameter")
    compute.add_argument("--runtime-manifest", type=Path, help="Reviewed runtime/checkpoint declaration JSON; no model code, credentials or downloads")
    compute.add_argument("--configuration-reference", default="researcher local configuration", help="Brief reference to the researcher's compute choice, containing no credentials")
    sub.add_parser("compute", help="Inspect effective model routing, credential names/presence, and cost basis without network requests")
    cluster = sub.add_parser("configure-cluster", help="Save an inert reviewed Slurm site profile; no submission or model launch")
    cluster.add_argument("profile", type=Path)
    throughput = sub.add_parser("tune-cluster", help="Set bounded request concurrency before jobs; preserve policy and budgets and require a fresh review")
    throughput.add_argument("--concurrency", type=int, default=4)
    throughput.add_argument("--model-concurrency", type=int, default=4)
    throughput.add_argument("--configuration-reference", default="researcher CLI operator tuning")
    cluster_review = sub.add_parser("cluster-review", help="Freeze a portable job bundle and review resource limits for an approved collection")
    cluster_review.add_argument("review_id")
    for name in ("cluster-submit", "cluster-resume"):
        batch = sub.add_parser(name, help="Submit a concrete reviewed Slurm allocation with finite cumulative limits")
        batch.add_argument("cluster_review_id")
        batch.add_argument("--researcher-approved", action="store_true", help="Declare the human decision about this concrete resource request")
        batch.add_argument("--approval-reference", required=True, help="Bounded decision reference; never credentials")
        batch.add_argument("--allow-cluster", action="store_true", help="Explicit scheduler execution permission")
        batch.add_argument("--allow-paid", action="store_true", help="Permit the reviewed nonfake extraction endpoint, including self-hosted models")
    batch_status = sub.add_parser("cluster-status", help="Read durable job receipts, reservations and checkpoints")
    batch_status.add_argument("--job-id")
    batch_status.add_argument("--refresh-scheduler", action="store_true")
    batch_status.add_argument("--allow-cluster", action="store_true")
    batch_cancel = sub.add_parser("cluster-cancel", help="Cancel a known scheduler job and preserve its checkpoint")
    batch_cancel.add_argument("job_id")
    batch_cancel.add_argument("--allow-cluster", action="store_true")
    reconcile = sub.add_parser("cluster-resolve", help="Record manual reconciliation of an unknown scheduler submission")
    reconcile.add_argument("job_id")
    resolution = reconcile.add_mutually_exclusive_group(required=True)
    resolution.add_argument("--scheduler-job-id")
    resolution.add_argument("--verified-absent", action="store_true")
    reconcile.add_argument("--reconciliation-reference", required=True)
    reconcile.add_argument("--allow-cluster", action="store_true")
    batch_import = sub.add_parser("cluster-import", help="Import a validated checkpoint into its unchanged origin; no model calls")
    batch_import.add_argument("--job-id")
    recipe = sub.add_parser("recipe", help="Write a complete starter recipe for researcher editing")
    recipe.add_argument("name", choices=("neologisms", "cultural", "jargon"))
    recipe.add_argument("--out", type=Path)
    prepare = sub.add_parser("prepare-agent", help="Describe a study and generate a request for your own ChatGPT/Claude agent")
    description = prepare.add_mutually_exclusive_group(required=True)
    description.add_argument("--brief", type=Path, help="Research brief JSON (optional alternative to plain-language flags)")
    description.add_argument("--idea", help="Your plain-language research question")
    prepare.add_argument("--data-type", choices=("term", "idea", "opinion", "sentence"), default="term")
    prepare.add_argument("--policy", choices=("neologisms", "cultural", "jargon"))
    prepare.add_argument("--include", action="append", default=[])
    prepare.add_argument("--exclude", action="append", default=[])
    prepare.add_argument("--language", action="append", default=[])
    prepare.add_argument("--community", action="append", default=[])
    prepare.add_argument("--domain", action="append", default=[])
    prepare.add_argument("--local-root", action="append", default=[])
    prepare.add_argument("--budget", type=float, default=0)
    prepare.add_argument("--max-sources", type=int, default=30)
    prepare.add_argument("--mode", choices=("broad", "specialists"), default="broad")
    prepare.add_argument("--profile", choices=("glm-deepseek", "gemini", "fake", "configured"), help="Defaults to your configured compute, or glm-deepseek before configuration")
    prepare.add_argument("--out", type=Path, required=True, help="Fresh handoff directory")
    validate = sub.add_parser("validate-plan", help="Check the agent's bundle without collection or source fetching")
    validate.add_argument("bundle", type=Path)
    validate.add_argument("--out", type=Path)
    apply = sub.add_parser("apply-plan", help="Review/apply a validated plan; ingest approved local files and stage URLs")
    apply.add_argument("bundle", type=Path)
    sub.add_parser("ingest-plan", help="Explicitly fetch only the sources in the applied plan; no model calls")
    freeze = sub.add_parser("freeze-corpus", help="Freeze the applied source plan and prepare blind full-source human review")
    freeze.add_argument("--name", default="corpus-v1")
    freeze.add_argument("--seed", default="v6-agent-study-v1")
    audit = sub.add_parser("publication-audit", help="Check frozen evidence/plan integrity and list research limitations")
    audit.add_argument("version")
    audit.add_argument("--out", type=Path)
    ingest = sub.add_parser("ingest", help="Ingest local HTML/text/Markdown/PDF and scoped URLs")
    ingest.add_argument("paths", nargs="*")
    ingest.add_argument("--url", action="append", default=[])
    ingest.add_argument("--url-list", type=Path)
    ingest.add_argument("--metadata", type=Path, help="JSON source metadata; dates, language, community, domain, constraints")
    estimate = sub.add_parser("estimate", help="Estimate stage costs from inventory or uncertain link count")
    estimate.add_argument("--links", type=int)
    estimate.add_argument("--average-chars", type=int)
    estimate.add_argument("--cache-hit-rate", type=float)
    for command in ("collect", "resume"):
        run = sub.add_parser(command, help="Run pending extraction jobs; interrupted/failed/budget work stays visible")
        group = run.add_mutually_exclusive_group()
        group.add_argument("--offline", action="store_true", help="Use deterministic FakeProvider for an offline demonstration")
        group.add_argument("--allow-paid", action="store_true", help="Explicitly authorize configured provider API calls for this command")
        run.add_argument("--max-jobs", type=int, help="Bound work in this invocation, leaving remaining jobs pending")
    sub.add_parser("status", help="Show progress, coverage, failures, and actual costs")
    sub.add_parser("cancel", help="Request durable cancellation; resume can process remaining work")
    sub.add_parser("large-run", help="Upgrade execution caps/backoff for an existing project; preserve spending and source scope")
    reset = sub.add_parser("reset-model", help="Explicitly re-enable a disabled model after resolving its outage/configuration")
    reset.add_argument("model_alias")
    backup = sub.add_parser("backup", help="Create a consistent WAL-aware local SQLite backup, including saved versions")
    backup.add_argument("out",type=Path)
    retry = sub.add_parser("retry-job", help="Return a failed or unresolved partial job to pending")
    retry.add_argument("job_id")
    uncertain = sub.add_parser("resolve-uncertain", help="Resolve an unknown API outcome; unknown reserves stay in budget")
    uncertain.add_argument("job_id")
    uncertain.add_argument("--retry", action="store_true", help="Make another request; the previous call may have been billed")
    uncertain.add_argument("--acknowledge-possible-duplicate-billing", action="store_true", help="Explicitly acknowledge that a retry can duplicate provider billing")
    sub.add_parser("versions", help="List saved immutable dataset versions")
    guided = sub.add_parser("review-plan", help="Prepare sources, freeze blind packets and estimate a checked plan in one operation")
    guided.add_argument("--bundle", type=Path, help="Optional validated agent plan; use the current applied plan when omitted")
    guided.add_argument("--fetch-reviewed-websites", action="store_true", help="Explicitly fetch URLs in the reviewed plan")
    sub.add_parser("current-review", help="Show the saved collection review and whether its approval is current")
    approval = sub.add_parser("approve-review", help="Record explicit approval of the concrete saved plan, corpus and finite budget")
    approval.add_argument("review_id")
    run = sub.add_parser("run-review", help="Collect or resume within a current approved source review")
    run.add_argument("review_id")
    run.add_argument("--offline", action="store_true", help="Use the fake fixture provider for an offline rehearsal")
    run.add_argument("--allow-paid", action="store_true", help="Authorize configured provider requests for this invocation")
    run.add_argument("--max-jobs", type=int, help="Optional finite interruption checkpoint")
    release = sub.add_parser("release", help="Save, audit and export a dataset in one operation, or re-export an existing version")
    release.add_argument("name", nargs="?", default="research-release")
    release.add_argument("--version", help="Existing saved dataset version to re-export without model calls")
    release.add_argument("--formats", default="csv,jsonl,parquet,annotation")
    skill = sub.add_parser("agent-skill", help="Copy the packaged Quarry collector skill to a fresh directory; never install globally")
    skill.add_argument("--out", type=Path, required=True)
    connect = sub.add_parser("connect", help="Install the Quarry skill and tool connection in your chosen agent workspace")
    connect.add_argument("--host", choices=("codex", "claude", "generic"), required=True,
                         help="Project-local host configuration, or a generic connection bundle")
    connect.add_argument("--workspace", type=Path, required=True,
                         help="Your existing analysis workspace; no global or home-directory installation")
    connect.add_argument("--studies", type=Path,
                         help="Bounded study directory; defaults to WORKSPACE/v6-studies")
    connect.add_argument("--allow-paid", action="store_true",
                         help="Permit separately approved finite collection runs in this connection")
    connect.add_argument("--allow-cluster", action="store_true", help="Permit separately reviewed bounded scheduler operations")
    connect.add_argument("--cluster-storage-root", action="append", type=Path, default=[], help="Specific existing approved durable cluster storage directory")
    mcp = sub.add_parser("mcp", help="Serve bounded collector tools over local standard input/output")
    mcp.add_argument("--workspace", type=Path,
                     help="Use one bounded study workspace instead of a single --project")
    mcp.add_argument("--allow-paid", action="store_true", help="Permit explicitly approved provider calls in this server session")
    mcp.add_argument("--allow-cluster", action="store_true", help="Permit separately reviewed bounded scheduler operations")
    mcp.add_argument("--cluster-storage-root", action="append", type=Path, default=[], help="Specific existing approved durable cluster storage directory")
    inspect = sub.add_parser("inspect", help="Inspect full inventory or selected term/source evidence")
    inspect.add_argument("--term")
    inspect.add_argument("--record", help="Inspect a typed collected record and its source evidence")
    inspect.add_argument("--source")
    annotate = sub.add_parser("annotate", help="Append a reversible human annotation without removing grounded terms")
    annotate.add_argument("term_id")
    annotate.add_argument("status", choices=("unreviewed", "approved", "rejected", "needs_review"))
    annotate.add_argument("--note", default="")
    annotate.add_argument("--attributes", type=Path, help="JSON human attributes")
    annotate.add_argument("--actor", default="researcher")
    undo = sub.add_parser("undo-annotation", help="Undo one annotation by ID, retaining history")
    undo.add_argument("annotation_id")
    relate = sub.add_parser("relate", help="Append a reversible alias/semantic relation")
    relate.add_argument("term_a")
    relate.add_argument("term_b")
    relate.add_argument("kind", choices=("alias", "semantic_merge", "distinct_sense"))
    relate.add_argument("--actor", default="researcher")
    unrelate = sub.add_parser("undo-relation")
    unrelate.add_argument("relation_id")
    snapshot = sub.add_parser("snapshot", help="Freeze records/config/provenance for reproducible exports")
    snapshot.add_argument("name")
    export = sub.add_parser("export", help="Export a frozen dataset without model calls")
    export.add_argument("version")
    export.add_argument("out", type=Path)
    export.add_argument("--formats", default="csv,jsonl,parquet,annotation")
    discover = sub.add_parser("discover", help="Bounded explicit search/fetch using recipe limits")
    discover.add_argument("--seed", action="append", default=[])
    discover.add_argument("--manifest", type=Path, help="Offline explicit search-result JSON manifest")
    discover.add_argument("--local-root", type=Path, help="Explicitly authorize local discovery files under this root; default is manifest's directory")
    discover.add_argument("--resume", action="store_true", help="Resume saved pending discovery within remaining campaign limits")
    evaluate = sub.add_parser("evaluate", help="Measure precision, recall, and FNs from complete held-out source labels")
    evaluate.add_argument("version")
    evaluate.add_argument("gold", type=Path)
    evaluate.add_argument("--unit", choices=("occurrence", "source_term"), default="occurrence")
    evaluate.add_argument("--require-sense", action="store_true")
    evaluate.add_argument("--split-manifest", type=Path, help="Frozen source/group split manifest; validates test-source coverage")
    evaluate.add_argument("--out", type=Path)
    splits = sub.add_parser("split", help="Create deterministic source/group splits before recipe tuning")
    splits.add_argument("version")
    splits.add_argument("--seed", default="termfinder-v1")
    splits.add_argument("--group-field")
    splits.add_argument("--out", type=Path, required=True)
    serve = sub.add_parser("serve", help="Start loopback browser UI, with per-session authenticated mutations")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-paid", action="store_true", help="Authorize configured provider API calls initiated in this browser session")
    return p


def _write_or_print(value, path):
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _json(value)


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "recipe":
            _write_or_print(_recipe(args.name), args.out)
            return 0
        if args.command == "agent-skill":
            from .mcp_server import write_skill
            _json(write_skill(args.out))
            return 0
        if args.command == "connect":
            from .harness import connect_harness
            _json(connect_harness(args.host, args.workspace, args.studies,
                                  allow_paid=args.allow_paid, allow_cluster=args.allow_cluster,
                                  cluster_storage_roots=args.cluster_storage_root))
            return 0
        if args.command == "mcp":
            from .mcp_server import main as mcp_main
            if args.workspace and args.project != ".":
                raise ValueError("Choose --workspace or --project for the MCP connection")
            mode = ["--workspace", str(args.workspace)] if args.workspace else ["--project", args.project]
            roots = [part for root in args.cluster_storage_root for part in ("--cluster-storage-root", str(root))]
            return mcp_main(mode + (["--allow-paid"] if args.allow_paid else []) + (["--allow-cluster"] if args.allow_cluster else []) + roots)
        from .project import Project
        project = Project(args.path if args.command == "init" and args.path else args.project)
        command = args.command
        if command == "prepare-agent":
            from .agent_setup import write_handoff
            from .config import read_json
            if args.brief:
                brief = read_json(args.brief)
            else:
                brief = {"data_type": args.data_type, "research_question": args.idea,
                         "domains": args.domain, "local_roots": args.local_root,
                         "budget_usd": args.budget, "max_sources": args.max_sources,
                         "mode": args.mode}
                if args.profile is not None:
                    brief["model_profile"] = args.profile
                for key, value in (("inclusion_criteria", args.include), ("exclusion_criteria", args.exclude),
                                   ("languages", args.language), ("communities", args.community)):
                    if value:
                        brief[key] = value
                if args.policy:
                    brief["starter_recipe"] = args.policy
            result = write_handoff(project.prepare_agent_setup(brief), args.out)
        elif command == "configure-compute":
            from .config import read_json
            result = project.configure_compute(backend=args.backend, preset=args.preset,
                base_url=args.base_url, model=args.model, model_version=args.model_version,
                credential_env=args.credential_env, input_per_million=args.input_per_million,
                output_per_million=args.output_per_million,
                context_limit_tokens=args.context_limit_tokens,
                max_output_tokens=args.max_output_tokens, response_format=args.response_format,
                runtime=read_json(args.runtime_manifest) if args.runtime_manifest else None,
                configuration_reference=args.configuration_reference)
        elif command == "compute":
            result = project.compute()
        elif command == "configure-cluster":
            from .config import read_json
            result = project.configure_cluster(read_json(args.profile))
        elif command == "tune-cluster":
            result = project.configure_cluster_throughput(concurrency=args.concurrency,
                model_concurrency=args.model_concurrency, configuration_reference=args.configuration_reference)
        elif command == "cluster-review":
            result = project.cluster().prepare(args.review_id)
        elif command in {"cluster-submit", "cluster-resume"}:
            method = project.cluster().submit if command == "cluster-submit" else project.cluster().resume
            result = method(args.cluster_review_id, human_approved=args.researcher_approved,
                approval_reference=args.approval_reference, allow_execution=args.allow_cluster, allow_paid=args.allow_paid)
        elif command == "cluster-status":
            if args.refresh_scheduler and not args.allow_cluster:
                raise ValueError("Scheduler refresh requires --allow-cluster")
            result = project.cluster().status(args.job_id, refresh=args.refresh_scheduler)
        elif command == "cluster-cancel":
            if not args.allow_cluster:
                raise ValueError("Scheduler cancellation requires --allow-cluster")
            result = project.cluster().cancel(args.job_id)
        elif command == "cluster-resolve":
            if not args.allow_cluster:
                raise ValueError("Scheduler reconciliation requires --allow-cluster")
            result = project.cluster().resolve_submission(args.job_id, scheduler_job_id=args.scheduler_job_id,
                verified_absent=args.verified_absent, reconciliation_reference=args.reconciliation_reference)
        elif command == "cluster-import":
            result = project.cluster().import_result(args.job_id)
        elif command == "validate-plan":
            from .config import read_json
            result = project.validate_agent_bundle(read_json(args.bundle))
            _write_or_print(result, args.out)
            return 0 if result["valid"] else 2
        elif command == "apply-plan":
            from .config import read_json
            result = project.apply_agent_bundle(read_json(args.bundle))
        elif command == "ingest-plan":
            result = project.ingest_agent_sources()
        elif command == "freeze-corpus":
            result = project.freeze_agent_corpus(args.name, args.seed)
        elif command == "publication-audit":
            result = project.publication_audit(args.version)
            _write_or_print(result, args.out)
            return 0 if result["integrity_passed"] else 2
        elif command == "review-plan":
            from .config import read_json
            from .workflow import prepare_review
            result = prepare_review(project, read_json(args.bundle) if args.bundle else None,
                                    fetch_remote=args.fetch_reviewed_websites)
        elif command == "current-review":
            from .workflow import current_review
            result = current_review(project)
        elif command == "approve-review":
            from .workflow import approve_review
            result = approve_review(project, args.review_id)
        elif command == "run-review":
            from .workflow import run_review
            provider = None
            if args.offline:
                from .providers import FakeProvider
                provider = FakeProvider()
            result = run_review(project, args.review_id, provider=provider,
                                allow_paid=args.allow_paid, max_jobs=args.max_jobs)
        elif command == "release":
            from .workflow import release_dataset
            result = release_dataset(project, args.name, formats=args.formats.split(","), version_id=args.version)
        elif command == "init":
            recipe = _recipe(args.recipe)
            if args.mode:
                recipe["mode"] = args.mode
            result = project.configure(recipe, args.profile)
        elif command == "ingest":
            urls = list(args.url)
            if args.url_list:
                urls.extend(line.strip() for line in args.url_list.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#"))
            if not args.paths and not urls:
                raise ValueError("Ingest requires local paths, --url, or --url-list")
            metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else None
            result = {"source_ids": project.ingest(paths=args.paths, urls=urls, metadata=metadata)}
        elif command == "estimate":
            assumptions = {}
            if args.average_chars is not None:
                assumptions["average_chars"] = args.average_chars
            if args.cache_hit_rate is not None:
                assumptions["cache_hit_rate"] = args.cache_hit_rate
            result = project.estimate(links=args.links, **assumptions)
        elif command in {"collect", "resume"}:
            print("Pre-collection estimate: " + json.dumps(project.estimate(), ensure_ascii=False, sort_keys=True, default=str), file=sys.stderr)
            provider = None
            if args.offline:
                from .providers import FakeProvider
                provider = FakeProvider()
            result = getattr(project, command)(provider=provider, allow_paid=args.allow_paid, max_jobs=args.max_jobs)
        elif command == "status":
            result = project.status()
        elif command == "cancel":
            project.cancel()
            result = project.status()
        elif command == "large-run":
            result = project.configure_large_run()
        elif command == "reset-model":
            result = project.reset_model(args.model_alias)
        elif command == "backup":
            result = project.store.backup(args.out)
        elif command == "retry-job":
            project.retry_failed(args.job_id)
            result = {"job_id": args.job_id, "status": "pending"}
        elif command == "resolve-uncertain":
            project.resolve_uncertain(args.job_id, retry=args.retry, acknowledge_possible_duplicate_billing=args.acknowledge_possible_duplicate_billing)
            result = {"job_id": args.job_id, "status": "pending" if args.retry else "failed", "unknown_reserves_retained": True}
        elif command == "versions":
            result = {"versions": project.versions()}
        elif command == "inspect":
            result = project.inventory()
            if args.record:
                result = {"records": [row for row in result["records"] if row.get("record_id") == args.record],
                          "occurrences": [row for row in result["occurrences"] if row.get("record_id", row.get("term_id")) == args.record]}
                if not result["records"]:
                    raise ValueError("Unknown record ID")
            elif args.term:
                result = {"terms": [row for row in result["terms"] if row.get("term_id", row.get("id")) == args.term], "occurrences": [row for row in result["occurrences"] if row.get("term_id") == args.term], "annotations": [row for row in result["annotations"] if row.get("term_id") == args.term], "relations": [row for row in result["relations"] if args.term in (row.get("term_a"), row.get("term_b"))]}
                if not result["terms"]:
                    raise ValueError("Unknown term ID")
            elif args.source:
                result = {"sources": [row for row in result["sources"] if row.get("source_id", row.get("id")) == args.source], "occurrences": [row for row in result["occurrences"] if row.get("source_id") == args.source], "jobs": [row for row in result["jobs"] if row.get("source_id") == args.source], "audit": [row for row in result["audit"] if row.get("source_id") == args.source]}
                if not result["sources"]:
                    raise ValueError("Unknown source ID")
        elif command == "annotate":
            attributes = json.loads(args.attributes.read_text(encoding="utf-8")) if args.attributes else None
            result = {"annotation_id": project.annotate(args.term_id, args.status, args.note, attributes, args.actor)}
        elif command == "undo-annotation":
            project.undo_annotation(args.annotation_id)
            result = {"undone_annotation_id": args.annotation_id}
        elif command == "relate":
            result = {"relation_id": project.relate(args.term_a, args.term_b, args.kind, args.actor)}
        elif command == "undo-relation":
            project.undo_relation(args.relation_id)
            result = {"undone_relation_id": args.relation_id}
        elif command == "snapshot":
            result = {"version_id": project.snapshot(args.name)}
        elif command == "export":
            result = project.export(args.version, args.out, formats=[part.strip() for part in args.formats.split(",") if part.strip()])
        elif command == "discover":
            from .discovery import StaticManifestSearch
            adapter = StaticManifestSearch(args.manifest, local_root=args.local_root) if args.manifest else None
            result = project.discover(seeds=args.seed, search_adapter=adapter, resume=args.resume)
        elif command in {"evaluate", "split"}:
            from .evaluation import evaluate, read_gold, source_splits
            dataset = project.dataset(args.version)
            if command == "split":
                result = source_splits(dataset["sources"], seed=args.seed, group_field=args.group_field)
            else:
                heldout = json.loads(args.split_manifest.read_text(encoding="utf-8"))["splits"]["test"] if args.split_manifest else None
                result = evaluate(dataset, read_gold(args.gold), unit=args.unit, require_sense=args.require_sense, heldout_source_ids=heldout)
            _write_or_print(result, args.out)
            return 0
        elif command == "serve":
            from .web import serve
            serve(project, port=args.port, allow_paid=args.allow_paid)
            return 0
        else:
            raise ValueError("Unknown command")
        _json(result)
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        if args.command.startswith("cluster-") or args.command in {"configure-cluster", "tune-cluster"}:
            print("termfinder: Cluster operation was blocked or failed. Inspect the saved job state and validated site profile; verify the concrete approval, execution gates and finite resource limits. No supplied values or scheduler exception bodies are echoed.", file=sys.stderr)
        elif args.command in {"configure-compute", "compute"}:
            print("termfinder: Compute configuration is invalid or unavailable. Use a supported backend, credential environment-variable names, a safe endpoint, exact model/version, and finite token caps/rates. No supplied values are echoed.", file=sys.stderr)
        else:
            print(f"termfinder: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
