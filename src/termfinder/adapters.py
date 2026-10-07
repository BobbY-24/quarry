"""Replaceable extraction boundaries with a complete, non-executable audit trail.

No provider is constructed here. Live use requires an explicitly supplied,
single-attempt transport; importing this module and replaying fixtures is offline.
"""
from __future__ import annotations

from copy import deepcopy
import dataclasses
import hashlib
import importlib
import importlib.metadata
import json
import math
import threading
import time
from types import SimpleNamespace

from .config import STAGES
from .experiments import _corpus, _hash
from .exports import canonical_json

VERSION = "7.0.0"
PINS = {"langextract": "1.7.0", "delm": "0.1.4"}
TRACKS = {"matched", "native"}
DEFAULT_SETTINGS = {"passes": 1, "max_char_buffer": 1000, "max_retries": 0,
                    "temperature": 0.0, "split_paragraphs": False, "keywords": [],
                    "score_threshold": 0.5, "validate_in_text": True,
                    "enable_fuzzy_alignment": False, "accept_match_lesser": False}
DEFAULT_ENVELOPE = {"max_calls": 100, "max_input_tokens": 1000000,
                    "max_output_tokens": 100000, "per_call_input_tokens": 16384,
                    "per_call_output_tokens": 4096, "max_seconds": 300,
                    "max_usd": 0, "per_call_reserved_usd": 0}


def _finite(value, *, low=0, high=1e9):
    return type(value) in {int, float} and math.isfinite(value) and low <= value <= high


def validate_adapter_config(config):
    """Validate data only. A valid config never authorizes network/model calls."""
    required = {"schema_version", "adapter", "track", "model_version", "policy", "examples", "envelope", "settings"}
    if not isinstance(config, dict) or set(config) != required or config["schema_version"] != "1":
        raise ValueError("Invalid adapter configuration fields/version")
    if config["adapter"] not in PINS or config["track"] not in TRACKS:
        raise ValueError("Unknown adapter or comparison track")
    for key in ("model_version", "policy"):
        if not isinstance(config[key], str) or not config[key].strip() or len(config[key]) > 20000:
            raise ValueError("Adapter needs bounded policy and explicit model/checkpoint version")
    if not isinstance(config["examples"], list) or not 1 <= len(config["examples"]) <= 100:
        raise ValueError("Supply shared, bounded examples")
    # Reject non-JSON values, including callable/module objects and nonfinite numbers.
    if len(canonical_json(config).encode()) > 1000000:
        raise ValueError("Adapter config exceeds one MB")
    settings, envelope = config["settings"], config["envelope"]
    if not isinstance(settings, dict) or set(settings) - set(DEFAULT_SETTINGS):
        raise ValueError("Unknown adapter settings")
    if not isinstance(envelope, dict) or set(envelope) != set(DEFAULT_ENVELOPE):
        raise ValueError("Declare every finite resource bound")
    for key, value in envelope.items():
        if not _finite(value, high=1e9) or key.startswith("max_") and key not in {"max_usd"} and value <= 0:
            raise ValueError("Invalid finite resource envelope")
        if "tokens" in key or key == "max_calls":
            if type(value) is not int or value <= 0:
                raise ValueError("Calls/tokens need positive integer bounds")
    settings = DEFAULT_SETTINGS | settings
    for key in ("passes", "max_char_buffer", "max_retries"):
        if type(settings[key]) is not int or not (0 if key == "max_retries" else 1) <= settings[key] <= (10 if key != "max_char_buffer" else 16000000):
            raise ValueError("Unbounded pass/chunk/retry setting")
    for key in ("split_paragraphs", "validate_in_text", "enable_fuzzy_alignment", "accept_match_lesser"):
        if type(settings[key]) is not bool:
            raise ValueError("Alignment/filter settings need booleans")
    if not _finite(settings["temperature"], high=2) or not _finite(settings["score_threshold"], high=1):
        raise ValueError("Invalid temperature/threshold")
    if not isinstance(settings["keywords"], list) or len(settings["keywords"]) > 100 or any(not isinstance(v, str) or not v or len(v) > 1000 for v in settings["keywords"]):
        raise ValueError("Invalid keyword filter")
    if config["track"] == "matched" and (settings["split_paragraphs"] or settings["keywords"] or settings["enable_fuzzy_alignment"] or settings["accept_match_lesser"]):
        raise ValueError("Matched track forbids native fuzzy/partial alignment and relevance filtering")
    if config["adapter"] == "delm" and (settings["passes"] != 1 or settings["enable_fuzzy_alignment"] or settings["accept_match_lesser"]):
        raise ValueError("DELM has no extraction-pass/fuzzy-align setting; register repeated outer components")
    if config["adapter"] == "langextract" and (settings["max_retries"] != 0 or settings["split_paragraphs"] or settings["keywords"]):
        raise ValueError("Injected LangExtract transport has no hidden retries or relevance filtering")
    return deepcopy(config) | {"settings": settings}


