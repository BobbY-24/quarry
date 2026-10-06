from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from termfinder.adapters import (DELMBackend, LangExtractBackend, DispatchMeter, EnvelopeExceeded, RecordedBackend,
    RecordedTransport, adapter_config, normalize_proposal, run_adapter, validate_adapter_config)
from termfinder.experiments import compare_experiments


def corpus_fixture():
    texts = {"positive": "Moonstep then moonstep.", "repeated": "zorb zorb", "negative": "Ordinary water."}
    return {"schema_version": "1", "corpus_id": "adapter-synthetic", "data_type": "term", "sources": [
        {"source_id": sid, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
         "domain": "synthetic", "language": "en", "family_id": sid} for sid, text in texts.items()]}


def reply(raw="{}", *, missing=False):
    return {"raw_reply": raw, "usage": {} if missing else {"input_tokens": 20, "output_tokens": 10},
            "cost_usd": None if missing else 0, "cost_basis": "not_metered" if missing else "simulated",
            "missing_reason": "fixture_deliberately_unmetered" if missing else None}


def lx_fixtures():
    # Library-shaped alignment and merge fixtures, not real model recordings.
    return {
        "positive": {"calls": [reply('{"extractions":[{"term":"Moonstep"}]}'), reply('{"extractions":[{"term":"Moonsteps"}]}')],
            "proposals": [
                {"observed_text": "Moonstep", "language": "en", "interpretation": None, "native_start": 0, "native_end": 8, "native_alignment": "match_exact", "retained": True},
                {"observed_text": "Moonsteps", "language": "en", "interpretation": None, "native_start": 0, "native_end": 8, "native_alignment": "match_fuzzy", "retained": True},
                {"observed_text": "moonstep", "language": "en", "interpretation": "variant", "native_start": 14, "native_end": 22, "retained": False}],
            "decisions": [{"stage": "merge", "decision": "native_first_pass_overlap_priority", "pass": 2}]},
        "repeated": {"calls": [reply("malformed {" )], "proposals": [], "status": "failed", "reason": "native_parse_failure"},
        "negative": {"calls": [reply('{"extractions":[]}')], "proposals": []}}


