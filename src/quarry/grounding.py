"""Exact deterministic evidence checks; no judgments of meanings or novelty."""
from __future__ import annotations

import json
import math
import re
import unicodedata

from .store import ident, now


def normalize(expression, language):
    text = unicodedata.normalize("NFC", expression)
    # Preserve script, accents and diacritics. Casefold locale exception for
    # Turkish/Azeri dotted I; no NFKC/translation/transliteration/lemmatization.
    if language.split("-")[0].lower() in {"tr", "az"}:
        text = text.replace("I", "ı").replace("İ", "i")
    return text.casefold()


def parse_response(raw):
    """Return complete objects even when the final response is cut off."""
    if not isinstance(raw, str) or len(raw) > 8_000_000:
        return [], False, ["response_type_or_size"]
    raw = raw.strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[7:-3].strip()
    def reject_constant(_):
        raise ValueError("nonfinite numeric response")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite numeric response")
        return number
    try:
        value = json.loads(raw, parse_constant=reject_constant, parse_float=finite_float)
        if not isinstance(value, dict) or set(value) != {"candidates", "coverage_complete"} or not isinstance(value["candidates"], list):
            raise ValueError()
        if type(value["coverage_complete"]) is not bool:
            raise ValueError()
        return value["candidates"], value["coverage_complete"], []
    except (ValueError, TypeError, RecursionError):
        candidates = []
        match = re.search(r'"candidates"\s*:\s*\[', raw)
        if match:
            index = match.end()
            decoder = json.JSONDecoder(parse_constant=reject_constant, parse_float=finite_float)
            while index < len(raw):
                while index < len(raw) and raw[index] in " \t\r\n,":
                    index += 1
                try:
                    item, index = decoder.raw_decode(raw, index)
                except (ValueError, RecursionError):
                    break
                if not isinstance(item, dict):
                    break
                candidates.append(item)
        return candidates, False, ["malformed_or_truncated_response"]


def _matches(text, needle):
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            break
        yield index
        start = index + 1