def adapter_config(adapter, *, track="matched", model_version="offline-shaped-fixture-v1", policy="Extract eligible terms verbatim; retain uncertain meanings.", examples=None, envelope=None, settings=None):
    return validate_adapter_config({"schema_version": "1", "adapter": adapter, "track": track,
        "model_version": model_version, "policy": policy,
        "examples": examples or [{"text": "The term zorb names a shared practice.", "extractions": [{"extraction_class": "term", "extraction_text": "zorb", "attributes": {"language": "en"}}]}],
        "envelope": DEFAULT_ENVELOPE | (envelope or {}), "settings": settings or {}})


class EnvelopeExceeded(RuntimeError):
    """A pre-dispatch bound was reached; this is not a provider error."""


class DispatchMeter:
    """Every library inference attempt must cross this boundary exactly once.

    Reservations are made before dispatch. Unknown usage/cost keeps the full
    reservation. A transport must enforce its supplied per-attempt limits and
    contain no hidden retries. OS/process supervision is a caller responsibility.
    """
    def __init__(self, envelope, model_version):
        self.envelope, self.model_version = envelope, model_version
        self.calls = []
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self.violation = None

    def dispatch(self, transport, *, source_id, prompt, logical_request=None):
        if getattr(transport, "single_attempt", False) is not True or getattr(transport, "honors_limits", False) is not True:
            raise ValueError("Transport must declare one observable attempt and enforcement of supplied limits")
        env = self.envelope
        # UTF-8 bytes are a conservative prompt bound for ordinary byte/subword
        # tokenizers; the exact tokenizer must be validated for live comparisons.
        if len(prompt.encode("utf-8")) > env["per_call_input_tokens"]:
            raise EnvelopeExceeded("input_byte_reservation_exceeded")
        with self._lock:
            if self.violation is not None:
                raise EnvelopeExceeded("terminal_transport_limit_violation")
            elapsed = time.monotonic() - self.started
            if len(self.calls) >= env["max_calls"]:
                raise EnvelopeExceeded("call_limit")
            if elapsed >= env["max_seconds"]:
                raise EnvelopeExceeded("deadline")
            in_used = sum(c.get("input_tokens") if c.get("input_tokens") is not None else env["per_call_input_tokens"] for c in self.calls)
            out_used = sum(c.get("output_tokens") if c.get("output_tokens") is not None else env["per_call_output_tokens"] for c in self.calls)
            reserved = sum(c.get("cost_usd") if c.get("cost_usd") is not None else env["per_call_reserved_usd"] for c in self.calls)
            if in_used + env["per_call_input_tokens"] > env["max_input_tokens"] or out_used + env["per_call_output_tokens"] > env["max_output_tokens"]:
                raise EnvelopeExceeded("token_reservation_limit")
            if reserved + env["per_call_reserved_usd"] > env["max_usd"]:
                raise EnvelopeExceeded("spending_reservation_limit")
            call = {"dispatch_index": len(self.calls), "source_id": source_id,
                    "logical_request": logical_request, "model_version": self.model_version,
                    "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "raw_reply": None, "input_tokens": None, "output_tokens": None,
                    "cost_usd": None, "cost_basis": "not_metered", "usage_reason": "dispatch_unresolved",
                    "cost_reason": "dispatch_unresolved", "status": "uncertain", "error_type": None,
                    "reserved_usd": env["per_call_reserved_usd"]}
            self.calls.append(call)
        request = {"source_id": source_id, "prompt": prompt, "model_version": self.model_version,
                   "logical_request": logical_request, "dispatch_index": call["dispatch_index"],
                   "max_input_tokens": env["per_call_input_tokens"], "max_output_tokens": env["per_call_output_tokens"],
                   "timeout_seconds": max(0, env["max_seconds"] - elapsed), "max_usd": env["per_call_reserved_usd"]}
        try:
            reply = transport.dispatch(request)
            if not isinstance(reply, dict) or set(reply) - {"raw_reply", "usage", "cost_usd", "cost_basis", "missing_reason"}:
                raise ValueError("Invalid transport reply envelope")
            raw, usage, cost = reply.get("raw_reply"), reply.get("usage", {}), reply.get("cost_usd")
            if not isinstance(raw, str) or len(raw) > 8000000 or not isinstance(usage, dict) or set(usage) - {"input_tokens", "output_tokens"}:
                raise ValueError("Invalid raw reply/usage")
            if any(v is not None and (type(v) is not int or v < 0) for v in usage.values()) or cost is not None and not _finite(cost):
                raise ValueError("Invalid usage/cost measurement")
            basis = reply.get("cost_basis", "not_metered")
            if basis not in {"simulated", "token_estimate", "provider_invoice", "not_metered"} or basis == "not_metered" and cost is not None:
                raise ValueError("Invalid cost basis")
            reason = reply.get("missing_reason") or "transport_did_not_report_measurement"
            call.update(raw_reply=raw, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                        cost_usd=cost, cost_basis=basis, status="returned",
                        usage_reason=None if all(usage.get(k) is not None for k in ("input_tokens", "output_tokens")) else reason,
                        cost_reason=None if cost is not None else reason)
            if (usage.get("input_tokens") or 0) > env["per_call_input_tokens"] or (usage.get("output_tokens") or 0) > env["per_call_output_tokens"] or cost is not None and cost > env["per_call_reserved_usd"]:
                call["status"] = "limit_violation"
                with self._lock:
                    self.violation = "transport_exceeded_reserved_limit"
                raise EnvelopeExceeded("transport_exceeded_reserved_limit")
            return raw
        except Exception as error:
            # Exception messages may contain credentials. Retain type only.
            call["error_type"] = type(error).__name__
            if call["status"] == "uncertain":
                call["usage_reason"] = call["cost_reason"] = "attempt_failed_or_uncertain_measurement_unavailable"
            raise


