"""Frozen evidence/lineage tampering and malformed input; synthetic only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from termfinder import FakeProvider, Project, Response
from termfinder.config import starter_recipe
from termfinder.publication import audit_dataset, verify_history
from termfinder.sources import parse_document
from termfinder.store import digest


TEXT = "😀 I think bilingual signs improve access. Moonstep and moonstep are pauses."
OPINION = "I think bilingual signs improve access."


class PublicationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def fixture(self, data_type="opinion", *, planned=True):
        project = Project(self.base / (data_type + ("-planned" if planned else "-manual")))
        if planned:
            corpus = self.base / "corpus"
            corpus.mkdir(exist_ok=True)
            source = corpus / "synthetic.md"
            source.write_text(TEXT, encoding="utf-8")
            setup = project.prepare_agent_setup({"data_type": data_type, "starter_recipe": "jargon",
                "research_question": "Which source spans meet the declared synthetic policy?",
                "languages": ["en"], "communities": ["research-corpus"], "local_roots": [str(corpus)],
                "budget_usd": 0, "model_profile": "fake"})
            bundle = deepcopy(setup["starter_bundle"])
            bundle["unresolved_questions"] = []
            bundle["sources"] = [{"source_key": "source-001", "kind": "local", "locator": str(source),
                "metadata": {"language": "en", "community": "research-corpus", "domain": "synthetic",
                    "publication_date": None, "publication_date_reason": "synthetic_fixture",
                    "constraints": {"content_origin": "synthetic_fixture", "license": "test-only",
                                    "permitted_use": "offline_verification", "redistribution": "fixture_only"}},
                "why_selected": "Synthetic evidence-contract test", "origin": "researcher_supplied",
                "search_refs": [], "family_id": "synthetic-family"}]
            project.apply_agent_bundle(bundle)
        else:
            recipe = starter_recipe("jargon")
            recipe["data_type"] = data_type
            recipe["communities"] = ["research-corpus"]
            recipe["execution"]["concurrency"] = 1
            project.configure(recipe, "fake")
            project.add_source(parse_document(TEXT.encode(), "text/plain", "synthetic.md",
                {"language": "en", "community": "research-corpus"}))
        expression = "Moonstep" if data_type == "term" else OPINION
        item = {"expression": expression, "language": "en", "sense": "A synthetic interpretation.",
                "context": TEXT, "start": None, "definition_quote": None, "translation": None, "attributes": {}}
        alternate = dict(item, expression="moonstep") if data_type == "term" else item
        def response(items):
            return Response(json.dumps({"candidates": items, "coverage_complete": True}), 40, 40, "stop", "synthetic-v1")
        project.collect(FakeProvider([], [response([item]), response([alternate])]))
        return project.dataset(project.snapshot("synthetic publication packet"))

    def codes(self, data):
        return {issue["code"] for issue in audit_dataset(data)["issues"]}

    def test_valid_plan_evidence_and_case_variants_require_no_external_access(self):
        for kind in ("term", "idea", "opinion", "sentence"):
            data = self.fixture(kind)
            before = digest(data)
            with patch("termfinder.sources.SafeFetcher.fetch", side_effect=AssertionError("No fetch")), \
                 patch("termfinder.sources.load_local", side_effect=AssertionError("No archive read")), \
                 patch("termfinder.providers.HTTPProvider.complete", side_effect=AssertionError("No models")):
                result = audit_dataset(data)
            self.assertTrue(result["integrity_passed"], result)
            self.assertEqual(result["checks"]["records"], 1)
            self.assertEqual(result["checks"]["verified_evidence_spans"], 2 if kind == "term" else 1)
            self.assertTrue(result["requires_researcher_review"])  # original archive still unrecorded
            self.assertEqual(digest(data), before)

    def test_orphan_record_and_changed_record_text_type_origin_are_errors(self):
        base = self.fixture()
        cases = [(lambda d: d.update(occurrences=[]), "record_without_evidence"),
                 (lambda d: d["records"][0].update(observed_text="A generated paraphrase."), "record_evidence_mismatch"),
                 (lambda d: d["records"][0].update(record_type="sentence"), "record_evidence_mismatch"),
                 (lambda d: d["records"][0].update(text_origin="model_generated"), "record_origin_invalid"),
                 (lambda d: d["occurrences"][0].update(record_type="term"), "record_evidence_mismatch"),
                 (lambda d: d["occurrences"][0].update(observed_text="A rewritten opinion."), "record_evidence_mismatch"),
                 (lambda d: d["occurrences"][0].update(term_id="different"), "record_identifier_alias_mismatch")]
        for mutation, code in cases:
            with self.subTest(code=code):
                data = deepcopy(base)
                mutation(data)
                result = audit_dataset(data)
                self.assertFalse(result["integrity_passed"])
                self.assertIn(code, {i["code"] for i in result["issues"]})

    def test_term_views_must_agree_without_forbidding_case_variants(self):
        data = self.fixture("term")
        self.assertTrue(audit_dataset(data)["integrity_passed"])
        data["records"][0]["interpretation"] = "A changed generic interpretation."
        self.assertIn("record_views_disagree", self.codes(data))

    def test_exact_context_source_hash_and_job_contract_tampering_detected(self):
        base = self.fixture()
        mutations = [(lambda d: d["sources"][0].update(text="changed"), "source_text_hash_mismatch"),
                     (lambda d: d["sources"][0].update(raw_sha256="not-a-hash"), "source_provenance_incomplete"),
                     (lambda d: d["sources"][0].update(retrieved_at="invented"), "source_provenance_incomplete"),
                     (lambda d: d["occurrences"][0].update(start=True), "evidence_span_mismatch"),
                     (lambda d: d["occurrences"][0].update(context="invented"), "context_span_mismatch"),
                     (lambda d: d["occurrences"][0].update(contexts=[]), "context_missing"),
                     (lambda d: d["occurrences"][0].update(provenance=[]), "extraction_provenance_missing")]
        for mutation, code in mutations:
            data = deepcopy(base)
            mutation(data)
            self.assertIn(code, self.codes(data))
        for key, value in (("start", "invalid"), ("end", 1), ("record_type", "term")):
            data = deepcopy(base)
            for job in data["jobs"]:
                job[key] = value
            self.assertIn("job_evidence_contract_mismatch", self.codes(data))
        for key in ("source_text_sha256", "source_id", "prompt_sha256"):
            data = deepcopy(base)
            for job in data["jobs"]:
                job["signature"][key] = "wrong"
            self.assertIn("job_evidence_contract_mismatch", self.codes(data))

    def test_configured_provenance_fields_match_each_saved_request(self):
        base = self.fixture()
        replacements = {"provider": "another-provider", "model": "another-model",
            "configured_model_version": "another-configured-version", "recipe_sha256": "0" * 64,
            "prompt_version": "another-prompt", "expert_id": "another-expert",
            "stage": "another-stage", "lens": "another-lens", "transport_identity": "another-transport"}
        for key, value in replacements.items():
            with self.subTest(key=key):
                data = deepcopy(base)
                data["occurrences"][0]["provenance"][0][key] = value
                self.assertIn("configured_provenance_mismatch", self.codes(data))

    def test_request_signature_and_job_identifier_detect_configuration_tampering(self):
        base = self.fixture()
        mutations = [lambda d: d["jobs"][0]["model"].update(provider="changed-provider"),
                     lambda d: d["jobs"][0]["model"].update(version="changed-version"),
                     lambda d: d["jobs"][0]["expert"].update(lens="changed-lens"),
                     lambda d: d["jobs"][0].update(policy_hash="0" * 64),
                     lambda d: d["jobs"][0].update(job_id="job_changed"),
                     lambda d: d["jobs"][0].update(transport_identity="changed-transport"),
                     lambda d: d["jobs"][0].update(max_output_tokens=123),
                     lambda d: d["jobs"][0]["signature"].update(policy="0" * 64),
                     lambda d: d["jobs"][0]["signature"]["provider"].update(kind="changed-kind"),
                     lambda d: d["jobs"][0]["signature"].update(prompt_version="changed-prompt")]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                data = deepcopy(base)
                mutation(data)
                self.assertIn("job_signature_mismatch", self.codes(data))

    def test_provider_reported_revision_is_independent_of_configured_alias(self):
        base = self.fixture()
        for reported, reason in (("provider-release-2026-10-05", None), (None, "not_reported_by_provider")):
            data = deepcopy(base)
            provenance = data["occurrences"][0]["provenance"][0]
            self.assertNotEqual(reported, provenance["configured_model_version"])
            provenance.update(reported_model_version=reported, reported_model_version_reason=reason)
            self.assertTrue(audit_dataset(data)["integrity_passed"])
        for reported, reason in ((None, None), (None, ""), ({"revision": "nested"}, None)):
            data = deepcopy(base)
            data["occurrences"][0]["provenance"][0].update(
                reported_model_version=reported, reported_model_version_reason=reason)
            self.assertIn("reported_model_version_invalid", self.codes(data))

    def test_historical_jobs_keep_their_own_recipe_and_model_configuration(self):
        first = self.fixture()
        project = Project(self.base / "opinion-planned")
        recipe, profile = deepcopy(first["recipe"]), deepcopy(first["profile"])
        recipe["version"] = "synthetic-revision-2"
        for model in profile["models"].values():
            model["version"] = "synthetic-model-revision-2"
        project.configure(recipe, profile)
        item = {"expression": OPINION, "language": "en", "sense": "A synthetic interpretation.",
                "context": TEXT, "start": None, "definition_quote": None, "translation": None, "attributes": {}}
        response = Response(json.dumps({"candidates": [item], "coverage_complete": True}),
                            40, 40, "stop", "a-provider-reported-alias")
        project.collect(FakeProvider([], [response, response]))
        data = project.dataset(project.snapshot("two historical configurations"))
        self.assertEqual(len({job["policy_hash"] for job in data["jobs"]}), 2)
        self.assertEqual(len({job["model"]["version"] for job in data["jobs"]}), 2)
        self.assertTrue(audit_dataset(data)["integrity_passed"], audit_dataset(data))

    def test_planned_source_bindings_selection_metadata_and_declarations(self):
        base = self.fixture()
        for key, value in (("family_id", "another-family"), ("source_selection_origin", "agent_suggested"),
                           ("approved_locator", "another-file.md"), ("search_refs", ["invented"]),
                           ("source_selection_reason", "changed"), ("agent_brief_sha256", "changed")):
            data = deepcopy(base)
            data["sources"][0]["constraints"][key] = value
            self.assertIn("source_plan_binding_mismatch", self.codes(data), key)
        data = deepcopy(base)
        data["sources"][0]["constraints"]["content_origin"] = "unlabeled_generated_text"
        self.assertIn("source_plan_metadata_mismatch", self.codes(data))
        data = deepcopy(base)
        data["sources"][0]["language"] = "zh"
        self.assertIn("source_plan_metadata_mismatch", self.codes(data))
        data = deepcopy(base)
        binding = next(iter(data["agent_workflow"]["source_map"]))
        data["agent_workflow"]["source_map"][binding] = "missing-source"
        self.assertIn("source_map_binding_invalid", self.codes(data))

    def test_uningested_approved_sources_rights_archives_and_pending_work_are_review_findings(self):
        data = self.fixture()
        data["occurrences"] = []
        data["records"] = []
        data["sources"] = []
        data["jobs"] = []
        data["agent_workflow"]["source_map"] = {}
        result = audit_dataset(data)
        self.assertTrue(result["integrity_passed"])
        self.assertTrue(result["requires_researcher_review"])
        self.assertIn("approved_source_not_ingested", {i["code"] for i in result["issues"]})
        data = self.fixture("sentence", planned=False)
        data["sources"][0]["constraints"] = {}
        data["jobs"][0]["status"] = "uncertain"
        result = audit_dataset(data)
        self.assertTrue(result["integrity_passed"], result)
        for code in ("source_use_unresolved", "original_bytes_archive_unrecorded", "processing_incomplete"):
            self.assertIn(code, {i["code"] for i in result["issues"]})
        data["sources"][0]["constraints"]["original_bytes_archive"] = "researcher-declared-archive"
        self.assertIn("original_bytes_archive_unverified", self.codes(data))

    def test_history_structure_and_applied_recipe_hash_verified(self):
        base = self.fixture()
        self.assertTrue(verify_history(base["agent_workflow"]["events"]))
        for events in (None, [42], [{"sequence": True}], [{"sequence": 0, "payload": []}], []):
            if events == []:
                self.assertTrue(verify_history(events))
            else:
                self.assertFalse(verify_history(events))
        data = deepcopy(base)
        applied = next(e for e in data["agent_workflow"]["events"] if e["event_type"] == "plan_applied")
        applied["payload"]["recipe_sha256"] = "wrong"
        self.assertIn("applied_recipe_hash_mismatch", self.codes(data))
        data = deepcopy(base)
        data["agent_workflow"]["events"][0]["payload"]["prompt"] = "changed"
        self.assertIn("setup_history_hash_mismatch", self.codes(data))

    def test_malformed_nested_artifacts_report_errors_without_crashing(self):
        base = self.fixture()
        for field, value in (("sources", None), ("records", [42]), ("terms", {}), ("jobs", [None]),
                             ("occurrences", [{"occurrence_id": []}]), ("agent_workflow", [])):
            data = deepcopy(base)
            data[field] = value
            self.assertFalse(audit_dataset(data)["integrity_passed"], field)
        mutations = [lambda d: d["sources"][0].update(text={}),
                     lambda d: d["sources"][0].update(constraints=[]),
                     lambda d: d["sources"][0]["constraints"].update(agent_plan_sha256=[]),
                     lambda d: d["records"][0].update(record_type=[]),
                     lambda d: d["records"][0].update(record_id=[]),
                     lambda d: d["records"][0].update(observed_variants={}),
                     lambda d: d["occurrences"][0].update(source_id=[]),
                     lambda d: d["occurrences"][0].update(contexts=[42]),
                     lambda d: d["occurrences"][0].update(provenance=[None]),
                     lambda d: d["occurrences"][0]["provenance"][0].update(job_id={}),
                     lambda d: d["jobs"][0].update(signature=[]),
                     lambda d: d["jobs"][0].update(model=[]),
                     lambda d: d["jobs"][0].update(expert=[]),
                     lambda d: d["agent_workflow"].update(events=[42]),
                     lambda d: d["agent_workflow"].update(source_map=[]),
                     lambda d: d["agent_workflow"]["events"][0].update(payload=[])]
        for mutation in mutations:
            data = deepcopy(base)
            mutation(data)
            self.assertFalse(audit_dataset(data)["integrity_passed"])
        for value in (None, [], {"arbitrary": float("nan")}):
            self.assertFalse(audit_dataset(value)["integrity_passed"])

    def test_duplicate_ids_and_canonical_hashes_never_silently_overwrite(self):
        base = self.fixture()
        for field in ("sources", "records", "jobs", "occurrences"):
            data = deepcopy(base)
            data[field].append(deepcopy(data[field][0]))
            self.assertIn("duplicate_identifier", self.codes(data), field)
        result = audit_dataset(base)
        self.assertEqual(result["dataset_sha256"], digest(base))
        self.assertIn("canonical JSON", " ".join(result["limitations"]))
        self.assertIn("not authenticated signatures", " ".join(result["limitations"]))


if __name__ == "__main__":
    unittest.main()