class AdapterTests(unittest.TestCase):
    def test_native_alignment_never_replaces_generated_wording(self):
        corpus = corpus_fixture()
        packet = run_adapter(corpus, adapter_config("langextract", track="native", settings={"enable_fuzzy_alignment": True}),
                             RecordedBackend(lx_fixtures()), run_id="lx-shaped")
        rows = packet["run"]["predictions"]
        self.assertEqual(rows[0]["start"], 0)
        self.assertEqual(rows[1]["observed_text"], "Moonsteps")
        self.assertIsNone(rows[1]["start"])
        self.assertIsNone(rows[2]["start"])
        transforms = packet["audit"]["source_audits"][0]["adapter_transformations"]
        self.assertEqual(transforms[1]["native_proposal"]["native_start"], 0)
        self.assertEqual(transforms[1]["reason"], "native_alignment_not_verbatim_at_reported_span")
        self.assertEqual(transforms[2]["reason"], "native_filter_or_merge_not_retained")
        self.assertEqual(packet["audit"]["measurement"]["actual_dispatches"], 4)
        self.assertEqual(packet["audit"]["dispatches"][2]["raw_reply"], "malformed {")

    def test_delm_unique_alignment_repeated_mentions_and_bad_offsets(self):
        source = corpus_fixture()["sources"][1]
        raw = {"observed_text": "zorb", "language": "en", "interpretation": None, "retained": True}
        normalized, audit = normalize_proposal(raw, source, "delm", "ambiguous")
        self.assertIsNone(normalized["start"])
        self.assertEqual(audit["reason"], "expression_repeated_ambiguous")
        specified = raw | {"proposed_start": 5, "proposed_end": 9}
        normalized, audit = normalize_proposal(specified, source, "delm", "specified")
        self.assertEqual(normalized["start"], 5)
        self.assertEqual(audit["offset_origin"], "adapter_verified_model_chunk_offsets")
        normalized, audit = normalize_proposal(raw | {"proposed_start": 1, "proposed_end": 5}, source, "delm", "bad")
        self.assertIsNone(normalized["start"])
        self.assertEqual(audit["reason"], "invalid_model_chunk_offsets_not_repaired")

    def test_all_filtered_sources_remain_in_recall_denominator(self):
        corpus = corpus_fixture()
        fixtures = {s["source_id"]: {"calls": [], "proposals": [], "decisions": [{"stage": "relevance_filter", "retained": False}],
                    "status": "complete", "reason": "all_chunks_filtered_by_native_relevance_policy"} for s in corpus["sources"]}
        fixtures["positive"] = lx_fixtures()["positive"]
        left = run_adapter(corpus, adapter_config("langextract"), RecordedBackend(lx_fixtures()), run_id="left")
        right = run_adapter(corpus, adapter_config("delm", track="native", settings={"keywords": ["moonstep"]}), RecordedBackend(fixtures), run_id="right")
        gold = [{"source_id": s["source_id"], "text_sha256": s["text_sha256"], "complete": True,
                 "terms": [{"expression": "zorb", "language": "en", "sense": None, "occurrences": [{"start": 0, "end": 4}, {"start": 5, "end": 9}]}] if s["source_id"] == "repeated" else []} for s in corpus["sources"]]
        report = compare_experiments(corpus, gold, [left["run"], right["run"]])
        for row in report["runs"]:
            self.assertEqual(row["coverage"]["source_count"], 3)
            self.assertEqual(row["detection"]["overall"]["false_negatives"], 2)
        self.assertEqual(right["run"]["source_results"][1]["reason"], "all_chunks_filtered_by_native_relevance_policy")

    def test_unknown_cost_and_usage_reservations_are_not_zero_measurements(self):
        config = adapter_config("delm", envelope={"max_calls": 2, "max_usd": 0.5, "per_call_reserved_usd": 0.5})
        fixtures = {s["source_id"]: {"calls": [reply(missing=True)], "proposals": []} for s in corpus_fixture()["sources"]}
        packet = run_adapter(corpus_fixture(), config, RecordedBackend(fixtures), run_id="missing")
        self.assertEqual(packet["audit"]["measurement"]["actual_dispatches"], 1)
        self.assertIsNone(packet["audit"]["measurement"]["input_tokens"])
        cost = next(c for c in packet["run"]["costs"] if c["stage"] == "extraction")
        self.assertIsNone(cost["known_usd"])
        self.assertEqual(cost["uncertain_reserved_usd"], 0.5)
        self.assertEqual(packet["run"]["source_results"][1]["status"], "pending")

    def test_attempt_failure_retained_and_next_retry_metered(self):
        config = adapter_config("delm")
        fixtures = {s["source_id"]: {"calls": [], "proposals": []} for s in corpus_fixture()["sources"]}
        fixtures["positive"]["calls"] = [{"error": "timeout"}, reply("recovered")]
        packet = run_adapter(corpus_fixture(), config, RecordedBackend(fixtures), run_id="retry")
        self.assertEqual(packet["audit"]["measurement"]["actual_dispatches"], 2)
        first, second = packet["audit"]["dispatches"]
        self.assertEqual(first["status"], "uncertain")
        self.assertEqual(first["error_type"], "RuntimeError")
        self.assertEqual(second["raw_reply"], "recovered")
        self.assertFalse(packet["audit"]["measurement"]["cost_complete"])

    def test_config_cannot_enable_native_filtering_in_matched_track_or_code(self):
        with self.assertRaises(ValueError):
            adapter_config("langextract", settings={"enable_fuzzy_alignment": True})
        with self.assertRaises(ValueError):
            adapter_config("delm", settings={"keywords": ["x"]})
        invalid = adapter_config("delm") | {"module_path": "remote.code"}
        with self.assertRaises(ValueError):
            validate_adapter_config(invalid)
        with self.assertRaises(ValueError):
            adapter_config("delm", envelope={"max_calls": float("inf")})

    def test_transport_cannot_hide_sdk_retry_boundary(self):
        meter = DispatchMeter(adapter_config("delm")["envelope"], "fixture")
        class UnmeteredTransport:
            def dispatch(self, request):
                raise AssertionError("must not dispatch")
        with self.assertRaises(ValueError):
            meter.dispatch(UnmeteredTransport(), source_id="x", prompt="text")
        self.assertEqual(meter.calls, [])

    def test_external_tool_like_content_is_data(self):
        raw = '{"tool_calls":[{"name":"shell","arguments":"delete everything"}]}'
        meter = DispatchMeter(adapter_config("delm")["envelope"], "fixture")
        self.assertEqual(meter.dispatch(RecordedTransport([reply(raw)]), source_id="x", prompt="text"), raw)
        self.assertEqual(meter.calls[0]["status"], "returned")

    def test_malformed_native_proposals_preserve_audit_and_full_sources(self):
        class MalformedBackend:
            verification_kind = "synthetic-malformed"
            def extract(self, source, config, meter):
                if source["source_id"] == "positive":
                    return {"proposals": [None, {"observed_text": "Moonstep", "language": "en", "chunk_text": 42}],
                            "decisions": [], "status": "complete", "reason": None}
                if source["source_id"] == "repeated":
                    return {"status": "complete", "proposals": "not-a-list"}
                return {"proposals": [], "decisions": [], "status": "complete", "reason": None}
        packet = run_adapter(corpus_fixture(), adapter_config("delm"), MalformedBackend(), run_id="bad")
        self.assertEqual(len(packet["run"]["source_results"]), 3)
        self.assertEqual(packet["run"]["source_results"][1]["status"], "failed")
        self.assertEqual(packet["audit"]["source_audits"][1]["original_backend_output"]["proposals"], "not-a-list")
        self.assertEqual(packet["audit"]["source_audits"][0]["adapter_transformations"][0]["reason"], "proposal_not_object")
        self.assertEqual(packet["audit"]["source_audits"][0]["adapter_transformations"][1]["reason"], "invalid_native_chunk_text")

    def test_reported_transport_overrun_stops_all_subsequent_attempts(self):
        meter = DispatchMeter(adapter_config("delm")["envelope"], "fixture")
        oversized = reply("retained raw despite violation")
        oversized["usage"]["output_tokens"] = 4097
        transport = RecordedTransport([oversized, reply("must never dispatch")])
        with self.assertRaises(EnvelopeExceeded):
            meter.dispatch(transport, source_id="x", prompt="text")
        with self.assertRaisesRegex(EnvelopeExceeded, "terminal_transport_limit_violation"):
            meter.dispatch(transport, source_id="x", prompt="text")
        self.assertEqual(len(meter.calls), 1)
        self.assertEqual(meter.calls[0]["raw_reply"], "retained raw despite violation")
        self.assertEqual(meter.calls[0]["status"], "limit_violation")

    def test_actual_langextract_wrapper_with_api_shaped_library_fixture(self):
        # These classes model the reviewed 1.7.0 API shape. They do not verify
        # third-party alignment algorithms or execute the pinned dependency tree.
        @dataclass
        class Interval:
            start_pos: int
            end_pos: int
        @dataclass
        class Extraction:
            extraction_class: str
            extraction_text: str
            attributes: dict = field(default_factory=dict)
            char_interval: object = None
            alignment_status: str | None = None
        @dataclass
        class Document:
            text: str
            document_id: str
        @dataclass
        class ExampleData:
            text: str
            extractions: list
        class BaseModel:
            def set_fence_output(self, value):
                self.fences = value
        class NativeResolver:
            def __init__(self, **kwargs):
                pass
            def resolve(self, raw, **kwargs):
                value = json.loads(raw)
                return [Extraction("term", row["term"], row.get("term_attributes", {})) for row in value["extractions"]]
            def align(self, rows, text, token_offset, char_offset=None, **kwargs):
                for row in rows:
                    row.char_interval = Interval(0, 8)
                    row.alignment_status = "match_exact" if row.extraction_text == "Moonstep" else "match_fuzzy"
                    yield row
        class NativeAnnotator:
            def __init__(self, *, language_model, prompt_template, **kwargs):
                self.model, self.template = language_model, prompt_template
            def _annotate_documents_single_pass(self, documents, resolver, **kwargs):
                for doc in documents:
                    outputs = list(self.model.infer([self.template.description + "\n" + doc.text]))
                    rows = resolver.resolve(outputs[0][0].output, suppress_parse_errors=False)
                    aligned = list(resolver.align(rows, doc.text, 0, 0))
                    yield SimpleNamespace(document_id=doc.document_id, extractions=aligned)
            def annotate_documents(self, documents, *, resolver, extraction_passes=1, **kwargs):
                by_pass = [list(self._annotate_documents_single_pass(documents, resolver, **kwargs))[0] for _ in range(extraction_passes)]
                # Recorded native merge disposition: pass two's overlapping
                # proposal is absent from the final document.
                yield SimpleNamespace(document_id=by_pass[0].document_id, extractions=by_pass[0].extractions)
        class Template:
            def __init__(self, description):
                self.description, self.examples = description, []
        modules = {"annotation": SimpleNamespace(Annotator=NativeAnnotator), "resolver": SimpleNamespace(Resolver=NativeResolver),
            "data": SimpleNamespace(ExampleData=ExampleData, Extraction=Extraction, Document=Document, FormatType=SimpleNamespace(JSON="json")),
            "types": SimpleNamespace(ScoredOutput=lambda **kwargs: SimpleNamespace(**kwargs)),
            "base": SimpleNamespace(BaseLanguageModel=BaseModel), "prompting": SimpleNamespace(PromptTemplateStructured=Template)}
        corpus = corpus_fixture()
        corpus["sources"] = corpus["sources"][:1]
        transport = RecordedTransport([reply('{"extractions":[{"term":"Moonstep","term_attributes":{"language":"en"}}]}'),
            reply('{"extractions":[{"term":"Moonsteps","term_attributes":{"language":"en"}}]}')])
        with patch("termfinder.adapters._load", return_value=modules) as load:
            packet = run_adapter(corpus, adapter_config("langextract", track="native", settings={"passes": 2, "enable_fuzzy_alignment": True}),
                                 LangExtractBackend(transport), run_id="lx-native-hook-shape")
        load.assert_called_once()
        self.assertEqual(packet["run"]["source_results"][0]["status"], "complete")
        self.assertEqual(len(packet["audit"]["dispatches"]), 2)
        self.assertEqual([d["logical_request"]["pass_index"] for d in packet["audit"]["dispatches"]], [1, 2])
        self.assertEqual(packet["run"]["predictions"][0]["start"], 0)
        self.assertIsNone(packet["run"]["predictions"][1]["start"])
        self.assertEqual(packet["run"]["predictions"][1]["observed_text"], "Moonsteps")
        audit = packet["audit"]["source_audits"][0]
        self.assertEqual(audit["parsed_proposals"][1]["native_alignment"], "match_fuzzy")
        self.assertTrue(any(d.get("reason") == "native_first_pass_overlap_priority" for d in audit["native_decisions"]))

    def test_actual_delm_wrapper_with_api_shaped_schema_filter_and_retry_fixture(self):
        # Models the 0.1.4 manager/schema/client API. No foreign code is imported.
        class ResponseModel:
            def __init__(self, value):
                self.value = value
            @classmethod
            def model_validate_json(cls, raw):
                value = json.loads(raw)
                if not isinstance(value.get("terms"), list):
                    raise ValueError("fixture native schema validation")
                return cls(value)
            def model_dump(self, **kwargs):
                return deepcopy(self.value)
        class NativeSchema:
            def __init__(self, spec):
                self.spec = spec
            def create_pydantic_schema(self):
                return ResponseModel
            def _clean_item(self, raw, text_lwr):
                text, language = raw.get("observed_text"), raw.get("language")
                return deepcopy(raw) if text and language and text.lower() in text_lwr else None
            def validate_and_parse_response_to_dict(self, response, chunk):
                cleaned = [self._clean_item(raw, chunk.lower()) for raw in response.model_dump()["terms"]]
                return {"terms": [row for row in cleaned if row is not None]} if any(cleaned) else {}
        class NativeRetry:
            def __init__(self, max_retries, base_delay):
                self.max_retries = max_retries
            def execute_with_retry(self, function):
                for attempt in range(self.max_retries + 1):
                    try:
                        return function()
                    except Exception:
                        if attempt == self.max_retries:
                            raise
        class NativeManager:
            def _extract_from_text_chunk(self, chunk):
                schema = self.extraction_schema.create_pydantic_schema()
                def attempt():
                    return self.client.chat.completions.create(model=self.model_config.name,
                        temperature=self.temperature, response_model=schema, max_retries=0,
                        messages=[{"role": "system", "content": self.schema_manager.system_prompt}, {"role": "user", "content": chunk}])
                try:
                    return {"extracted_data": self.retry_handler.execute_with_retry(attempt), "errors": []}
                except Exception:
                    return {"extracted_data": None, "errors": "fixture failure"}
        class ParagraphSplit:
            def split(self, text):
                return [p.strip() for p in text.split("\n\n") if p.strip()]
        class KeywordScorer:
            def __init__(self, keywords):
                self.keywords = keywords
            def score(self, text):
                return float(any(k.lower() in text.lower() for k in self.keywords))
        modules = {"extraction": SimpleNamespace(ExtractionManager=NativeManager), "schemas": SimpleNamespace(NestedSchema=NativeSchema),
            "retry": SimpleNamespace(RetryHandler=NativeRetry), "config": SimpleNamespace(LLMExtractionConfig=lambda **kw: SimpleNamespace(**kw)),
            "split": SimpleNamespace(ParagraphSplit=ParagraphSplit), "score": SimpleNamespace(KeywordScorer=KeywordScorer)}
        corpus = corpus_fixture()
        corpus["sources"] = corpus["sources"][:1]
        transport = RecordedTransport([{ "error": "transient"}, reply('{"terms":[{"observed_text":"Imagined","language":"en"},{"observed_text":"Moonstep","language":"en"}]}')])
        with patch("termfinder.adapters._load", return_value=modules):
            packet = run_adapter(corpus, adapter_config("delm", track="native", settings={"max_retries": 1, "split_paragraphs": True, "keywords": ["moonstep"]}),
                                 DELMBackend(transport), run_id="delm-native-hook-shape")
        self.assertEqual(packet["run"]["source_results"][0]["status"], "complete")
        self.assertEqual(len(packet["audit"]["dispatches"]), 2)
        self.assertEqual(packet["audit"]["dispatches"][0]["status"], "uncertain")
        self.assertIsNone(packet["run"]["predictions"][0]["start"])
        self.assertEqual(packet["run"]["predictions"][1]["start"], 0)
        native = packet["audit"]["source_audits"][0]["native_decisions"]
        filters = [d for d in native if d["stage"] == "schema_filter"]
        self.assertEqual([d["retained"] for d in filters], [False, True])
        self.assertEqual(filters[0]["parsed_proposal"]["observed_text"], "Imagined")
        # Entire relevance population filtered: no callback, source still present.
        with patch("termfinder.adapters._load", return_value=modules):
            filtered = run_adapter(corpus, adapter_config("delm", track="native", settings={"keywords": ["absent"]}),
                DELMBackend(RecordedTransport([])), run_id="delm-filtered-hook-shape")
        self.assertEqual(filtered["audit"]["dispatches"], [])
        self.assertEqual(filtered["run"]["source_results"][0]["reason"], "all_chunks_filtered_by_native_relevance_policy")


if __name__ == "__main__":
    unittest.main()