class RecordedTransport:
    """Inert shaped replies, not empirical recordings or a cloud provider."""
    single_attempt = honors_limits = True

    def __init__(self, replies):
        self.replies = iter(deepcopy(replies))

    def dispatch(self, request):
        reply = next(self.replies)
        if "error" in reply:
            raise RuntimeError("synthetic_dispatch_failure")
        return reply


class RecordedBackend:
    """Replay final and pre-filter library-shaped data through the real meter."""
    verification_kind = "synthetic_library_shaped_fixture"

    def __init__(self, fixtures):
        if not isinstance(fixtures, dict) or len(canonical_json(fixtures).encode()) > 32000000:
            raise ValueError("Fixtures must be bounded JSON data")
        self.fixtures = deepcopy(fixtures)

    def extract(self, source, config, meter):
        row = deepcopy(self.fixtures[source["source_id"]])
        transport = RecordedTransport(row.get("calls", []))
        for i in range(len(row.get("calls", []))):
            try:
                meter.dispatch(transport, source_id=source["source_id"], prompt=config["policy"] + "\n" + source["text"], logical_request={"fixture_attempt": i})
            except RuntimeError as error:
                if isinstance(error, EnvelopeExceeded):
                    raise
        return {"proposals": row.get("proposals", []), "decisions": row.get("decisions", []),
                "status": row.get("status", "complete"), "reason": row.get("reason")}