def ground(proposal, source, job, recipe, provenance):
    record_type = recipe.get("data_type", "term")
    errors = []
    if not isinstance(proposal, dict):
        return [], ["proposal_not_object"]
    allowed = {"expression", "language", "sense", "context", "start", "definition_quote", "attributes", "translation"}
    if set(proposal) - allowed:
        errors.append("unknown_proposal_fields")
    for key in recipe["output"]["required_fields"]:
        if key not in proposal:
            errors.append("required_field_missing:" + key)
    for key in ("expression", "language", "context"):
        if not isinstance(proposal.get(key), str) or not proposal[key].strip() or len(proposal[key]) > 100000:
            return [], errors + ["invalid_" + key]
    expression, language, context = proposal["expression"], proposal["language"], proposal["context"]
    if len(language) > 50 or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language):
        return [], errors + ["invalid_language_tag"]
    if "*" not in recipe["languages"] and language not in recipe["languages"] and language.split("-")[0] not in recipe["languages"]:
        errors.append("proposal_language_outside_recipe")
    sense = proposal.get("sense")
    if sense is not None and (not isinstance(sense, str) or not sense.strip() or len(sense) > 20000):
        sense = None
        errors.append("invalid_sense")
    if expression not in context:
        return [], errors + ["expression_absent_from_context"]
    window = source["text"][job["start"]:job["end"]]
    context_positions = list(_matches(window, context))
    if not context_positions:
        return [], errors + ["context_not_exact_in_window"]
    specified = proposal.get("start")
    possible = [(c, c + e) for c in context_positions for e in _matches(context, expression)]
    if specified is not None:
        if type(specified) is int and any(e == specified for _,e in possible):
            possible = [(c,e) for c,e in possible if e == specified]
        else:
            # A mistaken proposed offset must not erase exact grounded text.
            errors.append("offset_repaired_by_exact_context")
    attrs = proposal.get("attributes", {})
    if not isinstance(attrs, dict):
        attrs = {}
        errors.append("attributes_not_object")
    sanitized, reasons = {}, {}
    for key, spec in recipe["output"]["attributes"].items():
        value = attrs.get(key)
        typ = spec["type"]
        valid = value is None or (typ == "string" and isinstance(value, str)) or (typ == "boolean" and type(value) is bool) or (typ == "integer" and type(value) is int) or (typ == "number" and type(value) in {int,float}) or (typ == "array" and isinstance(value, list))
        if not valid:
            value = None
            errors.append("invalid_attribute:" + key)
        if value is None:
            reasons[key] = "not_provided_or_invalid_in_model_response"
            if spec["required"]:
                errors.append("required_attribute_unavailable:" + key)
        sanitized[key] = value
    if set(attrs) - set(sanitized):
        errors.append("unconfigured_attributes")
    translation = proposal.get("translation")
    if not recipe["output"]["translations"] or not isinstance(translation, str) or not translation.strip():
        translation = None
    quote = proposal.get("definition_quote")
    # Require a quote in this candidate's context; quotation is observed evidence,
    # never a verified semantic entailment claim about the proposed sense.
    if not isinstance(quote, str) or not quote.strip() or quote not in context:
        if quote is not None:
            errors.append("definition_quote_not_in_context")
        quote = None
    results = []
    for context_index, expression_index in possible:
        start = job["start"] + expression_index
        end = start + len(expression)
        community = source.get("community")
        # An unresolved meaning cannot justify merging different contextual
        # uses. Keep unknown-sense contexts separate until a human relates them.
        sense_identity = sense if sense is not None else {"unresolved_context":context}
        normalized = normalize(expression, language) if record_type == "term" else unicodedata.normalize("NFC", expression)
        # Nonlexical records identify an observed span in one source. Identical
        # opinions in different sources cannot establish identical attribution.
        tid = (ident("term", [normalized, language, community, sense_identity]) if record_type == "term"
               else ident("record", [record_type, source["source_id"], start, end,
                                      normalized, language, community, sense_identity]))
        oid = ident("occ", [source["source_id"], tid, start, end])
        locations = [b for b in source.get("blocks", []) if b["start"] < end and b["end"] > start]
        term = {"term_id": tid, "expression": expression, "original_spellings": [expression],
                "normalized_expression": normalized, "language": language,
                "record_id": tid, "record_type": record_type, "observed_text": expression,
                "text_origin": "observed_source", "interpretation": sense,
                "interpretation_origin": "model_generated" if sense else None,
                "interpretation_reason": None if sense else "not_proposed_or_unresolved",
                "community": community, "community_reason": None if community else "not_supplied_by_researcher_or_source",
                "sense": sense, "sense_reason": None if sense else "not_proposed_or_unresolved",
                "meaning_status": "model_proposed" if sense else "unresolved",
                "source_supported_definition": {"text": quote, "reason": None if quote else "no_exact_definition_quote",
                    "occurrence_id": oid if quote else None, "semantic_entailment_verified": False},
                "model_suggestions": {"attributes": sanitized, "attribute_null_reasons": reasons},
                "human_attributes": {}, "review_status": "unreviewed", "first_observed_in_corpus": source["retrieved_at"],
                "coinage_date": None, "coinage_date_reason": "corpus_observation_does_not_establish_coinage",
                "recipe_ids": [recipe["id"]]}
        occurrence = {"occurrence_id": oid, "term_id": tid, "source_id": source["source_id"],
                "record_id": tid, "record_type": record_type, "observed_text": expression,
                "expression": expression, "language": language, "start": start, "end": end,
                "offset_unit": "unicode_codepoint_in_frozen_extracted_text", "context": context,
                "context_start": job["start"] + context_index, "context_end": job["start"] + context_index + len(context),
                "source_locations": locations, "text_origin": "observed_source", "contexts": [{"text": context,
                    "start": job["start"] + context_index, "end": job["start"] + context_index + len(context)}],
                "translation": {"text": translation, "origin": "model_generated" if translation else None,
                                "reason": None if translation else "not_requested_or_not_provided"},
                "definition_quote": quote, "definition_quote_reason": None if quote else "no_exact_definition_quote",
                "model_attributes": sanitized, "attribute_null_reasons": reasons, "provenance": [provenance],
                "grounding": "exact_source_occurrence", "meaning_verified": False}
        results.append((term, occurrence))
    return results, errors
