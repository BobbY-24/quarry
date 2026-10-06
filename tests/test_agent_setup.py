"""Agent drafts cannot cross deterministic scope/authority and evidence gates."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import Project, FakeProvider, Response
from termfinder import cli
from termfinder.agent_setup import normalize_brief, validate_bundle, write_handoff
from termfinder.publication import audit_dataset, verify_history
from termfinder.store import digest

TEXT = "Our system uses byte-level BPE. I think bilingual signs improve access."


class AgentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.corpus = self.base / "corpus"
        self.corpus.mkdir()
        self.source = self.corpus / "source.md"
        self.source.write_text(TEXT, encoding="utf-8")
        self.project = Project(self.base / "project")
        self.brief = {"research_question": "Which technical expressions occur in this declared source?",
                      "data_type": "term", "starter_recipe": "jargon", "local_roots": [str(self.corpus)],
                      "languages": ["en"], "communities": ["research-corpus"], "domains": ["example.org"],
                      "budget_usd": 0, "max_sources": 2, "model_profile": "fake"}
        self.setup = self.project.prepare_agent_setup(self.brief)
        self.bundle = deepcopy(self.setup["starter_bundle"])
        self.bundle["unresolved_questions"] = []
        self.bundle["recipe"]["execution"]["concurrency"] = 1
        self.bundle["agent"]["tool"] = "offline_test_object"
        self.bundle["sources"] = [{"source_key": "source-001", "kind": "local", "locator": str(self.source),
            "metadata": {"language": "en", "community": "research-corpus", "domain": "synthetic",
                "publication_date": None, "publication_date_reason": "synthetic_fixture_without_publication_date",
                "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                                "permitted_use": "offline_verification", "redistribution": "fixture_only"}},
            "why_selected": "Declared synthetic workflow test", "origin": "researcher_supplied",
            "search_refs": [], "family_id": "synthetic-family"}]

    def validate(self, bundle=None):
        return validate_bundle(bundle or self.bundle, self.setup["brief"])

    def collect(self):
        proposal = {"expression": "byte-level BPE", "language": "en", "sense": "A tokenization method",
                    "context": TEXT, "start": None, "definition_quote": None, "translation": None,
                    "attributes": {}}
        def response(items):
            return Response(json.dumps({"candidates": items, "coverage_complete": True}), 40, 40, "stop", "fixture-v1")
        self.project.collect(FakeProvider([], [response([proposal]), response([])]))

    def test_plain_brief_creates_portable_request_without_provider_or_source_read(self):
        with patch("termfinder.providers.HTTPProvider", side_effect=AssertionError("No provider")), \
             patch("termfinder.sources.load_local", side_effect=AssertionError("No source content read")):
            setup = self.project.prepare_agent_setup(self.brief)
            write_handoff(setup, self.base / "handoff")
        self.assertIn("Return JSON only", setup["prompt"])
        self.assertEqual(setup["brief_sha256"], digest(setup["brief"]))
        self.assertEqual(setup["prompt_sha256"], digest(setup["prompt"]))
        self.assertEqual(self.project.inventory()["sources"], [])
        self.assertTrue((self.base / "handoff" / "contract.json").is_file())

    def test_apply_local_plan_and_trace_to_frozen_export_without_network(self):
        with patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("No network")), \
             patch("termfinder.providers.HTTPProvider", side_effect=AssertionError("No provider")):
            self.assertTrue(self.validate()["valid"])
            self.assertEqual(len(self.project.apply_agent_bundle(self.bundle)["source_ids"]), 1)
        self.collect()
        dataset = self.project.dataset(self.project.snapshot("agent-v1"))
        report = audit_dataset(dataset)
        self.assertTrue(report["integrity_passed"], report)
        self.assertEqual(report["checks"]["verified_evidence_spans"], 1)
        constraints = dataset["sources"][0]["constraints"]
        self.assertEqual(constraints["agent_plan_sha256"], digest(self.bundle))
        self.assertEqual(constraints["agent_source_key"], "source-001")
        self.assertTrue(verify_history(dataset["agent_workflow"]["events"]))
        version = dataset["version_id"]
        for name in ("a", "b"):
            self.project.export(version, self.base / name)
        for path in (self.base / "a").iterdir():
            self.assertEqual(path.read_bytes(), (self.base / "b" / path.name).read_bytes())
        self.assertTrue((self.base / "a" / "agent_workflow.json").is_file())
        self.assertTrue((self.base / "a" / "publication_audit.json").is_file())

    def test_scope_budget_profile_and_type_expansions_cannot_apply(self):
        cases = [("languages", ["en", "zh"]), ("communities", ["*"]), ("mode", "specialists"),
                 ("model_profile", "gemini"), ("data_type", "opinion")]
        for key, value in cases:
            bundle = deepcopy(self.bundle)
            bundle["recipe"][key] = value
            self.assertFalse(self.validate(bundle)["valid"], key)
        for mutation in (lambda r: r["execution"].update(budget_usd=1),
                         lambda r: r["source_scope"].update(domains=["*"]),
                         lambda r: r["discovery"].update(enabled=True)):
            bundle = deepcopy(self.bundle)
            mutation(bundle["recipe"])
            self.assertFalse(self.validate(bundle)["valid"])
            with self.assertRaises(ValueError):
                self.project.apply_agent_bundle(bundle)
        self.assertIsNone(self.project.recipe)

    def test_stale_plan_unresolved_questions_and_removed_criteria_get_repair_prompt(self):
        for mutation in (lambda b: b.update(brief_sha256="old"),
                         lambda b: b.update(unresolved_questions=["Which opinions are in scope?"]),
                         lambda b: b["recipe"].update(inclusion_criteria=["Collect anything"])):
            bundle = deepcopy(self.bundle)
            mutation(bundle)
            report = self.validate(bundle)
            self.assertFalse(report["valid"])
            self.assertIn("Repair", report["repair_prompt"])

    def test_outside_symlink_and_hidden_local_files_are_rejected(self):
        outside = self.base / "outside.txt"
        outside.write_text("Unrelated test file")
        link = self.corpus / "link.txt"
        link.symlink_to(outside)
        hidden = self.corpus / ".secret.txt"
        hidden.write_text("Synthetic marker")
        for path in (outside, link, hidden):
            bundle = deepcopy(self.bundle)
            bundle["sources"][0]["locator"] = str(path)
            self.assertFalse(self.validate(bundle)["valid"])

    def test_malformed_nested_values_produce_diagnostics_not_crashes(self):
        for field, value in (("sources", [42]), ("sampling", None), ("evaluation", []), ("agent", "Claude"),
                             ("search_log", [{"search_id": "q", "query": "query", "provider": "fake", "executed_at": 42, "results": [], "limitations": []}])):
            bundle = deepcopy(self.bundle)
            bundle[field] = value
            self.assertFalse(self.validate(bundle)["valid"], field)

    def test_empty_scope_forged_retrieval_dates_and_inconsistent_evaluation_rejected(self):
        for mutation in (lambda b: b["recipe"]["source_scope"].update(domains=[]),
                         lambda b: b["sources"][0]["metadata"].update(retrieved_at="1900-01-01"),
                         lambda b: b["evaluation"].update(matching="source_expression")):
            bundle = deepcopy(self.bundle)
            mutation(bundle)
            self.assertFalse(self.validate(bundle)["valid"])

    def test_changed_configuration_cannot_race_approved_ingestion(self):
        self.project.apply_agent_bundle(self.bundle)
        original = self.project._lock
        @contextmanager
        def changed_lock():
            with original():
                recipe = self.project.recipe
                recipe["execution"]["budget_usd"] = 1
                self.project.store.setting("recipe", recipe)
                yield
        with patch.object(self.project, "_lock", changed_lock), self.assertRaises(ValueError):
            self.project.ingest_agent_sources()

    def test_replaced_plan_cannot_ingest_under_an_earlier_apply_result(self):
        original_ingest = self.project.ingest_agent_sources
        def replaced_plan(**kwargs):
            current = self.project.agent_setup()
            current["bundle_sha256"] = "a" * 64
            self.project.store.setting("agent_setup", current)
            return original_ingest(**kwargs)
        with patch.object(self.project, "ingest_agent_sources", replaced_plan), self.assertRaises(ValueError):
            self.project.apply_agent_bundle(self.bundle)
        self.assertEqual(self.project.inventory()["sources"], [])

    def test_nonterm_templates_start_with_units_rather_than_jargon_policy(self):
        from termfinder.agent_setup import template_bundle
        from termfinder.config import load_recipe
        for kind in ("idea", "opinion", "sentence"):
            brief = normalize_brief(dict(self.brief, data_type=kind))
            recipe = template_bundle(brief)["recipe"]
            self.assertEqual(load_recipe(recipe)["data_type"], kind)
            self.assertNotIn("technical_category", recipe["output"]["attributes"])
            for lens in recipe["specialist_lenses"]:
                self.assertIn(kind, lens["lens"])
            for group in ("positive", "negative", "boundary"):
                example = recipe["examples"][group][0]
                self.assertIn(example["expression"], example["text"])
                self.assertIn("Synthetic", example["reason"])

    def test_template_routing_supports_all_profiles_types_and_modes(self):
        from termfinder.agent_setup import template_bundle
        from termfinder.config import experts, load_profile
        for profile in ("glm-deepseek", "gemini", "fake"):
            for kind in ("term", "idea", "opinion", "sentence"):
                for mode in ("broad", "specialists"):
                    brief = normalize_brief(dict(self.brief, model_profile=profile, data_type=kind, mode=mode))
                    bundle = template_bundle(brief)
                    bundle["sources"] = deepcopy(self.bundle["sources"])
                    bundle["unresolved_questions"] = []
                    self.assertTrue(validate_bundle(bundle, brief)["valid"], (profile, kind, mode))
                    passes = experts(bundle["recipe"], load_profile(profile))
                    self.assertEqual(len(passes), (1 if profile == "gemini" else 2) + (2 if mode == "specialists" else 0))

    def test_blind_corpus_materializes_families_and_blank_packets_before_jobs(self):
        self.project.apply_agent_bundle(self.bundle)
        prepared = self.project.freeze_agent_corpus()
        self.assertEqual(prepared["source_count"], 1)
        packet = json.loads((Path(prepared["out"]) / "annotation_sources.jsonl").read_text())
        self.assertFalse(packet["complete"])
        self.assertEqual(packet["terms"], [])
        self.assertEqual(set(prepared["family_map"].values()), {"synthetic-family"})
        self.assertTrue(verify_history(self.project.store.read_setting("agent_workflow")))
        self.project.collect(FakeProvider([], []), max_jobs=0)
        with self.assertRaises(ValueError):
            self.project.freeze_agent_corpus()

    def test_secret_bearing_rejection_never_saves_or_echoes_secret_marker(self):
        bundle = deepcopy(self.bundle)
        marker = "synthetic-secret-marker-do-not-log"
        bundle["agent"]["api_key"] = marker
        report = self.project.validate_agent_bundle(bundle)
        self.assertFalse(report["valid"])
        self.assertNotIn(marker, json.dumps(report))
        self.assertNotIn(marker, json.dumps(self.project.store.read_setting("agent_workflow")))

    def test_urls_staged_and_explicit_fetch_only_uses_approved_list_once(self):
        bundle = deepcopy(self.bundle)
        source = bundle["sources"][0]
        source.update(kind="url", locator="https://example.org/source")
        with patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("Apply must stage")):
            result = self.project.apply_agent_bundle(bundle)
        self.assertEqual(result["staged_remote_source_keys"], ["source-001"])
        from termfinder.sources import parse_document
        document = parse_document(TEXT.encode(), "text/plain", source["locator"], source["metadata"])
        with patch("termfinder.sources.SafeFetcher.fetch", return_value=document) as fetch:
            self.project.ingest_agent_sources()
            self.project.ingest_agent_sources()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], "https://example.org/source")

    def test_remote_scope_credentials_private_hosts_and_source_cap_rejected(self):
        for url in ("https://outside.example/source", "https://user:pass@example.org/source", "https://example.org/source?api_key=synthetic", "http://127.0.0.1/source"):
            bundle = deepcopy(self.bundle)
            bundle["sources"][0].update(kind="url", locator=url)
            self.assertFalse(self.validate(bundle)["valid"])
        bundle = deepcopy(self.bundle)
        bundle["sources"] *= 3
        self.assertFalse(self.validate(bundle)["valid"])

    def test_processing_failures_remain_visible_and_plan_survives_reopen(self):
        broken = self.corpus / "broken.pdf"
        broken.write_bytes(b"not a pdf")
        bundle = deepcopy(self.bundle)
        bundle["sources"][0]["locator"] = str(broken)
        result = self.project.apply_agent_bundle(bundle)
        self.assertTrue(result["failures"])
        self.assertTrue(self.project.status()["failures"])
        self.assertTrue(Project(self.project.path).agent_setup()["applied"])

    def test_publication_audit_detects_text_span_history_and_plan_join_tampering(self):
        self.project.apply_agent_bundle(self.bundle)
        self.collect()
        frozen = self.project.dataset(self.project.snapshot("audit-v1"))
        for mutate in (lambda d: d["sources"][0].update(text="changed"),
                       lambda d: d["occurrences"][0].update(start=999),
                       lambda d: d["agent_workflow"]["events"][0]["payload"].update(prompt="changed"),
                       lambda d: d["sources"][0]["constraints"].update(agent_source_key="missing")):
            changed = deepcopy(frozen)
            mutate(changed)
            self.assertFalse(audit_dataset(changed)["integrity_passed"])

    def test_cli_prepares_validates_applies_and_audits_through_public_commands(self):
        def run(*args):
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                status = cli.main(["--project", str(self.project.path), *map(str, args)])
            return status, json.loads(output.getvalue())
        code, result = run("prepare-agent", "--idea", self.brief["research_question"], "--policy", "jargon",
            "--local-root", self.corpus, "--domain", "example.org", "--profile", "fake", "--max-sources", "2", "--out", self.base / "cli-handoff")
        self.assertEqual(code, 0)
        self.bundle["brief_sha256"] = self.project.agent_setup()["brief_sha256"]
        file = self.base / "bundle.json"
        file.write_text(json.dumps(self.bundle))
        self.assertEqual(run("validate-plan", file)[0], 0)
        self.assertEqual(run("apply-plan", file)[0], 0)
        self.assertEqual(len(self.project.inventory()["sources"]), 1)
        self.collect()
        version = self.project.snapshot("cli-v1")
        self.assertTrue(run("publication-audit", version)[1]["integrity_passed"])


if __name__ == "__main__":
    unittest.main()