def _load(name, modules):
    if importlib.metadata.version(name) != PINS[name]:
        raise RuntimeError("Installed baseline does not match the reviewed pin")
    return {key: importlib.import_module(path) for key, path in modules.items()}


def _serialize(value):
    if dataclasses.is_dataclass(value):
        return {k: _serialize(v) for k, v in dataclasses.asdict(value).items()}
    if hasattr(value, "value"):
        return _serialize(value.value)
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise ValueError("Library returned a non-data object")


class LangExtractBackend:
    """Pinned Annotator/Resolver with pre-merge alignment and inference hooks.

    Uses a custom BaseLanguageModel; no hidden SDK retries or provider factory.
    Native workflow retains native chunking, fuzzy alignment and first-pass merge.
    Provider-specific constrained decoding is not reproduced by this transport.
    """
    verification_kind = "pinned_library_with_supplied_transport"

    def __init__(self, transport):
        self.transport = transport

    def extract(self, source, config, meter):
        lib = _load("langextract", {"annotation": "langextract.annotation", "resolver": "langextract.resolver",
            "data": "langextract.core.data", "types": "langextract.core.types", "base": "langextract.core.base_model", "prompting": "langextract.prompting"})
        data, native = lib["data"], lib["resolver"]
        parsed, aligned, decisions = [], [], []
        state = {"pass_index": 0}
        transport = self.transport

        class Model(lib["base"].BaseLanguageModel):
            def infer(self, batch_prompts, **kwargs):
                for prompt in batch_prompts:
                    raw = meter.dispatch(transport, source_id=source["source_id"], prompt=prompt,
                                         logical_request={"library_infer_prompt": True, "pass_index": state["pass_index"]})
                    yield [lib["types"].ScoredOutput(score=1.0, output=raw)]

        class Resolver(native.Resolver):
            def resolve(self, raw, **kwargs):
                try:
                    rows = list(super().resolve(raw, **kwargs))
                except Exception as error:
                    decisions.append({"stage": "parse", "decision": "failed", "error_type": type(error).__name__})
                    raise
                parsed.append(_serialize(rows))
                decisions.append({"stage": "parse", "pass_index": state["pass_index"], "parsed_proposals": parsed[-1]})
                return rows

            def align(self, rows, text, token_offset, char_offset=None, **kwargs):
                output = list(super().align(rows, text, token_offset, char_offset, **kwargs))
                aligned.extend((e, state["pass_index"]) for e in output)
                decisions.append({"stage": "alignment", "chunk_text": text, "char_offset": char_offset,
                                  "token_offset": token_offset, "pass_index": state["pass_index"], "parsed": parsed[-1], "aligned": _serialize(output)})
                return iter(output)

        class Annotator(lib["annotation"].Annotator):
            def _annotate_documents_single_pass(self, *args, **kwargs):
                state["pass_index"] += 1
                decisions.append({"stage": "pass", "pass_index": state["pass_index"], "decision": "started"})
                yield from super()._annotate_documents_single_pass(*args, **kwargs)
                decisions.append({"stage": "pass", "pass_index": state["pass_index"], "decision": "completed"})

        template = lib["prompting"].PromptTemplateStructured(description=config["policy"])
        template.examples.extend(data.ExampleData(text=e["text"], extractions=[data.Extraction(**x) for x in e["extractions"]]) for e in config["examples"])
        model = Model()
        model.set_fence_output(False)
        resolver = Resolver(format_type=data.FormatType.JSON, fence_output=False)
        annotator = Annotator(language_model=model, prompt_template=template, format_type=data.FormatType.JSON, fence_output=False)
        settings = config["settings"]
        error = None
        try:
            result = list(annotator.annotate_documents([data.Document(text=source["text"], document_id=source["source_id"])],
                resolver=resolver, max_char_buffer=settings["max_char_buffer"], batch_length=1, debug=False,
                extraction_passes=settings["passes"], show_progress=False,
                enable_fuzzy_alignment=settings["enable_fuzzy_alignment"], accept_match_lesser=settings["accept_match_lesser"],
                suppress_parse_errors=False, temperature=settings["temperature"]))
            final = {id(e) for doc in result for e in doc.extractions or []}
        except Exception as failure:
            error = type(failure).__name__
            final = set()  # Interrupted native multi-pass merge never completed.
        proposals = []
        for index, (extraction, pass_index) in enumerate(aligned):
            row = _serialize(extraction)
            interval, attrs = row.get("char_interval") or {}, row.get("attributes") or {}
            kept = id(extraction) in final
            proposals.append({"observed_text": row.get("extraction_text"), "language": attrs.get("language", source["language"]),
                "interpretation": attrs.get("sense"), "native_start": interval.get("start_pos"), "native_end": interval.get("end_pos"),
                "native_alignment": row.get("alignment_status"), "native_pass_index": pass_index, "retained": kept, "native": row})
            decisions.append({"stage": "merge", "proposal_index": index, "decision": "retained" if kept else "not_emitted",
                "reason": None if kept else "native_first_pass_overlap_priority" if error is None else "native_workflow_interrupted_before_final_emission"})
        return {"proposals": proposals, "decisions": decisions, "status": "complete" if error is None else "partial" if proposals else "failed",
                "reason": None if error is None else "library_failure:" + error}


