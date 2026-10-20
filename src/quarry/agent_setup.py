"""Portable agent handoff and deterministic import gates. Never executes agents."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from .config import canonical, experts, load_profile, load_recipe, starter_recipe
from .sources import canonical_url, in_domain_scope
from .store import digest

VERSION = "agent-handoff-v1"
TYPES = ("term", "idea", "opinion", "sentence")
PROFILES = ("glm-deepseek", "gemini", "fake", "configured")
FORBIDDEN_PARTS = {".ssh", ".aws", ".config", ".codex", ".git", "keychains"}
SOURCE_SUFFIXES = {".html", ".htm", ".txt", ".md", ".markdown", ".pdf"}
BRIEF_KEYS = {"schema_version", "id", "data_type", "research_question", "inclusion_criteria",
              "exclusion_criteria", "languages", "communities", "domains", "local_roots",
              "budget_usd", "mode", "model_profile", "starter_recipe", "max_sources", "dates"}
BUNDLE_KEYS = {"schema_version", "brief_sha256", "recipe", "sources", "search_log", "sampling",
               "evaluation", "agent", "unresolved_questions"}
SOURCE_KEYS = {"source_key", "kind", "locator", "metadata", "why_selected", "origin", "search_refs", "family_id"}
META_KEYS = {"language", "community", "domain", "publication_date", "publication_date_reason",
             "title", "constraints", "turns"}


class FieldError(ValueError):
    """A fixed human-readable validator message containing no supplied values."""


def _text(value, label, limit=20000, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise FieldError(label + " needs bounded nonempty text")


def _strings(value, label, empty=False):
    if not isinstance(value, list) or len(value) > 1000 or (not empty and not value):
        raise FieldError(label + " needs a list")
    for item in value:
        _text(item, label, 2000)
    if len(set(value)) != len(value):
        raise FieldError(label + " contains duplicates")


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise FieldError("Missing or unsupported fields")


def _credential_free(value):
    """Reject explicit secret fields/patterns without echoing their contents."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in {"api_key", "apikey", "password", "secret", "access_token", "authorization", "credential", "credentials"}:
                raise ValueError("Credentials are forbidden in research plans")
            _credential_free(item)
    elif isinstance(value, list):
        for item in value:
            _credential_free(item)
    elif isinstance(value, str) and re.search(r"(?:\bsk-[A-Za-z0-9_-]{20,}|\bAIza[A-Za-z0-9_-]{25,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)", value):
        raise ValueError("Credential-like values are forbidden in research plans")


def _safe_path(value, roots, *, directory=False):
    _text(value, "Local location", 4000)
    path = Path(value).expanduser().resolve()
    if any(part.lower() in FORBIDDEN_PARTS or part.startswith(".") for part in path.parts):
        raise FieldError("Hidden and credential paths are not collection inputs")
    if directory:
        if path in {Path("/"), Path.home(), Path.home().parent, Path("/Users")} or not path.is_dir():
            raise FieldError("Choose a specific existing corpus directory")
    else:
        if not roots or not any(path.is_relative_to(Path(root)) for root in roots):
            raise FieldError("Local source is outside researcher-approved corpus directories")
        if path.suffix.lower() not in SOURCE_SUFFIXES or not path.is_file():
            raise FieldError("Local source must be an existing HTML, text, Markdown or PDF file")
        if path.stat().st_size > 50_000_000:
            raise FieldError("Local source exceeds 50 MB")
    return str(path)


def read_approved_local(locator, brief, metadata):
    """Open validated path components without following replacement symlinks."""
    from .sources import parse_document
    path = Path(_safe_path(locator, brief["local_roots"]))
    root = next(Path(root) for root in brief["local_roots"] if path.is_relative_to(Path(root)))
    # The explicitly selected corpus directory is the authority boundary. Open
    # it directly: walking '/' would need unrelated directory-read permission.
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.relative_to(root).parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 50_000_000:
                raise FieldError("Source is not a bounded regular file")
            data = stream.read(50_000_001)
            if len(data) > 50_000_000:
                raise FieldError("Source exceeds the file-size limit")
    finally:
        os.close(directory)
    media = "text/markdown" if path.suffix.lower() in {".md", ".markdown"} else mimetypes.guess_type(path.name)[0] or "text/plain"
    return parse_document(data, media, str(path), metadata)


