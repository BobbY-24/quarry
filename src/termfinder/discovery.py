"""Finite discovery driven by recipe scope and explicit adapter results.

Source hyperlinks are navigation evidence. Extraction/model responses are never
accepted here and cannot issue tools or modify the recipe. Static manifests are
an implemented offline connector; a public HTTPS JSON search endpoint is an
implemented optional connector. Proprietary search SDKs/OCR are extension points.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from .sources import SafeFetcher, SourceError, UnsafeURLError, canonical_url, error_category, in_domain_scope, load_local, utc_now

DISCOVERY_VERSION = "termfinder-discovery/1.0"


class StaticManifestSearch:
    """Explicit JSON ``{results: {query: [{url: ...}|{path: ...}]}}``.

    A flat results list is also supported for a single search. File paths resolve
    relative to the manifest; remote result URLs remain subject to recipe scope.
    A manifest cannot modify limits, providers, prompts or source scope.
    """

    name = "static_manifest"

    def __init__(self, manifest: str | Path | dict, *, local_root: str | Path | None = None):
        if isinstance(manifest, dict):
            data = manifest
            self.base = Path.cwd()
        else:
            path = Path(manifest).resolve()
            if path.stat().st_size > 5_000_000:
                raise ValueError("search_manifest_too_large")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.base = path.parent
        self.local_root = Path(local_root).expanduser().resolve() if local_root is not None else self.base
        if not isinstance(data, dict) or set(data) - {"schema_version", "results", "description"}:
            raise ValueError("invalid_search_manifest")
        if data.get("schema_version", 1) != 1:
            raise ValueError("unsupported_search_manifest_version")
        self.results = data.get("results")
        if not isinstance(self.results, (dict, list)):
            raise ValueError("invalid_search_manifest_results")
        groups = self.results.values() if isinstance(self.results, dict) else [self.results]
        for group in groups:
            if not isinstance(group, list):
                raise ValueError("invalid_search_manifest_results")
            for item in group:
                if not isinstance(item, dict) or set(item) - {"url", "path", "title", "metadata"}:
                    raise ValueError("invalid_search_manifest_result")
                if ("url" in item) == ("path" in item):
                    raise ValueError("search_result_requires_one_locator")
                if not isinstance(item.get("url", item.get("path")), str):
                    raise ValueError("invalid_search_result_locator")
                if "metadata" in item and not isinstance(item["metadata"], dict):
                    raise ValueError("invalid_search_result_metadata")

    def search(self, query: str, limit: int) -> list[dict]:
        records = self.results.get(query, []) if isinstance(self.results, dict) else self.results
        result = []
        for item in records[:limit]:
            item = dict(item)
            if "path" in item:
                resolved = (self.base / item["path"]).resolve()
                forbidden_parts = {".ssh", ".aws", ".codex", ".agents", ".gnupg", ".git", ".config"}
                secret_names = {".netrc", ".pypirc", "credentials", "id_rsa", "id_ed25519"}
                if not resolved.is_relative_to(self.local_root) or forbidden_parts.intersection(resolved.parts):
                    item = {"rejection_reason": "local_path_out_of_scope"}
                elif resolved.name in secret_names or resolved.name.startswith(".env"):
                    item = {"rejection_reason": "credential_file_forbidden"}
                else:
                    item["path"] = str(resolved)
            result.append(item)
        return result


class HTTPJSONSearch:
    """Explicit public HTTPS GET search endpoint yielding ``{results:[...]}``.

    Endpoint domain scope is independent of source-domain scope. Authentication
    is intentionally unsupported: use a separately reviewed connector for APIs
    needing secrets. Responses only provide URL/title fields, never code/tools.
    ``cost_usd`` must be accounted through the recipe's search_cost_usd.
    """

    name = "http_json"

    def __init__(self, endpoint: str, *, query_parameter: str = "q", limit_parameter: str = "limit",
                 timeout: float = 20, max_bytes: int = 2_000_000, fetcher: SafeFetcher | None = None):
        endpoint = canonical_url(endpoint)
        if urlsplit(endpoint).scheme != "https":
            raise ValueError("search_endpoint_requires_https")
        if urlsplit(endpoint).query:
            raise ValueError("search_endpoint_query_not_allowed")
        if not query_parameter.isidentifier() or not limit_parameter.isidentifier():
            raise ValueError("invalid_search_query_parameter")
        self.endpoint, self.query_parameter, self.limit_parameter = endpoint, query_parameter, limit_parameter
        self.fetcher = fetcher or SafeFetcher({"domains": [urlsplit(endpoint).hostname]}, timeout, max_bytes)

    def search(self, query: str, limit: int) -> list[dict]:
        parts = urlsplit(self.endpoint)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                          urlencode({self.query_parameter: query, self.limit_parameter: limit}), ""))
        deadline = time.monotonic() + self.fetcher.timeout
        if not in_domain_scope(url, self.fetcher.scope):
            raise UnsafeURLError("search_endpoint_out_of_scope")
        addresses = self.fetcher._addresses(url, deadline)
        status, headers, body = self.fetcher._request(url, addresses, deadline)
        # Unlike source retrieval, search endpoint redirects are not followed.
        if status != 200:
            raise SourceError("search_endpoint_failed")
        if len(body) > self.fetcher.max_bytes:
            raise SourceError("search_response_too_large")
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise SourceError("search_response_invalid_json") from exc
        records = data.get("results") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise SourceError("search_response_invalid_schema")
        result = []
        for item in records[:limit]:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                raise SourceError("search_response_invalid_schema")
            # Discard unrelated fields. They have no executable authority.
            result.append({"url": item["url"], "title": str(item.get("title", ""))[:1000]})
        return result


def _safe_locator(item: dict) -> tuple[str | None, str | None]:
    if "path" in item:
        try:
            return str(Path(item["path"]).expanduser().resolve()), None
        except (TypeError, ValueError, OSError):
            return None, "invalid_local_locator"
    try:
        return canonical_url(item["url"]), None
    except (SourceError, KeyError, TypeError, ValueError):
        # Never record an invalid supplied URL; it could carry credentials.
        return None, "unsafe_or_invalid_url"


def _allowed_by_date(document: dict, dates: dict) -> tuple[bool, str | None]:
    date = document.get("publication_date")
    if not date:
        return (False, "publication_date_unavailable") if dates.get("unknown") == "exclude" else (True, None)
    if not isinstance(date, str) or len(date) < 10:
        return (False, "publication_date_unresolved") if dates.get("unknown") == "exclude" else (True, None)
    date = date[:10]
    for key, comparison in (("start", lambda a, b: a < b), ("end", lambda a, b: a > b)):
        if dates.get(key) and comparison(date, dates[key]):
            return False, "publication_date_out_of_scope"
    return True, None


def discover(recipe: dict, fetcher, search_adapter=None, seeds=(), decisions_path: str | Path | None = None,
             *, on_document=None, on_decision=None, on_state=None, is_cancelled=None) -> dict:
    """Collect bounded, source-derived documents and complete decision lineage.

    Requests and configured request prices are reserved before calling adapters,
    even on failure. They describe discovery charges/assumptions, not extraction
    spend. ``pending`` explicitly retains unfinished URLs and queries. The caller
    persists returned documents/decisions and may pass pending locators as seeds
    in a later authorized run. No infinite worker or persistent job is created.
    """
    settings = recipe["discovery"]
    scope = recipe["source_scope"]
    max_sources, max_hops, max_requests = (settings[k] for k in ("max_sources", "max_hops", "max_requests"))
    max_cost = float(settings["max_cost_usd"])
    search_cost, fetch_cost = (float(settings[k]) for k in ("search_cost_usd", "fetch_cost_usd"))
    if any(type(n) is not int or n < 0 for n in (max_sources, max_hops, max_requests)):
        raise ValueError("invalid_discovery_limits")
    if any(not math.isfinite(n) or n < 0 for n in (max_cost, search_cost, fetch_cost)):
        raise ValueError("invalid_discovery_costs")
    decisions: list[dict] = []
    documents: list[dict] = []
    excluded_documents: list[dict] = []
    pending: list[dict] = []
    queue = deque()
    seen = set()
    requests = 0
    source_attempts = 0
    spent = 0.0
    stopped_reason = None
    queries = deque(settings.get("queries", []) if search_adapter else [])

    def checkpoint(status=None):
        if on_state is None:
            return
        remaining = []
        for item in queue:
            value = {k: item[k] for k in ("locator", "parent", "hop", "query")}
            value["path" if "path" in item else "url"] = item["locator"]
            if item.get("metadata"):
                value["metadata"] = item["metadata"]
            remaining.append(value)
        remaining.extend({"query": query} for query in queries)
        on_state({"spent_usd": spent, "requests": requests, "source_attempts": source_attempts,
                  "pending": remaining, "status": status or ("partial" if stopped_reason else "running"),
                  "stop_reason": stopped_reason})

    def record(action, *, locator=None, parent=None, hop=0, query=None, reason=None, **extra):
        decision = {"decision_id": len(decisions) + 1, "discovery_version": DISCOVERY_VERSION,
                    "time": utc_now(), "action": action, "locator": locator,
                    "parent": parent, "hop": hop, "query": query, "reason": reason, **extra}
        decisions.append(decision)
        if decisions_path is not None:
            path = Path(decisions_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n")
        if on_decision is not None:
            on_decision(dict(decision))
        checkpoint()
        return decision

    def enqueue(item, *, parent=None, hop=0, query=None):
        if item.get("rejection_reason") in {"local_path_out_of_scope", "credential_file_forbidden"}:
            record("rejected", parent=parent, hop=hop, query=query, reason=item["rejection_reason"])
            return
        if type(hop) is not int or hop < 0:
            record("rejected", query=query, reason="invalid_hop")
            return
        locator, error = _safe_locator(item)
        if error:
            record("rejected", parent=parent, hop=hop, query=query, reason=error)
            return
        if "path" in item:
            if not scope.get("local", False):
                record("rejected", locator=locator, parent=parent, hop=hop, query=query, reason="local_sources_disabled")
                return
        elif not scope.get("domains") or not in_domain_scope(locator, scope):
            record("rejected", locator=locator, parent=parent, hop=hop, query=query, reason="domain_out_of_scope")
            return
        if hop > max_hops:
            record("rejected", locator=locator, parent=parent, hop=hop, query=query, reason="hop_limit")
            return
        if locator in seen:
            record("duplicate", locator=locator, parent=parent, hop=hop, query=query, reason="already_queued_or_fetched")
            return
        seen.add(locator)
        value = {**item, "locator": locator, "parent": parent, "hop": hop, "query": query}
        queue.append(value)
        record("queued", locator=locator, parent=parent, hop=hop, query=query)

    def reserve(cost):
        nonlocal requests, spent, stopped_reason
        if requests >= max_requests:
            stopped_reason = "request_limit"
            return False
        if spent + cost > max_cost + 1e-12:
            stopped_reason = "discovery_budget_exhausted"
            return False
        requests += 1
        spent = round(spent + cost, 12)
        return True

    for item in seeds:
        item = item if isinstance(item, dict) else {"url": item}
        enqueue(item, parent=item.get("parent"), hop=item.get("hop", 0), query=item.get("query"))
    if not settings.get("enabled", False):
        stopped_reason = "discovery_disabled"
    while not stopped_reason and (queue or queries):
        if is_cancelled is not None and is_cancelled():
            stopped_reason = "cancelled"
            break
        if source_attempts >= max_sources:
            stopped_reason = "source_limit"
            break
        # Complete explicit search queries before traversing found links.
        if queries:
            query = queries[0]
            if not reserve(search_cost):
                break
            record("search_started", query=query, adapter=getattr(search_adapter, "name", type(search_adapter).__name__),
                   request_number=requests, cost_usd=search_cost, outcome="uncertain_until_terminal_event")
            try:
                hits = search_adapter.search(query, max_sources)
                if not isinstance(hits, list):
                    raise ValueError("invalid_search_results")
                for hit in hits[:max_sources]:
                    if isinstance(hit, dict):
                        enqueue(hit, query=query)
                    else:
                        record("rejected", query=query, reason="invalid_search_result")
                queries.popleft()
                record("searched", query=query, adapter=getattr(search_adapter, "name", type(search_adapter).__name__),
                       request_number=requests, cost_usd=search_cost, results=len(hits), result_limit=max_sources)
            except KeyboardInterrupt:
                stopped_reason = "interrupted"
                record("search_interrupted", query=query, reason="outcome_uncertain",
                       request_number=requests, cost_usd=search_cost)
                break
            except Exception as exc:
                if queries and queries[0] == query:
                    queries.popleft()
                record("search_failed", query=query, reason=type(exc).__name__,
                       request_number=requests, cost_usd=search_cost)
            continue
        item = queue[0]
        is_local = "path" in item
        cached = (not is_local and callable(getattr(fetcher, "is_cached", None))
                  and fetcher.is_cached(item["locator"], item.get("metadata")))
        if not is_local and not cached and not reserve(fetch_cost):
            break
        source_attempts += 1
        context = {k: item[k] for k in ("locator", "parent", "hop", "query")}
        request_context = {"request_number": None if is_local or cached else requests,
                           "cost_usd": 0 if is_local or cached else fetch_cost, "cache_hit": bool(cached)}
        record("fetch_started", **context, **request_context, outcome="uncertain_until_terminal_event")
        try:
            metadata = dict(item.get("metadata") or {})
            if item.get("title"):
                metadata.setdefault("title", item["title"])
            document = load_local(item["path"], metadata) if is_local else fetcher.fetch(item["locator"], metadata)
            # Adapter implementations cannot widen the scope through redirects.
            if not is_local and not in_domain_scope(document["locator"], scope):
                raise UnsafeURLError("adapter_returned_out_of_scope_source")
            document["discovery_lineage"] = {"parent": item["parent"], "hop": item["hop"],
                                               "query": item["query"], "requested_locator": item["locator"]}
            allowed, reason = _allowed_by_date(document, recipe.get("dates", {}))
        except KeyboardInterrupt:
            stopped_reason = "interrupted"
            record("fetch_interrupted", **context, reason="outcome_uncertain",
                   **request_context)
            break
        except Exception as exc:
            queue.popleft()
            record("fetch_failed", **context, reason=type(exc).__name__,
                   category=error_category(exc),
                   **request_context)
            continue
        document["discovery_scope_status"] = "eligible" if allowed else "excluded_scope"
        if on_document is not None:
            on_document(document)
        queue.popleft()
        if not allowed:
            excluded_documents.append(document)
            record("excluded", **context, reason=reason, raw_sha256=document["raw_sha256"],
                   **request_context)
            continue
        documents.append(document)
        record("fetched", **context, resolved_locator=document["locator"], raw_sha256=document["raw_sha256"],
               **request_context)
        for link in document.get("links", []):
            enqueue({"url": link}, parent=document["locator"], hop=item["hop"] + 1)
    if stopped_reason:
        for item in queue:
            value = {k: item[k] for k in ("locator", "parent", "hop", "query")}
            value["path" if "path" in item else "url"] = item["locator"]
            value["reason"] = stopped_reason
            if item.get("metadata"):
                value["metadata"] = item["metadata"]
            pending.append(value)
            record("pending", **{k: value[k] for k in ("locator", "parent", "hop", "query")}, reason=stopped_reason)
        for query in queries:
            pending.append({"query": query, "reason": stopped_reason})
            record("pending", query=query, reason=stopped_reason)
    checkpoint("partial" if stopped_reason else "complete")
    return {"documents": documents, "excluded_documents": excluded_documents, "decisions": decisions,
            "spent_usd": spent, "requests": requests, "status": "partial" if stopped_reason else "complete",
            "stop_reason": stopped_reason, "pending": pending,
            "source_attempts": source_attempts,
            "costs": {"stage": "discovery", "actual_usd": spent,
                      "basis": "configured_adapter_request_prices", "requests": requests}}


# Stable CLI-facing name; the descriptive class name remains public as well.
StaticSearchAdapter = StaticManifestSearch