class DELMBackend:
    """Pinned DELM schema, splitting/scoring, cleaning and outer retry methods.

    Injection bypasses DELM's provider factory, dotenv, logging and global price
    database. Supplied transport returns raw JSON; DELM's Pydantic schema validates
    it. Instructor provider modes and native disk orchestration remain unverified.
    """
    verification_kind = "pinned_library_with_supplied_transport"

    def __init__(self, transport):
        self.transport = transport

    def extract(self, source, config, meter):
        lib = _load("delm", {"extraction": "delm.core.extraction_manager", "schemas": "delm.schemas.schemas",
            "retry": "delm.utils.retry_handler", "config": "delm.config", "split": "delm.strategies.splitting_strategies", "score": "delm.strategies.scoring_strategies"})
        settings = config["settings"]
        schema_spec = {"container_name": "terms", "variables": [
            {"name": "observed_text", "data_type": "string", "description": "Exact eligible source term", "required": True, "validate_in_text": settings["validate_in_text"]},
            {"name": "language", "data_type": "string", "description": "BCP-47 language tag for observed text", "required": True},
            {"name": "interpretation", "data_type": "string", "description": "Proposed contextual meaning; null when uncertain", "required": False},
            {"name": "start", "data_type": "integer", "description": "Unicode codepoint start in this exact input chunk; disambiguate repeats, null if uncertain", "required": False},
            {"name": "end", "data_type": "integer", "description": "Exclusive Unicode codepoint end in this exact input chunk; null if uncertain", "required": False}]}
        schema = lib["schemas"].NestedSchema(schema_spec)
        manager = lib["extraction"].ExtractionManager.__new__(lib["extraction"].ExtractionManager)
        manager.model_config = lib["config"].LLMExtractionConfig(provider="quarry-injected", name=config["model_version"],
            temperature=settings["temperature"], max_retries=settings["max_retries"], dotenv_path=None, track_cost=False)
        manager.temperature, manager.track_cost = settings["temperature"], False
        manager.schema_manager = SimpleNamespace(prompt_template="{variables}\nText:\n{text}", system_prompt=config["policy"] + "\nExamples:\n" + canonical_json(config["examples"]))
        manager.extraction_schema = schema
        manager.retry_handler = lib["retry"].RetryHandler(max_retries=settings["max_retries"], base_delay=0)

        class Cache:
            def get(self, key):
                return None
            def set(self, key, value):
                pass
        manager.semantic_cache = Cache()
        transport = self.transport

        def create(**kwargs):
            if kwargs.get("max_retries") != 0:
                raise ValueError("Unobserved Instructor retries prohibited")
            prompt = "\n".join(m["content"] for m in kwargs["messages"])
            raw = meter.dispatch(transport, source_id=source["source_id"], prompt=prompt,
                                 logical_request={"library_create": True})
            return kwargs["response_model"].model_validate_json(raw)
        manager.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        chunks = lib["split"].ParagraphSplit().split(source["text"]) if settings["split_paragraphs"] else [source["text"]]
        scorer = lib["score"].KeywordScorer(settings["keywords"]) if settings["keywords"] else None
        proposals, decisions, failed, retained_chunks = [], [], 0, 0
        for index, chunk in enumerate(chunks):
            score = scorer.score(chunk) if scorer else None
            keep = scorer is None or score >= settings["score_threshold"]
            positions = _positions(source["text"], chunk) if settings["split_paragraphs"] else [0]
            chunk_start = positions[0] if len(positions) == 1 else None
            decisions.append({"stage": "relevance_filter", "chunk_index": index, "chunk_text": chunk, "score": score,
                "retained": keep, "chunk_source_start": chunk_start, "offset_reason": None if chunk_start is not None else "repeated_chunk_ambiguous"})
            if not keep:
                continue
            retained_chunks += 1
            # This is the pinned library's retry/caching and schema generation path.
            result = manager._extract_from_text_chunk(chunk)
            response = result["extracted_data"]
            if response is None:
                failed += 1
                decisions.append({"stage": "extraction", "chunk_index": index, "decision": "failed", "reason": "library_extraction_failed"})
                continue
            raw_rows = response.model_dump(mode="json").get("terms", [])
            cleaned = schema.validate_and_parse_response_to_dict(response, chunk)
            # Audit individual native cleaning so duplicate rows remain attributable.
            for raw in raw_rows:
                cleaned_one = schema._clean_item(raw, chunk.lower())
                kept = cleaned_one is not None
                row = cleaned_one if kept else raw
                proposals.append({"observed_text": row.get("observed_text"), "language": row.get("language"),
                    "interpretation": row.get("interpretation"), "native_start": None, "native_end": None,
                    "proposed_start": row.get("start"), "proposed_end": row.get("end"), "chunk_text": chunk,
                    "chunk_source_start": chunk_start, "retained": kept, "native": raw})
                decisions.append({"stage": "schema_filter", "chunk_index": index, "parsed_proposal": raw,
                    "cleaned_proposal": cleaned_one, "retained": kept,
                    "reason": None if kept else "native_required_null_allowed_value_or_case_insensitive_text_filter"})
            decisions.append({"stage": "schema_filter_result", "chunk_index": index, "cleaned_response": cleaned})
        status = "partial" if failed and failed < retained_chunks else "failed" if failed else "complete"
        reason = "library_chunk_failures" if failed else "all_chunks_filtered_by_native_relevance_policy" if retained_chunks == 0 else None
        return {"proposals": proposals, "decisions": decisions, "status": status, "reason": reason}