def normalize_brief(value):
    if not isinstance(value, dict) or set(value) - BRIEF_KEYS:
        raise ValueError("Brief has unsupported fields")
    _credential_free(value)
    if len(canonical(value)) > 100000:
        raise ValueError("Research brief exceeds its size limit")
    kind = value.get("data_type", "term")
    if kind not in TYPES:
        raise ValueError("Choose term, idea, opinion or sentence")
    question = value.get("research_question")
    _text(question, "Research question")
    policy = value.get("starter_recipe", "neologisms" if kind == "term" else "jargon")
    recipe = starter_recipe(policy)
    brief = {"schema_version": 1, "id": value.get("id", "study-" + digest(question)[:12]),
        "data_type": kind, "research_question": question,
        "inclusion_criteria": value.get("inclusion_criteria", recipe["inclusion_criteria"] if kind == "term" else [f"Collect exact contiguous source passages expressing the requested {kind} units relevant to this question."]),
        "exclusion_criteria": value.get("exclusion_criteria", recipe["exclusion_criteria"] if kind == "term" else ["Exclude generated paraphrases, unsupported interpretations and noncontiguous evidence."]),
        "languages": value.get("languages", ["en"]), "communities": value.get("communities", ["research-corpus"]),
        "domains": value.get("domains", []), "local_roots": value.get("local_roots", []),
        "budget_usd": value.get("budget_usd", 0), "mode": value.get("mode", "broad"),
        "model_profile": value.get("model_profile", "glm-deepseek"), "starter_recipe": policy,
        "max_sources": value.get("max_sources", 30),
        "dates": value.get("dates", {"start": None, "end": None, "unknown": "include"})}
    if type(value.get("schema_version", 1)) is not int or value.get("schema_version", 1) != 1 or not isinstance(brief["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", brief["id"]):
        raise ValueError("Unsupported brief version or project identifier")
    for key in ("inclusion_criteria", "exclusion_criteria", "languages", "communities", "domains", "local_roots"):
        _strings(brief[key], key, empty=key in {"domains", "local_roots"})
    brief["local_roots"] = [_safe_path(p, [], directory=True) for p in brief["local_roots"]]
    if len(set(brief["local_roots"])) != len(brief["local_roots"]):
        raise ValueError("Corpus directories resolve to duplicates")
    if type(brief["max_sources"]) is not int or not 1 <= brief["max_sources"] <= 50000:
        raise ValueError("Source limit must be 1–50000")
    if brief["model_profile"] not in PROFILES:
        raise ValueError("Select a supported profile; provider settings stay outside agent plans")
    recipe.update(id=brief["id"], research_question=question, mode=brief["mode"],
                  languages=brief["languages"], communities=brief["communities"], dates=brief["dates"])
    recipe["source_scope"] = {"domains": brief["domains"] or ["local-only.invalid"], "local": bool(brief["local_roots"])}
    recipe["execution"]["budget_usd"] = brief["budget_usd"]
    load_recipe(recipe)  # Reuse the collector's bounded budget/scope/date checks.
    return brief


def planning_profile(brief, configured_profile=None):
    if brief["model_profile"] == "configured":
        if configured_profile is None:
            raise ValueError("Choose researcher compute before selecting the configured profile")
        return load_profile(configured_profile)
    return load_profile(brief["model_profile"])


def template_bundle(brief, configured_profile=None):
    recipe = starter_recipe(brief["starter_recipe"])
    recipe.update(id=brief["id"], data_type=brief["data_type"], research_question=brief["research_question"],
                  mode=brief["mode"], model_profile=brief["model_profile"],
                  languages=brief["languages"], communities=brief["communities"], dates=brief["dates"],
                  inclusion_criteria=brief["inclusion_criteria"], exclusion_criteria=brief["exclusion_criteria"])
    recipe["source_scope"] = {"domains": brief["domains"] or ["local-only.invalid"], "local": bool(brief["local_roots"])}
    recipe["discovery"].update(enabled=False, max_sources=brief["max_sources"], max_hops=0, max_cost_usd=0)
    recipe["execution"]["budget_usd"] = brief["budget_usd"]
    recipe["execution"]["stage_budgets"] = {stage: brief["budget_usd"] if stage in {"extraction", "specialist"} else 0
                                          for stage in recipe["execution"]["stage_budgets"]}
    for lens in recipe["specialist_lenses"]:
        lens["communities"] = brief["communities"]
    if brief["data_type"] != "term":
        # Synthetic English examples explain the span contract, not a domain
        # annotation rubric. The planning agent must adapt them to the study.
        examples = {
            "idea": (
                ("We propose adding bilingual signs to improve access.", "We propose adding bilingual signs to improve access.", "A proposal to add bilingual signs"),
                ("The heading reads Methods.", "Methods", None),
                ("Perhaps the service could open later.", "Perhaps the service could open later.", None)),
            "opinion": (
                ("I think bilingual signs improve access.", "I think bilingual signs improve access.", "Favorable opinion about bilingual signs"),
                ("The meeting begins at noon.", "The meeting begins at noon.", None),
                ("They say the service is unfair.", "They say the service is unfair.", None)),
            "sentence": (
                ("The service opens at noon.", "The service opens at noon.", None),
                ("Title: Opening hours", "Opening hours", None),
                ("Open later?", "Open later?", None)),
        }[brief["data_type"]]
        reasons = ("Synthetic example: preserve the complete observed wording; the interpretation remains generated.",
                   "Synthetic example: this unit is outside the example policy; adapt the actual criteria to the study.",
                   "Synthetic boundary case: decide its inclusion in the annotation rubric before collection; no inferred attribution or repaired text.")
        recipe["examples"] = {group: [dict(text=text, expression=span, language="en", sense=sense, reason=reason)]
                              for group, (text, span, sense), reason in zip(("positive", "negative", "boundary"), examples, reasons)}
        recipe["output"]["attributes"] = {
            "unit_category": {"type": "string", "required": False,
                              "description": "Optional model-proposed category under the study's annotation rubric; requires review."},
            "attribution": {"type": "string", "required": False,
                            "description": "Optional model-proposed source attribution; not verified speaker identity."}}
        recipe["specialist_lenses"] = [
            {"id": "glm-explicit-units", "model": "glm", "communities": brief["communities"],
             "lens": f"Attend to explicit {brief['data_type']} spans under this recipe, retaining every grounded qualifying unit."},
            {"id": "deepseek-contextual-units", "model": "deepseek", "communities": brief["communities"],
             "lens": f"Attend to context-dependent {brief['data_type']} spans and attribution in the source; preserve original wording and all qualifying units."}]
        recipe["discovery"]["queries"] = [brief["research_question"]]
    profile = planning_profile(brief, configured_profile)
    profile_aliases = list(profile["models"])
    for index, lens in enumerate(recipe["specialist_lenses"]):
        if lens["model"] not in profile_aliases:
            lens["model"] = profile_aliases[index % len(profile_aliases)]
            lens["id"] = lens["model"] + "-focus-" + str(index + 1)
    output_limit = min(m["output_token_ceiling"] for m in profile["models"].values())
    recipe["execution"]["max_output_tokens"] = min(recipe["execution"]["max_output_tokens"], output_limit)
    recipe["execution"]["recovery_output_tokens"] = min(recipe["execution"]["recovery_output_tokens"], output_limit)
    return {"schema_version": 1, "brief_sha256": digest(brief), "recipe": recipe, "sources": [], "search_log": [],
            "sampling": {"unit": "source", "strategy": "Specify selection before collection", "stopping_rule": f"At most {brief['max_sources']} sources", "limitations": ["Agent source suggestions do not establish an exhaustive population."]},
            "evaluation": {"unit": "occurrence", "grouping": "source_family", "holdout_fraction": 0.2,
                           "matching": "exact_span", "exhaustive_gold_required": True},
            "agent": {"tool": "template", "model": None, "session_reference": None, "generated_at": None},
            "unresolved_questions": ["Supply permitted sources and task-specific examples; confirm the sampling and annotation policy."]}


def contract():
    return {"version": VERSION, "bundle_fields": sorted(BUNDLE_KEYS), "source_fields": sorted(SOURCE_KEYS),
            "source_example": {"source_key": "source-001", "kind": "url", "locator": "https://example.org/article",
                "metadata": {"language": "en", "community": "research-corpus", "domain": "example.org",
                             "publication_date": None, "publication_date_reason": "not_available",
                             "constraints": {"content_origin": "published_human_text", "license": None, "license_reason": "verify_before_sharing", "permitted_use": None, "permitted_use_reason": "researcher_review_required", "redistribution": None, "redistribution_reason": "not_established"}},
                "why_selected": "Explain relevance and selection", "origin": "agent_suggested", "search_refs": [], "family_id": None},
            "search_example": {"search_id": "search-001", "query": "actual query", "provider": "actual service or not_executed", "executed_at": None,
                "results": [{"locator": "https://example.org/article", "selected": True, "reason": "Relevant source candidate"}], "limitations": ["Record search limitations and exclusions."]},
            "unknown_policy": "Use null plus a reason; do not fabricate verification, dates, permissions or search history.",
            "unit_contract": "expression must be an exact contiguous observed span for every data_type; sense/attributes/translation are generated suggestions."}


def build_prompt(brief, configured_profile=None):
    return "\n\n".join([
        "V6 RESEARCH SETUP REQUEST — " + VERSION,
        "You are the researcher's planning assistant. Convert their brief into ONE JSON bundle for V6. Return JSON only, no code fences. You may propose sources and policy; the deterministic collector validates and runs the work. Do not execute V6, install code, contact people, publish/upload data, read unrelated local files or call paid collection services. Only use your existing researcher-authorized search workflow, at most 5 search queries and the brief's source limit. Do not assume this prompt grants extra tools or permissions.",
        "Researcher-controlled brief (do not increase its scope, languages, communities, source limit, budget, mode or profile):\n" + json.dumps(brief, ensure_ascii=False, indent=2),
        "Fill the complete template below. Preserve the brief hash and research question. Retain the researcher's criteria; refine examples and optional attributes. For term units distinguish new senses/cultural entities/jargon by policy. For ideas, opinions and sentences, expression is a verbatim supporting span, never your paraphrase. sense is your proposed interpretation. Collection does not verify semantic truth, novelty, sentiment or speaker identity.",
        "Each selected source needs a supported local file inside an approved corpus directory or a public URL in permitted domains, original language/community, null+reason for missing publication dates, source-use constraints, why_selected, source origin, search_refs and a family_id if known. Do not invent existing local paths. Cite search history only when executed; record queries, service, time if available, examined results and exclusion reasons. Unverified candidate URLs are allowed and will be fetched later explicitly. Never include credentials, private access links, source content copied from unrelated files, executable instructions or provider endpoints.",
        "Unknown research choices go in unresolved_questions; do not silently decide contested inclusion/sampling rules. An unresolved bundle cannot be applied. Agent-selected sources are not an exhaustive population. Specify sampling unit/strategy/stopping rule/limitations. Keep held-out complete sources independent of prompt tuning; opinions/ideas require an independently defined annotation rubric. Do not use model agreement or candidate counts as recall.",
        "Keep discovery disabled: V6 will ingest only the reviewed finite source list. All tools and credentials stay under the researcher's control. V6 prepare/validate/apply makes no model calls; remote fetching is a later explicit step. Repair errors by returning a revised bundle, not by weakening checks.",
        "Contract:\n" + json.dumps(contract(), ensure_ascii=False, indent=2),
        "Complete editable bundle template:\n" + json.dumps(template_bundle(brief, configured_profile), ensure_ascii=False, indent=2),
    ])


def validate_bundle(value, brief, configured_profile=None):
    """Return stable diagnostics. Never fetch, read source contents or call models."""
    errors, warnings = [], []

    def issue(path, code, message):
        errors.append({"path": path, "code": code, "message": message})

    def check(path, callback):
        try:
            callback()
        except (ValueError, TypeError, KeyError, AttributeError, OSError, OverflowError, RecursionError) as error:
            # These validators generate fixed messages; no input value appears.
            message = str(error) if isinstance(error, FieldError) else "Check required fields, types and bounded values here."
            issue(path, "invalid_value", message or "Check required fields, types and bounded values here.")

    try:
        _credential_free(value)
        if len(canonical(value).encode("utf-8")) > 32_000_000:
            raise ValueError("Oversize bundle")
        _keys(value, BUNDLE_KEYS)
    except (ValueError, TypeError, RecursionError):
        return {"valid": False, "errors": [{"path": "$", "code": "unsafe_or_invalid_bundle", "message": "Return the required JSON object, under 32 MB, without credentials or unsupported fields."}], "warnings": [], "summary": None, "bundle_sha256": None,
                "repair_prompt": "Return one JSON object following the V6 handoff contract. Remove credentials, unsupported fields and code; preserve the researcher's scope."}
    bundle_hash = digest(value)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        issue("schema_version", "unsupported_version", "Use bundle schema version 1.")
    if value["brief_sha256"] != digest(brief):
        issue("brief_sha256", "stale_brief", "Use the latest V6-generated request; this plan belongs to another brief.")
    recipe = None
    try:
        recipe = load_recipe(value["recipe"])
        profile = planning_profile(brief, configured_profile)
        passes = experts(recipe, profile)
        if any(recipe["execution"]["recovery_output_tokens"] > profile["models"][e["model"]]["output_token_ceiling"] for e in passes):
            raise ValueError("Output cap")
    except (ValueError, TypeError, KeyError, OSError):
        issue("recipe", "invalid_recipe", "Use a complete valid V6 recipe and supported output limits.")
    if recipe:
        if recipe["id"] != brief["id"]:
            issue("recipe.id", "changed_project_id", "Keep the identifier generated for this research brief.")
        for key in ("research_question", "mode", "model_profile"):
            if recipe[key] != brief[key]:
                issue("recipe." + key, "changed_researcher_choice", "Keep the researcher's selected " + key + ".")
        if recipe.get("data_type", "term") != brief["data_type"]:
            issue("recipe.data_type", "changed_unit", "Keep the selected collection unit.")
        for key in ("languages", "communities"):
            if not set(recipe[key]).issubset(brief[key]):
                issue("recipe." + key, "scope_expansion", "Use only researcher-approved " + key + ".")
        if not set(recipe["source_scope"]["domains"]).issubset(brief["domains"] or ["local-only.invalid"]):
            issue("recipe.source_scope.domains", "scope_expansion", "Use only researcher-approved domains.")
        if not recipe["source_scope"]["domains"]:
            issue("recipe.source_scope.domains", "empty_scope", "Keep the explicit domain list or local-only.invalid; an empty list permits public URLs.")
        if recipe["source_scope"]["local"] and not brief["local_roots"]:
            issue("recipe.source_scope.local", "local_not_authorized", "Choose a corpus directory in the brief before proposing local files.")
        for key in ("inclusion_criteria", "exclusion_criteria"):
            if not set(brief[key]).issubset(recipe[key]):
                issue("recipe." + key, "removed_researcher_criteria", "Retain the researcher's explicit criteria.")
        bounds, actual = brief["dates"], recipe["dates"]
        if (bounds["start"] and (not actual["start"] or actual["start"] < bounds["start"])) or (bounds["end"] and (not actual["end"] or actual["end"] > bounds["end"])) or (bounds["unknown"] == "exclude" and actual["unknown"] != "exclude"):
            issue("recipe.dates", "scope_expansion", "Keep the researcher's date limits and unknown-date rule.")
        if recipe["discovery"]["enabled"]:
            issue("recipe.discovery.enabled", "discovery_not_authorized", "Keep discovery disabled; this workflow uses the reviewed finite source list.")
        if recipe["execution"]["budget_usd"] > brief["budget_usd"] or any(v > brief["budget_usd"] for v in recipe["execution"]["stage_budgets"].values()):
            issue("recipe.execution", "budget_expansion", "Do not increase the researcher's spending limit.")

    sources = value["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= brief["max_sources"]:
        issue("sources", "source_limit", "Supply at least one source and stay within the researcher's source limit.")
        sources = []
    seen, locators, search_ids = set(), set(), set()
    logs = value["search_log"]
    if not isinstance(logs, list) or len(logs) > 5:
        issue("search_log", "search_limit", "Provide a list of at most five actual search records.")
        logs = []
    for i, log in enumerate(logs):
        def log_check(log=log):
            _keys(log, {"search_id", "query", "provider", "executed_at", "results", "limitations"})
            for key in ("search_id", "query", "provider"):
                _text(log[key], key, 2000)
            if log["search_id"] in search_ids:
                raise ValueError("Duplicate search")
            search_ids.add(log["search_id"])
            if log["executed_at"] is not None:
                datetime.fromisoformat(log["executed_at"].replace("Z", "+00:00"))
            _strings(log["limitations"], "Search limitations", empty=True)
            if not isinstance(log["results"], list) or len(log["results"]) > 1000:
                raise ValueError("Search results")
            for result in log["results"]:
                _keys(result, {"locator", "selected", "reason"})
                _text(result["locator"], "Search result", 4000)
                if urlsplit(result["locator"]).scheme:
                    canonical_url(result["locator"])
                if type(result["selected"]) is not bool:
                    raise ValueError("Selection flag")
                _text(result["reason"], "Selection reason")
        check(f"search_log[{i}]", log_check)

    for i, source in enumerate(sources):
        def source_check(source=source):
            _keys(source, SOURCE_KEYS)
            if not isinstance(source["source_key"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", source["source_key"]) or source["source_key"] in seen:
                raise FieldError("Source keys must be unique lowercase identifiers")
            seen.add(source["source_key"])
            _text(source["why_selected"], "Source selection reason")
            if source["origin"] not in {"agent_suggested", "researcher_supplied"}:
                raise FieldError("Choose agent_suggested or researcher_supplied as selection origin")
            _strings(source["search_refs"], "Search references", empty=True)
            if not set(source["search_refs"]).issubset(search_ids):
                raise FieldError("Each search reference must identify a search_log entry")
            _text(source["family_id"], "Family identifier", 2000, nullable=True)
            if source["kind"] == "local":
                locator = _safe_path(source["locator"], brief["local_roots"])
                if recipe and not recipe["source_scope"]["local"]:
                    raise FieldError("Local inputs are disabled in the proposed recipe")
            elif source["kind"] == "url":
                locator = canonical_url(source["locator"])
                host = urlsplit(locator).hostname
                if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
                    raise FieldError("Private and localhost URLs are not supported source inputs")
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if address and not address.is_global:
                    raise FieldError("Private and localhost URLs are not supported source inputs")
                if not brief["domains"] or not in_domain_scope(locator, brief["domains"]) or (recipe and not in_domain_scope(locator, recipe["source_scope"])):
                    raise FieldError("Source URL is outside the researcher-approved domains")
            else:
                raise FieldError("Source kind must be local or url")
            if locator in locators:
                raise FieldError("The source list contains a duplicate canonical location")
            locators.add(locator)
            metadata = source["metadata"]
            _keys(metadata, {"language", "community", "domain", "publication_date", "publication_date_reason", "constraints"}, META_KEYS)
            for key in ("language", "community", "domain"):
                _text(metadata[key], key, 2000)
            if metadata["language"] not in {"mul", "und"} and "*" not in brief["languages"] and metadata["language"] not in brief["languages"] and metadata["language"].split("-")[0] not in brief["languages"]:
                raise FieldError("Source language is outside the researcher-approved languages")
            if "*" not in brief["communities"] and metadata["community"] not in brief["communities"]:
                raise FieldError("Source community is outside the researcher-approved communities")
            if recipe and "*" not in recipe["communities"] and metadata["community"] not in recipe["communities"]:
                raise FieldError("Source community must also match the proposed recipe routes")
            if recipe and metadata["language"] not in {"mul", "und"} and "*" not in recipe["languages"] and metadata["language"] not in recipe["languages"] and metadata["language"].split("-")[0] not in recipe["languages"]:
                raise FieldError("Source language is outside the proposed recipe")
            if metadata["publication_date"] is None:
                _text(metadata["publication_date_reason"], "Missing date reason")
                if recipe and recipe["dates"]["unknown"] == "exclude":
                    raise FieldError("This recipe excludes sources without publication dates")
            else:
                date.fromisoformat(metadata["publication_date"][:10])
                if recipe and ((recipe["dates"]["start"] and metadata["publication_date"][:10] < recipe["dates"]["start"]) or (recipe["dates"]["end"] and metadata["publication_date"][:10] > recipe["dates"]["end"])):
                    raise FieldError("Source publication date is outside the proposed recipe")
            _keys(metadata["constraints"], {"content_origin"}, metadata["constraints"])
            _text(metadata["constraints"]["content_origin"], "Content origin", nullable=True)
            if metadata["constraints"]["content_origin"] is None:
                _text(metadata["constraints"].get("content_origin_reason"), "Missing source-origin reason")
        check(f"sources[{i}]", source_check)

    def sampling_check():
        _keys(value["sampling"], {"unit", "strategy", "stopping_rule", "limitations"})
        for key in ("unit", "strategy", "stopping_rule"):
            _text(value["sampling"][key], key)
        _strings(value["sampling"]["limitations"], "Sampling limitations", empty=True)
    check("sampling", sampling_check)

    def evaluation_check():
        e = value["evaluation"]
        _keys(e, {"unit", "grouping", "holdout_fraction", "matching", "exhaustive_gold_required"})
        if e["unit"] not in {"occurrence", "source_term"} or e["grouping"] != "source_family" or e["matching"] not in {"exact_span", "source_expression"} or e["exhaustive_gold_required"] is not True:
            raise ValueError("Evaluation unit")
        if (e["unit"] == "occurrence") != (e["matching"] == "exact_span") or brief["data_type"] != "term" and e["unit"] != "occurrence":
            raise FieldError("Ideas, opinions and sentences need occurrence/exact_span matching; keep term matching consistent too")
        if type(e["holdout_fraction"]) not in {int, float} or not 0 < e["holdout_fraction"] < 1:
            raise ValueError("Holdout fraction")
    check("evaluation", evaluation_check)

    def agent_check():
        _keys(value["agent"], {"tool", "model", "session_reference", "generated_at"})
        _text(value["agent"]["tool"], "Agent tool", 2000)
        for key in ("model", "session_reference"):
            _text(value["agent"][key], key, 2000, nullable=True)
        if value["agent"]["generated_at"] is not None:
            datetime.fromisoformat(value["agent"]["generated_at"].replace("Z", "+00:00"))
    check("agent", agent_check)
    check("unresolved_questions", lambda: _strings(value["unresolved_questions"], "Unresolved questions", empty=True))
    if value["unresolved_questions"]:
        issue("unresolved_questions", "research_choices_pending", "Resolve the listed research choices with your agent before applying.")
    warnings.append({"code": "agent_claims_unverified", "message": "Source suggestions, dates, permissions and sampling claims require researcher review; validation is not verification of those claims."})
    if any(s.get("kind") == "url" for s in sources if isinstance(s, dict)):
        warnings.append({"code": "remote_sources_staged", "message": "URLs are staged. Applying the plan does not fetch them; use the explicit approved-source ingest step."})
    if recipe:
        for lens in recipe["specialist_lenses"]:
            if not set(lens["communities"]).issubset(brief["communities"]):
                issue("recipe.specialist_lenses", "route_outside_scope", "Route lenses only to researcher-approved communities.")
    from .costs import estimate
    summary = {"data_type": brief["data_type"], "mode": brief["mode"], "profile": brief["model_profile"],
               "source_count": len(sources), "local_sources": sum(s.get("kind") == "local" for s in sources if isinstance(s, dict)),
               "remote_sources": sum(s.get("kind") == "url" for s in sources if isinstance(s, dict)),
               "budget_usd": recipe["execution"]["budget_usd"] if recipe else brief["budget_usd"],
               "recipe_question": brief["research_question"], "sampling": value["sampling"], "evaluation": value["evaluation"],
               "estimate": estimate(recipe, profile, links=len(sources)) if recipe and sources and not errors else None}
    return {"valid": not errors, "errors": errors, "warnings": warnings, "summary": summary, "bundle_sha256": bundle_hash,
            "repair_prompt": "Repair this V6 bundle without changing the researcher-controlled brief. Return only the corrected complete JSON. Diagnostics:\n" + json.dumps(errors, ensure_ascii=False, indent=2) if errors else None}


def write_handoff(setup, out):
    out = Path(out)
    content = {"brief.json": canonical(setup["brief"]) + "\n", "prompt.md": setup["prompt"] + "\n",
               "bundle-template.json": canonical(setup["starter_bundle"]) + "\n", "contract.json": canonical(contract()) + "\n"}
    content["manifest.json"] = canonical({"version": VERSION, "brief_sha256": setup["brief_sha256"], "prompt_sha256": setup["prompt_sha256"],
        "files": {name: digest(data) for name, data in content.items()}, "authorization": "No model calls, source fetch or publication occurs during handoff creation."}) + "\n"
    out.mkdir(parents=True, exist_ok=True)
    for name, text in content.items():
        target = out / name
        if target.is_symlink() or target.exists() and target.read_text(encoding="utf-8") != text:
            raise FileExistsError("Choose a fresh handoff directory; different existing artifacts are preserved")
    for name, text in content.items():
        target = out / name
        if not target.exists():
            target.write_text(text, encoding="utf-8")
    return {"out": str(out.resolve()), "files": sorted(content), "brief_sha256": setup["brief_sha256"], "prompt_sha256": setup["prompt_sha256"]}


def write_plan_inputs(setup, profile, out):
    """Materialize all collector inputs deterministically; never execute them."""
    bundle = setup["bundle"]
    documents = {"brief.json": setup["brief"], "bundle.json": bundle, "recipe.json": bundle["recipe"],
                 "profile.json": profile, "sources.json": bundle["sources"], "evaluation.json": bundle["evaluation"],
                 "sampling.json": bundle["sampling"], "search_log.json": bundle["search_log"], "agent.json": bundle["agent"]}
    documents.update({"metadata-" + source["source_key"] + ".json": source["metadata"] for source in bundle["sources"]})
    content = {name: canonical(value) + "\n" for name, value in documents.items()}
    content["prompt.md"] = setup["prompt"] + "\n"
    content["urls.txt"] = "".join(canonical_url(s["locator"]) + "\n" for s in bundle["sources"] if s["kind"] == "url")
    content["manifest.json"] = canonical({"version": VERSION, "brief_sha256": setup["brief_sha256"],
        "bundle_sha256": setup["bundle_sha256"], "prompt_sha256": setup["prompt_sha256"],
        "files": {name: digest(data) for name, data in content.items()},
        "execution": "These files are data, not scripts. Applying stages remote sources and makes no model calls."}) + "\n"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, content_text in content.items():
        path = out / name
        if path.is_symlink() or path.exists() and path.read_text(encoding="utf-8") != content_text:
            raise FileExistsError("Different compiled inputs already exist; preserve them and use a new plan")
    for name, content_text in content.items():
        path = out / name
        if not path.exists():
            path.write_text(content_text, encoding="utf-8")
    return {"out": str(out.resolve()), "files": sorted(content)}