def _positions(text, needle):
    if not isinstance(needle, str) or not needle:
        return []
    found, cursor = [], 0
    while (start := text.find(needle, cursor)) >= 0:
        found.append(start)
        cursor = start + 1
    return found


def normalize_proposal(proposal, source, adapter, prediction_id):
    """Predeclared exact positions; never choose the first repeated mention."""
    if not isinstance(proposal, dict):
        prediction = {"prediction_id": prediction_id, "source_id": source["source_id"], "observed_text": None,
                      "language": None, "start": None, "end": None, "interpretation": None}
        return prediction, {"prediction_id": prediction_id, "native_proposal": deepcopy(proposal),
                            "offset_origin": "unavailable", "transformation": "retained_invalid_native_proposal",
                            "reason": "proposal_not_object", "normalized_prediction": prediction}
    text = proposal.get("observed_text")
    start, end, origin, reason = None, None, "unavailable", None
    if proposal.get("retained", True) is not True:
        reason = "native_filter_or_merge_not_retained"
    elif adapter == "langextract":
        start, end, origin = proposal.get("native_start"), proposal.get("native_end"), "native"
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]) or source["text"][start:end] != text:
            reason = "native_alignment_not_verbatim_at_reported_span"
    else:
        chunk = proposal.get("chunk_text", source["text"])
        chunk_start = proposal.get("chunk_source_start", 0)
        if not isinstance(chunk, str):
            reason = "invalid_native_chunk_text"
        elif type(chunk_start) is not int or chunk_start < 0 or source["text"][chunk_start:chunk_start + len(chunk)] != chunk:
            reason = "chunk_source_alignment_unavailable"
        elif proposal.get("proposed_start") is not None or proposal.get("proposed_end") is not None:
            a, b = proposal.get("proposed_start"), proposal.get("proposed_end")
            if type(a) is int and type(b) is int and 0 <= a < b <= len(chunk) and chunk[a:b] == text:
                start, end, origin = chunk_start + a, chunk_start + b, "adapter_verified_model_chunk_offsets"
            else:
                reason = "invalid_model_chunk_offsets_not_repaired"
        else:
            positions = _positions(chunk, text)
            if len(positions) == 1:
                start = chunk_start + positions[0]
                end, origin = start + len(text), "adapter_unique_exact_in_unambiguous_chunk"
            else:
                reason = "expression_repeated_ambiguous" if positions else "expression_not_exact_in_chunk"
    if reason:
        start = end = None
    prediction = {"prediction_id": prediction_id, "source_id": source["source_id"], "observed_text": text,
                  "language": proposal.get("language"), "start": start, "end": end,
                  "interpretation": proposal.get("interpretation")}
    return prediction, {"prediction_id": prediction_id, "native_proposal": deepcopy(proposal),
                        "offset_origin": origin, "transformation": "preserved_generated_wording", "reason": reason,
                        "normalized_prediction": prediction}


def run_adapter(corpus, config, backend, *, run_id, software_revision=None):
    """Run an injected boundary and return normalized run plus lossless audit.

    There is no backend lookup from config and no credential/config loading.
    The caller supplies code explicitly; fixture replay is the CLI's only path.
    """
    sources = _corpus(corpus)
    config = validate_adapter_config(config)
    meter = DispatchMeter(config["envelope"], config["model_version"])
    predictions, results, audits = [], [], []
    for sid, source in sources.items():
        before = len(meter.calls)
        original_output = None
        try:
            output = backend.extract(source, config, meter)
            original_output = deepcopy(output)
            if not isinstance(output, dict) or set(output) != {"proposals", "decisions", "status", "reason"}:
                raise ValueError("Invalid backend source output shape")
            if not isinstance(output["proposals"], list) or len(output["proposals"]) > 100000 or not isinstance(output["decisions"], list):
                raise ValueError("Invalid bounded backend proposal/decision population")
            if output["status"] not in {"complete", "partial", "failed", "pending", "uncertain", "excluded"}:
                raise ValueError("Invalid backend source status")
        except Exception as error:
            output = {"proposals": [], "decisions": [], "status": "uncertain" if len(meter.calls) > before and any(c["status"] == "uncertain" for c in meter.calls[before:]) else "pending" if isinstance(error, EnvelopeExceeded) else "failed",
                      "reason": str(error) if isinstance(error, EnvelopeExceeded) else "backend_failure:" + type(error).__name__}
        transformations = []
        for index, proposal in enumerate(output["proposals"]):
            prediction, transformation = normalize_proposal(proposal, source, config["adapter"], f"{run_id}:{sid}:{index}")
            predictions.append(prediction)
            transformations.append(transformation)
        reason = output.get("reason")
        if output["status"] != "complete" and not reason:
            reason = "backend_declared_incomplete"
        results.append({"source_id": sid, "text_sha256": source["text_sha256"], "status": output["status"], "reason": reason})
        audits.append({"source_id": sid, "parsed_proposals": deepcopy(output["proposals"]),
                       "native_decisions": deepcopy(output["decisions"]), "adapter_transformations": transformations,
                       "original_backend_output": original_output,
                       "dispatch_indices": list(range(before, len(meter.calls))), "outcome": results[-1]})
    calls = meter.calls
    kinds = {c["cost_basis"] for c in calls if c["cost_usd"] is not None}
    if len(kinds) > 1:
        raise ValueError("Separate runs with different cost measurement bases")
    unknown = any(c["cost_usd"] is None for c in calls)
    costs = [{"stage": stage, "known_usd": 0, "uncertain_reserved_usd": 0, "basis": "simulated" if getattr(backend, "verification_kind", "").startswith("synthetic") else "token_estimate", "missing_reason": None} for stage in STAGES]
    extraction = next(c for c in costs if c["stage"] == "extraction")
    extraction.update(known_usd=None if unknown else sum(c["cost_usd"] for c in calls),
        uncertain_reserved_usd=sum(c["reserved_usd"] for c in calls if c["cost_usd"] is None),
        basis=next(iter(kinds)) if kinds else "not_metered" if calls else extraction["basis"],
        missing_reason="one_or_more_actual_attempt_costs_unavailable" if unknown else None)
    if not getattr(backend, "verification_kind", "").startswith("synthetic"):
        costs.extend({"stage": stage, "known_usd": None, "uncertain_reserved_usd": None, "basis": "not_metered", "missing_reason": "not_measured_by_adapter"} for stage in ("human_review", "infrastructure", "external_planning"))
    provenance = {"software_revision": software_revision, "model_version": config["model_version"],
        "prompt_sha256": _hash({"policy": config["policy"], "examples": config["examples"]}),
        "configuration_sha256": _hash(config), "adapter_version": VERSION + ":" + config["adapter"] + "==" + PINS[config["adapter"]],
        "unavailable_reasons": {} if software_revision else {"software_revision": "operator_did_not_supply_revision"}}
    run = {"schema_version": "1", "run_id": run_id, "system": config["adapter"] + ":" + config["track"],
           "data_type": corpus["data_type"], "proposal_population": "raw_proposals", "provenance": provenance,
           "source_results": results, "predictions": predictions, "costs": costs}
    audit = {"schema_version": "1", "run_id": run_id, "configuration": config, "library_pin": PINS[config["adapter"]],
             "verification_kind": getattr(backend, "verification_kind", "unattested_backend"),
             "source_audits": audits, "dispatches": calls,
             "terminal_transport_violation": meter.violation,
             "measurement": {"actual_dispatches": len(calls), "raw_reply_count": sum(c["raw_reply"] is not None for c in calls),
                 "known_cost_subtotal_usd": sum(c["cost_usd"] or 0 for c in calls), "cost_complete": not unknown,
                 "input_tokens": sum(c["input_tokens"] for c in calls) if all(c["input_tokens"] is not None for c in calls) else None,
                 "output_tokens": sum(c["output_tokens"] for c in calls) if all(c["output_tokens"] is not None for c in calls) else None,
                 "usage_reason": None if all(c["usage_reason"] is None for c in calls) else "one_or_more_attempt_usage_values_unavailable"},
             "limits": ["No empirical extraction-quality claim", "No provider-side exactly-once billing claim", "Transport must enforce timeout and output limits; use process/OS supervision for real execution", "Matched model identity alone does not equalize prompts or provider structured-decoding modes"]}
    # Freeze into JSON data, rejecting accidental callable/library object escape.
    return json.loads(canonical_json({"run": run, "audit": audit}))
