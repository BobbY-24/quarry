"""Bounded newline-delimited MCP adapter for a fixed project or study workspace.

No HTTP listener, client sampling, generated tools, subprocesses, or credentials
are introduced here. Collection delegates to the same deterministic workflow.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import uuid

from . import __version__
from .agent_setup import _credential_free
from .config import canonical
from .project import Project
from .store import digest, now

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
MAX_MESSAGE_BYTES = 32_000_000
MAX_RESULT_BYTES = 262_144
MAX_WORKSPACE_ENTRIES = 1000
REVIEW_SECTIONS = ("summary", "brief", "recipe", "profile", "sampling", "evaluation",
                   "search_log", "agent", "binding", "costs", "source_plan", "source_provenance",
                   "failures", "pending_sources", "freeze")


class ToolFailure(ValueError):
    """Only fixed adapter-authored diagnostics may become public tool errors."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.public_message = code, message


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def decode_json(value):
    def finite_float(text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError("Nonfinite JSON")
        return number
    return json.loads(value, object_pairs_hook=_unique_object,
                      parse_float=finite_float,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def _shape(value, depth=0):
    if depth > 32:
        raise ValueError("JSON nesting exceeds the finite bound")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError("Invalid object key")
            _shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 100_000:
            raise ValueError("List exceeds the finite bound")
        for item in value:
            _shape(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON")


def _schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required),
            "additionalProperties": False}


ID = {"type": "string", "minLength": 1, "maxLength": 128}
BOOL = {"type": "boolean"}
PAGE = {"type": "integer", "minimum": 0, "maximum": 10_000_000}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}
OBJECT = {"type": "object"}


def _tool(name, description, properties=None, required=(), readonly=False):
    return {"name": name, "description": description, "inputSchema": _schema(properties, required),
            "annotations": {"readOnlyHint": readonly, "destructiveHint": False,
                            "openWorldHint": name in {"prepare_review", "collect"}}}


TOOLS = [
    _tool("prepare_study", "Describe a study within the researcher's explicit source, language, model and finite budget bounds; returns an inert planning contract, prompt and starter bundle. No collection.", {"brief": OBJECT}, ("brief",)),
    _tool("submit_plan", "Validate an agent-produced bundle against the current brief. Save valid plans as the current proposal; never ingest, approve or collect here.", {"bundle": OBJECT}, ("bundle",)),
    _tool("inspect_plan", "Inspect the current validated proposal or applied plan before any source is ready: exact chunks of its policy, source declarations, sampling, validation and ingestion state. The submitted bundle hash binds every page; this never freezes, approves, fetches or collects.", {"plan_sha256": ID, "section": {"type": "string", "enum": ["brief", "recipe", "sources", "sampling", "evaluation", "search_log", "agent", "validation", "ingestion"]}, "offset": PAGE, "length": {"type": "integer", "minimum": 1, "maximum": 12000}}, ("plan_sha256", "section"), readonly=True),
    _tool("prepare_review", "Prepare the current valid proposal: ingest local approved sources, optionally fetch only its explicit URL list, freeze blank source-level evaluation packets and calculate costs. No model extraction.", {"fetch_remote": BOOL}),
    _tool("inspect_review", "Read one exact reviewed plan section as a bounded page of top-level fields or list items. Includes its section hash and cursors; use review_text for any long nested field that is clipped.", {"review_id": ID, "section": {"type": "string", "enum": list(REVIEW_SECTIONS)}, "offset": PAGE, "limit": LIMIT}, ("review_id", "section"), readonly=True),
    _tool("review_sources", "Read a bounded page of the exact concrete review's full source declarations, ingestion summaries and retained provenance. Pages remain bound to the same review ID; use review_text for large nested values.", {"review_id": ID, "offset": PAGE, "limit": LIMIT}, ("review_id",), readonly=True),
    _tool("review_text", "Read an exact Unicode-character chunk of a plan section or its RFC6901 JSON pointer. No files or URLs are opened from the pointer. Concatenate chunks with the same value hash to inspect every long field inside the harness.", {"review_id": ID, "section": {"type": "string", "enum": list(REVIEW_SECTIONS)}, "json_pointer": {"type": "string", "maxLength": 1000}, "offset": PAGE, "length": {"type": "integer", "minimum": 1, "maximum": 12000}}, ("review_id", "section"), readonly=True),
    _tool("approve_review", "Record the client's declaration that the researcher approved this concrete review. This assertion is recorded, not independently authenticated.", {"review_id": ID, "researcher_approved": BOOL, "approval_reference": {"type": "string", "minLength": 1, "maxLength": 1000}}, ("review_id", "researcher_approved", "approval_reference")),
    _tool("collect", "Start or resume approved collection asynchronously. The launch-time paid gate, review hashes, engine scope, finite budgets, retries and evidence validation remain in force.", {"review_id": ID, "max_jobs": {"type": "integer", "minimum": 1, "maximum": 50_000}}, ("review_id",)),
    _tool("status", "Read persistent progress, cost reservations, processing failures and the current worker state. Coverage is not measured recall.", readonly=True),
    _tool("cancel", "Request cancellation of this project's current collection. Already dispatched requests may complete or have uncertain billing outcomes."),
    _tool("records", "Read a bounded page of collected records; use inspect_record for exact evidence.", {"offset": PAGE, "limit": LIMIT, "query": {"type": "string", "maxLength": 400}}, readonly=True),
    _tool("inspect_record", "Inspect one saved record with a bounded page of source evidence, provenance and reversible annotation history.", {"record_id": ID, "evidence_offset": PAGE, "limit": LIMIT}, ("record_id",), readonly=True),
    _tool("inspect_source", "Read a bounded Unicode-character excerpt from an already ingested source ID. Does not fetch a URL or open a supplied path.", {"source_id": ID, "offset": PAGE, "length": {"type": "integer", "minimum": 1, "maximum": 12_000}}, ("source_id",), readonly=True),
    _tool("annotate", "Save a model suggestion separately from human marks, or relay an explicitly approved human annotation. Suggestions cannot approve/reject records or change the approved subset.", {"record_id": ID, "status": {"type": "string", "enum": ["unreviewed", "approved", "rejected", "needs_review"]}, "note": {"type": "string", "maxLength": 4000}, "attributes": OBJECT, "annotation_origin": {"type": "string", "enum": ["model_suggestion", "human_relay"]}, "researcher_approved": BOOL, "approval_reference": {"type": "string", "maxLength": 2000}}, ("record_id", "status")),
    _tool("undo_annotation", "Undo a saved human-relay annotation while retaining history; requires an explicit researcher declaration.", {"annotation_id": ID, "researcher_approved": BOOL, "approval_reference": {"type": "string", "minLength": 1, "maxLength": 2000}}, ("annotation_id", "researcher_approved", "approval_reference")),
    _tool("versions", "List immutable saved dataset versions; no models or new snapshots.", readonly=True),
    _tool("release", "Freeze or reuse a saved dataset and export every configured format to a fixed version-specific directory inside the project. Includes publication findings; never publishes or uploads.", {"name": {"type": "string", "minLength": 1, "maxLength": 128}, "version_id": ID}, ("name",)),
]

WORKSPACE_TOOLS = [
    _tool("list_studies", "List a bounded page of immediate safe study folders under the launch-time workspace; at most 1000 entries are scanned, hidden/unmanaged/symlink entries are not opened.", {"offset": PAGE, "limit": LIMIT}, readonly=True),
    _tool("create_study", "Create and select a fresh safe-slug study inside the fixed workspace. An optional validated brief prepares inert study inputs only; no source/model calls. Existing folders are never overwritten.", {"slug": {"type": "string", "minLength": 1, "maxLength": 64}, "brief": OBJECT}, ("slug",)),
    _tool("open_study", "Select an existing safe-slug V6 study immediately inside the fixed workspace. Cannot follow symlinks, traverse paths or switch during active collection.", {"slug": {"type": "string", "minLength": 1, "maxLength": 64}}, ("slug",)),
]


def _validate(schema, value):
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError("Unsupported arguments")
        if set(schema.get("required", ())) - set(value):
            raise ValueError("Missing required arguments")
        for key in set(value) & set(props):
            _validate(props[key], value[key])
    elif kind == "string":
        if not isinstance(value, str) or "\x00" in value or len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", MAX_MESSAGE_BYTES):
            raise ValueError("Invalid bounded string")
    elif kind == "integer":
        if type(value) is not int or not schema.get("minimum", -(2**63)) <= value <= schema.get("maximum", 2**63 - 1):
            raise ValueError("Invalid bounded integer")
    elif kind == "boolean" and type(value) is not bool:
        raise ValueError("Expected a boolean")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Unsupported choice")


def _preview(value, depth=0):
    """Return valid bounded JSON; mark clipping instead of emitting broken JSON."""
    if depth > 12:
        return {"preview_only": True, "reason": "nested_detail_omitted"}
    if isinstance(value, str) and len(value) > 24_000:
        return {"preview_only": True, "text": value[:24_000], "total_characters": len(value)}
    if isinstance(value, list):
        items = [_preview(v, depth + 1) for v in value[:100]]
        return items if len(value) <= 100 else {"preview_only": True, "items": items, "total_items": len(value)}
    if isinstance(value, dict):
        items = {key: _preview(v, depth + 1) for key, v in list(value.items())[:200]}
        return items if len(value) <= 200 else {"preview_only": True, "fields": items, "total_fields": len(value)}
    return value


def _routing_summary(value, depth=0, budget=None):
    """Keep identifiers usable when large research detail exceeds stdio limits.

    Fixed field names and primitive bounds prevent the fallback from recursively
    copying the large source/manifest payload that triggered the size limit.
    """
    if not isinstance(value, dict) or depth > 2:
        return {}
    budget = [32_000] if budget is None else budget
    keys = {"review_id", "version_id", "out", "ready", "started", "running", "name",
            "brief_sha256", "bundle_sha256", "approval_id", "annotation_id", "suggestion_id",
            "paid_transport_permitted", "budget_usd", "source_count", "eligible_source_count",
            "data_type", "mode", "model_profile", "status", "stop_reason", "stale", "approved",
            "check_deferred", "integrity_passed", "failure_count", "unresolved_audit_count",
            "study_slug", "workspace", "selected_study", "section", "section_sha256", "value_sha256",
            "json_pointer", "representation", "start", "end", "total_characters", "plan_sha256",
            "stage", "inspection_only", "next_offset", "complete_chunk", "complete_value"}
    result = {}
    for key in sorted(keys & set(value), key=lambda k: (k not in {"review_id", "version_id", "out", "ready"}, k)):
        item = value[key]
        if item is None or type(item) in {bool, int} or isinstance(item, float) and math.isfinite(item):
            cost = len(key) + len(canonical(item)) + 4
        elif isinstance(item, str) and len(item) <= (4096 if key == "out" else 1024):
            cost = len(key) + len(canonical(item).encode("utf-8")) + 4
        else:
            continue
        if budget[0] >= cost:
            result[key] = item
            budget[0] -= cost
    for key in ("review", "freeze", "approval", "worker_result", "status", "audit"):
        if isinstance(value.get(key), dict):
            nested = _routing_summary(value[key], depth + 1, budget)
            if nested:
                result[key] = nested
    for key in ("counts", "jobs", "page"):
        if isinstance(value.get(key), dict):
            counts = {k: v for k, v in list(value[key].items())[:30]
                      if isinstance(k, str) and len(k) <= 100 and type(v) is int}
            cost = len(canonical(counts).encode("utf-8")) + len(key) + 4
            if counts and budget[0] >= cost:
                result[key] = counts
                budget[0] -= cost
    return result


def _contains_preview(value):
    if isinstance(value, dict):
        return value.get("preview_only") is True or any(_contains_preview(v) for v in value.values())
    return isinstance(value, list) and any(_contains_preview(v) for v in value)


def _result(value, error=False):
    data = _preview(value)
    body = canonical(data)
    oversized = len(body.encode("utf-8")) > MAX_RESULT_BYTES - 1800
    if oversized:
        data = {**_routing_summary(value), "preview_only": True,
                "reason": "result_exceeds_transport_preview",
                "guidance": "Routing identifiers remain usable. Use inspect_review, review_sources and review_text to inspect the complete plan, costs and provenance inside this harness; use paged evidence tools for records. Full dataset records and audit detail remain in frozen exports."}
    elif isinstance(data, dict) and _contains_preview(data):
        data["preview_only"] = True
        data["guidance"] = "Some nested detail is clipped. Use inspect_review, review_sources and review_text for complete harness inspection, and smaller evidence pages for records. Do not treat this preview as complete."
    if isinstance(data, dict) and data.get("preview_only") is True and isinstance(value, dict) and (value.get("review_id") or isinstance(value.get("review"), dict) and value["review"].get("review_id")):
        data["full_review_required_before_approval"] = True
        data["approval_guidance"] = "Before relaying approval, disclose this preview and inspect the complete source list, source problems and cost estimate with the paged review tools inside this harness. The browser is optional. A review ID alone is not approval."
    body = canonical(data)
    return {"content": [{"type": "text", "text": body}], "isError": error}


class MCPServer:
    def __init__(self, project=None, *, workspace=None, allow_paid=False):
        if (project is None) == (workspace is None):
            raise ValueError("Choose one fixed project or one bounded workspace")
        self.project = project
        self.workspace = None
        self.workspace_fd = None
        self.study_slug = None
        self.study_identity = None
        if workspace is not None:
            path = Path(workspace).expanduser().absolute()
            if (path in {Path("/"), Path.home(), Path.home().parent, Path("/Users"), Path("/home"),
                         Path("/tmp"), Path("/private/tmp"), Path("/private"), Path("/var")}
                    or any(part.startswith(".") or part in {"..", "."} for part in path.parts)
                    or any(part.lower() in {"keychains", "credentials"} for part in path.parts)
                    or any(parent.is_symlink() for parent in (path, *path.parents))
                    or not path.is_dir()):
                raise ValueError("Workspace must be a specific existing nonhidden directory without symbolic links")
            self.workspace = path.resolve()
            self.workspace_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.allow_paid = bool(allow_paid)
        self.initialized = False
        self.ready = False
        self.worker = None
        self.worker_result = None
        self.worker_error = None
        self.worker_lock = threading.Lock()
        self.resources_lock = threading.Lock()
        self.closing = threading.Event()

    @property
    def tools(self):
        return TOOLS + WORKSPACE_TOOLS if self.workspace is not None else TOOLS

    @staticmethod
    def _slug(value):
        if (not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value)
                or value.lower() in {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
                or re.fullmatch(r"(?:com|lpt)[0-9]", value)):
            raise ToolFailure("invalid_study_slug", "Use a lowercase portable study slug of 1–64 characters, starting with a letter; paths, hidden names and reserved device names are forbidden.")
        return value

    def _workspace_guard(self):
        if self.workspace is None:
            raise ToolFailure("fixed_project_mode", "This connection has one fixed project. Study selection is available only in a server launched with --workspace.")
        if self.workspace_fd is None:
            raise ToolFailure("server_closing", "The workspace connection is closed.")
        try:
            current, opened = self.workspace.lstat(), os.fstat(self.workspace_fd)
        except OSError:
            raise ToolFailure("workspace_changed", "The launch-time workspace is no longer available. Restore it or reconnect to the intended directory.") from None
        if (not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
                or any(parent.is_symlink() for parent in self.workspace.parents)):
            raise ToolFailure("workspace_changed", "The launch-time workspace was moved, replaced or linked. Reconnect after restoring the intended directory.")

    def _study_path(self, slug, *, existing):
        self._workspace_guard()
        slug = self._slug(slug)
        path = self.workspace / slug
        if existing:
            try:
                info = os.stat(slug, dir_fd=self.workspace_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise ToolFailure("study_not_found", "Choose a saved study returned by list_studies.") from None
            if not stat.S_ISDIR(info.st_mode):
                raise ToolFailure("unsafe_study_path", "Study folders must be real immediate workspace directories, never symbolic links or files.")
            for filename in ("project.sqlite3", "project.sqlite3-wal", "project.sqlite3-shm", ".collection.lock"):
                candidate = path / filename
                if candidate.is_symlink() or candidate.exists() and not candidate.is_file():
                    raise ToolFailure("unsafe_study_path", "Study database and lock files must be regular files without symbolic links.")
            if not (path / "project.sqlite3").is_file():
                raise ToolFailure("study_not_found", "This directory is not a saved V6 study.")
        elif path.exists() or path.is_symlink():
            raise ToolFailure("study_already_exists", "Create uses a fresh slug and never overwrites a folder. Use open_study for an existing study.")
        return path

    def _workspace_project(self, path, slug):
        """Admit a project before Project.resolve or SQLite can open it.

        Directory descriptors and adapter guards reject replacements observed
        before each legacy path-based operation. Python SQLite still opens path
        names: this logical workspace boundary is not an OS filesystem sandbox
        against a malicious concurrent same-user filesystem actor.
        """
        self._workspace_guard()
        try:
            directory = os.open(slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=self.workspace_fd)
        except OSError:
            raise ToolFailure("study_changed", "The intended study directory changed before admission. Restore it before opening the study.") from None
        try:
            opened = os.fstat(directory)
            identity = (opened.st_dev, opened.st_ino)
        finally:
            os.close(directory)

        def guard(candidate_path):
            self._workspace_guard()
            if Path(candidate_path) != path:
                raise ToolFailure("study_changed", "The admitted study path resolved outside its selected workspace directory.")
            try:
                current = os.stat(slug, dir_fd=self.workspace_fd, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != identity:
                    raise ToolFailure("study_changed", "The admitted study directory was replaced or linked. Restore the intended study before continuing.")
                child = os.open(slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=self.workspace_fd)
                try:
                    retained = os.fstat(child)
                    if (retained.st_dev, retained.st_ino) != identity:
                        raise ToolFailure("study_changed", "The admitted study directory changed while opening its guarded files.")
                    for filename in ("project.sqlite3", "project.sqlite3-wal", "project.sqlite3-shm", ".collection.lock"):
                        try:
                            info = os.stat(filename, dir_fd=child, follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            raise ToolFailure("unsafe_study_path", "Study database and lock files must remain regular files without symbolic links.")
                finally:
                    os.close(child)
            except OSError:
                raise ToolFailure("study_changed", "The admitted study directory or guarded files are no longer safely available.") from None

        guard(path)
        candidate = Project(path, path_guard=guard)
        guard(candidate.path)
        return candidate, identity

    def _require_project(self):
        if self.project is None:
            raise ToolFailure("study_not_open", "Create or open a study in the launch-time workspace first.")
        if self.workspace is not None:
            path = self._study_path(self.study_slug, existing=True)
            info = path.lstat()
            if self.project.path != path or self.study_identity != (info.st_dev, info.st_ino):
                raise ToolFailure("study_changed", "The selected study directory changed. Stop and restore the intended workspace study.")
        return self.project

    def _switch_idle(self):
        self._idle()
        if self.project is not None:
            with self._require_project()._lock():
                pass  # Includes a collector in another process, not just this worker.

    def _workspace_call(self, name, arguments):
        self._workspace_guard()
        if name == "list_studies":
            slugs = []
            scanned = 0
            with os.scandir(self.workspace_fd) as entries:
                for count, entry in enumerate(entries):
                    if count >= MAX_WORKSPACE_ENTRIES:
                        raise ToolFailure("workspace_entry_limit", "Workspace admission is bounded to 1000 immediate entries. Use a smaller study workspace; no further folders were opened.")
                    scanned += 1
                    try:
                        slug = self._slug(entry.name)
                    except ToolFailure:
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        self._study_path(slug, existing=True)
                    except ToolFailure:
                        continue
                    slugs.append(slug)
            slugs.sort()
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 50)
            return {"workspace": str(self.workspace), "selected_study": self.study_slug,
                    "studies": [{"slug": slug, "selected": slug == self.study_slug} for slug in slugs[offset:offset + limit]],
                    "page": {"offset": offset, "limit": limit, "total": len(slugs),
                             "next_offset": offset + limit if offset + limit < len(slugs) else None},
                    "entry_limit": MAX_WORKSPACE_ENTRIES, "scanned_entries": scanned}
        self._switch_idle()
        slug = self._slug(arguments["slug"])
        inventory = self._workspace_call("list_studies", {})  # Finite admission inventory.
        if name == "create_study":
            # Validate before creating anything. Creation is a preparation action.
            brief = None
            if "brief" in arguments:
                from .agent_setup import normalize_brief
                brief = normalize_brief(arguments["brief"])
            if inventory["scanned_entries"] >= MAX_WORKSPACE_ENTRIES:
                raise ToolFailure("workspace_entry_limit", "The workspace has reached its finite admission limit.")
            path = self._study_path(slug, existing=False)
            os.mkdir(slug, mode=0o700, dir_fd=self.workspace_fd)
            candidate, identity = self._workspace_project(path, slug)
            setup = candidate.prepare_agent_setup(brief) if brief is not None else None
        else:
            path = self._study_path(slug, existing=True)
            candidate, identity = self._workspace_project(path, slug)
            with candidate._lock():
                pass
            setup = None
        candidate._guard_path(candidate.path)
        self.project, self.study_slug, self.study_identity = candidate, slug, identity
        self.worker = self.worker_result = self.worker_error = None
        return {"study_slug": slug, "project": str(path), "selected": True,
                "created": name == "create_study", "paid_transport_permitted": self.allow_paid,
                **({"brief": setup["brief"], "brief_sha256": setup["brief_sha256"]} if setup else {}),
                "next_step": "Prepare this study's bounded brief and submit its plan; no sources or models have been dispatched."}

    def _review_section(self, review_id, section):
        p = self._require_project()
        # _review_call owns the same admission lock, so the retained review,
        # complete plan and captured provenance cannot change between pages.
        review, _ = self._workflow()._check_review_unlocked(p, review_id, require_ready=False)
        if review.get("review_id") != review_id:
            raise ToolFailure("review_stale", "Choose the current concrete review ID returned by prepare_review or status.")
        if review.get("stale"):
            raise ToolFailure("review_stale", "The concrete plan changed. Prepare its current review before inspecting or approving it.")
        setup = p.agent_setup()
        bundle = setup.get("bundle", {})
        if section == "summary":
            value = {key: val for key, val in review.items() if key not in {"sources", "failures", "pending_sources", "binding", "freeze", "estimate"}}
            value["cost_range_usd"] = review.get("estimate", {}).get("range_usd")
            value["failure_count"] = len(review.get("failures", []))
            value["pending_source_count"] = len(review.get("pending_sources", []))
        elif section == "brief":
            value = setup["brief"]
        elif section in {"recipe", "profile"}:
            value = p.recipe if section == "recipe" else p.profile
        elif section in {"sampling", "evaluation", "search_log", "agent", "source_plan"}:
            value = bundle["sources" if section == "source_plan" else section]
        elif section == "binding":
            value = review["binding"]
        elif section == "costs":
            value = {"estimate": review["estimate"], "budget_usd": review["budget_usd"],
                     "external_agent_costs": review["external_agent_costs"]}
        elif section in {"failures", "pending_sources", "freeze"}:
            value = review[section]
        else:
            value = []
            for source in review["sources"]:
                saved = p.store.get("sources", source["source_id"]) if source.get("source_id") else None
                value.append({"source_key": source["source_key"], "source_id": source.get("source_id"),
                    "ingestion_status": source["status"], "provenance": {k: v for k, v in saved.items()
                        if k not in {"text", "blocks", "outlinks"}} if saved else None,
                    "provenance_reason": None if saved else source.get("reason") or "source_not_ingested"})
        return review, deepcopy(value)

    def _review_call(self, name, arguments):
        with self._require_project()._lock():
            return self._review_call_unlocked(name, arguments)

    def _plan_inspection(self, arguments):
        p = self._require_project()
        with p._lock():
            setup = p.agent_setup()
            plan = p.store.read_setting("agent_proposal") or setup.get("bundle")
            checksum = digest(plan) if isinstance(plan, dict) else None
            if (checksum != arguments["plan_sha256"] or not plan
                    or plan.get("brief_sha256") != setup.get("brief_sha256")
                    or digest(setup.get("brief")) != setup.get("brief_sha256")):
                raise ToolFailure("plan_stale", "Choose the validated current bundle hash returned by submit_plan; changed briefs or proposals invalidate earlier inspection pages.")
            from .publication import verify_history
            history = p.store.read_setting("agent_workflow") or []
            if not verify_history(history) or not any(e["event_type"] in {"bundle_validated", "plan_applied"}
                    and e["payload"].get("bundle_sha256") == checksum
                    and e["payload"].get("brief_sha256") == setup["brief_sha256"]
                    and e["payload"].get("validation", {}).get("valid") is True
                    and digest(e["payload"].get("submitted_bundle")) == checksum for e in history):
                raise ToolFailure("plan_validation_unverified", "The saved proposal does not match its deterministic validation history. Submit and validate the intended current plan again.")
            applied = setup.get("applied") and setup.get("bundle_sha256") == checksum
            section = arguments["section"]
            if section == "brief":
                value = setup["brief"]
            elif section == "validation":
                value = {"valid": True, "bundle_sha256": checksum, "brief_sha256": setup["brief_sha256"],
                         "reason": "matching_deterministic_validation_in_integrity_history"}
            elif section == "ingestion":
                mapping = p.store.read_setting("agent_source_map") or {}
                failures = {row.get("locator"): row.get("reason") for row in p.store.iter_rows("audit")
                            if row.get("stage") == "parsing"}
                value = []
                for source in plan["sources"]:
                    sid = mapping.get(checksum + ":" + source["source_key"])
                    retained = p.store.get("sources", sid) if sid else None
                    value.append({"source_key": source["source_key"], "source_id": sid,
                        "locator": source["locator"], "kind": source["kind"],
                        "status": "captured" if retained else "not_captured",
                        "historical_parse_failure": failures.get(source["locator"]),
                        "text_sha256": retained.get("text_sha256") if retained else None,
                        "text_sha256_reason": None if retained else "source_not_ingested"})
            else:
                value = plan[section]
            text = value if isinstance(value, str) else canonical(value)
            start, length = arguments.get("offset", 0), arguments.get("length", 8000)
            if start > len(text):
                raise ToolFailure("invalid_plan_offset", "The character offset exceeds the selected plan section.")
            end = min(len(text), start + length)
            return {"plan_sha256": checksum, "brief_sha256": setup["brief_sha256"],
                    "stage": "applied" if applied else "proposed", "section": section,
                    "section_sha256": digest(value), "value_sha256": digest(text),
                    "representation": "original_string" if isinstance(value, str) else "canonical_json",
                    "text": text[start:end], "start": start, "end": end,
                    "total_characters": len(text), "next_offset": end if end < len(text) else None,
                    "offset_unit": "Unicode code points", "complete_chunk": True,
                    "complete_value": start == 0 and end == len(text), "inspection_only": True,
                    "note": "Inspection never authorizes collection. Prepare a concrete source/cost review when usable sources are captured, then relay the actual researcher decision."}

    def _review_call_unlocked(self, name, arguments):
        review_id = arguments["review_id"]
        if name == "review_sources":
            review, declared = self._review_section(review_id, "source_plan")
            _, provenance = self._review_section(review_id, "source_provenance")
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 10)
            items = [{"index": i, "declaration": declared[i], "inspection": review["sources"][i],
                      "source_provenance": provenance[i]} for i in range(offset, min(len(declared), offset + limit))]
            return {"review_id": review_id, "sources": items, "source_plan_sha256": digest(declared),
                    "page": {"offset": offset, "limit": limit, "total": len(declared),
                             "next_offset": offset + limit if offset + limit < len(declared) else None},
                    "page_selection_complete": True, "note": "Use review_text section=source_plan with json_pointer=/INDEX for any clipped declaration; provenance is available in source_provenance."}
        section = arguments["section"]
        review, value = self._review_section(review_id, section)
        section_hash = digest(value)
        if name == "review_text":
            pointer = arguments.get("json_pointer", "")
            if pointer:
                if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
                    raise ToolFailure("invalid_review_pointer", "Use an RFC6901 JSON pointer within the selected review section; the empty pointer reads the complete section.")
                for component in pointer[1:].split("/"):
                    component = component.replace("~1", "/").replace("~0", "~")
                    if isinstance(value, dict) and component in value:
                        value = value[component]
                    elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", component) and int(component) < len(value):
                        value = value[int(component)]
                    else:
                        raise ToolFailure("invalid_review_pointer", "The pointer does not address a value in this exact review section.")
            text = value if isinstance(value, str) else canonical(value)
            offset, length = arguments.get("offset", 0), arguments.get("length", 8000)
            if offset > len(text):
                raise ToolFailure("invalid_review_offset", "The character offset exceeds the selected value length.")
            end = min(len(text), offset + length)
            return {"review_id": review_id, "section": section, "section_sha256": section_hash,
                    "json_pointer": pointer, "value_sha256": digest(text), "representation": "original_string" if isinstance(value, str) else "canonical_json",
                    "text": text[offset:end], "offset_unit": "Unicode code points", "start": offset,
                    "end": end, "total_characters": len(text), "next_offset": end if end < len(text) else None,
                    "complete_value": offset == 0 and end == len(text), "complete_chunk": True}
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 20)
        items = [{"key": key, "value": val} for key, val in value.items()] if isinstance(value, dict) else [{"index": i, "value": val} for i, val in enumerate(value)]
        return {"review_id": review_id, "section": section, "section_sha256": section_hash,
                "items": items[offset:offset + limit], "page": {"offset": offset, "limit": limit,
                    "total": len(items), "next_offset": offset + limit if offset + limit < len(items) else None},
                "page_selection_complete": True, "note": "Nested values may be clipped by the transport. Read any such value exactly with review_text and the same section/review ID."}

    def _workflow(self):
        from . import workflow
        return workflow

    @property
    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def _idle(self):
        if self.running:
            raise ToolFailure("collection_running", "Cancel or wait for collection to stop before modifying the study.")
        if self.closing.is_set():
            raise ToolFailure("server_closing", "The connection is closing. Reconnect to the same project to resume.")

    def _review_ready(self, review_id, *, collection=False):
        if not self.project.recipe or not self.project.profile:
            raise ToolFailure("study_not_prepared", "Prepare a study, submit a valid plan and prepare its concrete collection review first.")
        review = self._workflow().current_review(self.project)
        if review.get("review_id") != review_id or review.get("stale"):
            raise ToolFailure("review_stale", "Sources, settings or approval changed. Prepare the current plan and review its new estimate.")
        if not review.get("ready"):
            raise ToolFailure("sources_pending", "Fetch or repair the pending approved sources before approving or collecting.")
        if collection and not review.get("approval"):
            raise ToolFailure("approval_required", "Show the concrete source list and estimate, then relay the researcher's explicit decision through approve_review.")
        if collection and not self.allow_paid and any(provider["adapter"] != "fake" for provider in self.project.profile["providers"].values()):
            raise ToolFailure("paid_launch_gate_disabled", "This server permits offline fake collection only. A separately authorized real study needs a server launched with --allow-paid; tools cannot enable it.")

    def _start(self, review_id, max_jobs=None):
        with self.worker_lock:
            self._idle()
            # Synchronous preflight must fail before a background success response.
            self._review_ready(review_id, collection=True)
            self._workflow().check_review(self.project, review_id, allow_paid=self.allow_paid)
            self.worker_result = self.worker_error = None

            def run():
                try:
                    if self.closing.is_set():
                        return
                    self.worker_result = self._workflow().run_review(
                        self.project, review_id, allow_paid=self.allow_paid, max_jobs=max_jobs)
                except Exception as error:
                    self.worker_error = {"type": type(error).__name__,
                                         "message": "Collection stopped; inspect persistent status and recovery records."}
                finally:
                    if self.closing.is_set():
                        try:
                            self.project.cancel()
                        except (OSError, RuntimeError, ValueError):
                            pass
                        finally:
                            self._close_workspace_resources()

            self.worker = threading.Thread(target=run, name="v6-mcp-collection", daemon=True)
            self.worker.start()
        return {"started": True, "review_id": review_id, "paid_transport_permitted": self.allow_paid,
                "next_step": "Poll status; cancel requests a bounded stop. No output is a recall estimate."}

    def call_tool(self, name, arguments):
        tool = next((t for t in self.tools if t["name"] == name), None)
        if tool is None:
            raise LookupError("Unknown tool")
        try:
            _validate(tool["inputSchema"], arguments)
            _shape(arguments)
            _credential_free(arguments)
        except (ValueError, RecursionError):
            raise ToolFailure("invalid_arguments", "Use the tool's advertised schema and bounded values. Unsupported fields, credentials and nonfinite values are forbidden.") from None
        if name in {"list_studies", "create_study", "open_study"}:
            return self._workspace_call(name, arguments)
        if name == "status" and self.project is None:
            self._workspace_guard()
            return {"workspace": str(self.workspace), "selected_study": None, "running": False,
                    "paid_transport_permitted": self.allow_paid,
                    "next_step": "Create or open a study to begin. This connection reuses the launch-time workspace."}
        p = self._require_project()
        if name in {"prepare_study", "submit_plan", "prepare_review", "approve_review", "release"}:
            self._idle()
        if name in {"inspect_review", "review_sources", "review_text"}:
            return self._review_call(name, arguments)
        if name == "inspect_plan":
            return self._plan_inspection(arguments)
        if name == "prepare_study":
            setup = p.prepare_agent_setup(arguments["brief"])
            return {"brief": setup["brief"], "brief_sha256": setup["brief_sha256"],
                    "prompt": setup["prompt"], "starter_bundle": setup["starter_bundle"],
                    "paid_transport_permitted": self.allow_paid,
                    "next_step": "Draft a bounded bundle and submit_plan; researcher reviews the concrete prepared study before collection."}
        if name == "submit_plan":
            bundle = arguments["bundle"]
            report = p.validate_agent_bundle(bundle)
            if report["valid"]:
                with p._lock(), p.store.connection() as db:
                    setup = p.agent_setup()
                    if setup.get("brief_sha256") != bundle.get("brief_sha256"):
                        raise ValueError("Brief changed during validation")
                    p.store.setting("agent_proposal", deepcopy(bundle), db)
                    p.store.setting("ui_setup_revision", digest({"brief_sha256": setup["brief_sha256"],
                        "proposal_sha256": digest(bundle), "stage": "proposal"}), db)
            return report
        if name == "prepare_review":
            if not p.store.read_setting("agent_proposal") and not p.agent_setup().get("applied"):
                raise ToolFailure("plan_required", "Call submit_plan with a valid bundle before preparing collection.")
            return self._workflow().prepare_review(p, bundle=p.store.read_setting("agent_proposal"),
                                                   fetch_remote=arguments.get("fetch_remote", False))
        if name == "approve_review":
            if arguments["researcher_approved"] is not True:
                raise ToolFailure("approval_declaration_required", "Relay an existing explicit researcher decision with researcher_approved=true and its approval reference.")
            self._review_ready(arguments["review_id"])
            return self._workflow().approve_review(p, arguments["review_id"],
                approval_reference=arguments["approval_reference"], approval_origin="agent_relay")
        if name == "collect":
            return self._start(arguments["review_id"], arguments.get("max_jobs"))
        if name == "status":
            status = p.status()
            return {"status": status, "running": self.running,
                    "worker_result": self.worker_result, "worker_error": self.worker_error,
                    "paid_transport_permitted": self.allow_paid,
                    "review": self._workflow().current_review(p)}
        if name == "cancel":
            p.cancel()
            return {"cancellation_requested": True, "running": self.running,
                    "note": "In-flight provider requests may complete; unknown outcomes retain reservations and require explicit resolution."}
        if name == "records":
            page = p.page_inventory(**arguments)
            return {"records": page["records"], "page": page["page"]}
        if name == "inspect_record":
            page = p.page_inventory(record_id=arguments["record_id"],
                evidence_offset=arguments.get("evidence_offset", 0), limit=arguments.get("limit", 20))
            if page["selected_record"] is None:
                raise ValueError("Unknown record ID")
            return {key: page[key] for key in ("selected_record", "occurrences", "sources", "annotations", "relations", "page")}
        if name == "inspect_source":
            source = p.store.get("sources", arguments["source_id"])
            if source is None:
                raise ValueError("Unknown source ID")
            start = arguments.get("offset", 0)
            length = arguments.get("length", 4000)
            text = source["text"]
            if start > len(text):
                raise ValueError("Source offset exceeds text")
            end = min(len(text), start + length)
            blocks = [b for b in source.get("blocks", ()) if b.get("start", 0) < end and b.get("end", len(text)) > start][:100]
            return {"source": {k: v for k, v in source.items() if k not in {"text", "blocks", "outlinks"}},
                    "excerpt": {"text": text[start:end], "start": start, "end": end,
                                "offset_unit": "Unicode code points", "total_characters": len(text)},
                    "blocks": blocks, "next_offset": end if end < len(text) else None}
        if name == "annotate":
            if not p.store.get("terms", arguments["record_id"]):
                raise ValueError("Unknown record ID")
            origin = arguments.get("annotation_origin", "model_suggestion")
            attributes = arguments.get("attributes", {})
            if len(canonical(attributes).encode("utf-8")) > 8000:
                raise ValueError("Attributes exceed the annotation bound")
            if origin == "model_suggestion":
                if arguments["status"] not in {"needs_review", "unreviewed"} or arguments.get("researcher_approved"):
                    raise ValueError("Model suggestions cannot approve/reject records or declare human approval")
                aid = "audit_" + uuid.uuid4().hex
                p.store.put("audit", aid, {"audit_id": aid, "source_id": None, "job_id": None,
                    "stage": "human_review_suggestion", "reason": "agent_annotation_suggestion",
                    "created_at": now(), "review_status": "unresolved", "record_id": arguments["record_id"],
                    "proposal": {"status": arguments["status"], "note": arguments.get("note", ""),
                                 "attributes": attributes, "origin": "model_suggestion"}})
                return {"suggestion_id": aid, "origin": "model_suggestion", "changes_human_review_status": False}
            self._declared_approval(arguments)
            # Nested Store operations reuse this transaction: no observer can
            # freeze a transient default-human row lacking the relay provenance.
            with p.store.connection():
                aid = p.annotate(arguments["record_id"], arguments["status"], arguments.get("note", ""),
                                 attributes=attributes, actor="researcher_via_agent")
                row = p.store.get("annotations", aid)
                row.update(origin="human_relay", human_approval_declared=True,
                           approval_reference=arguments["approval_reference"],
                           approval_identity_verified=False)
                p.store.put("annotations", aid, row)
            return {"annotation_id": aid, "origin": "human_relay", "approval_identity_verified": False}
        if name == "undo_annotation":
            self._declared_approval(arguments)
            with p.store.connection():
                p.undo_annotation(arguments["annotation_id"])
                row = p.store.get("annotations", arguments["annotation_id"])
                row["undo_approval_reference"] = arguments["approval_reference"]
                row["undo_approval_origin"] = "agent_relay"
                p.store.put("annotations", arguments["annotation_id"], row)
            return {"annotation_id": arguments["annotation_id"], "active": False, "history_retained": True}
        if name == "versions":
            return {"versions": p.versions()}
        if name == "release":
            if arguments.get("version_id") is not None and not re.fullmatch(r"dataset_[0-9a-f]{32}", arguments["version_id"]):
                raise ToolFailure("invalid_version_id", "Choose an existing saved dataset ID returned by versions; version IDs cannot be paths.")
            return self._workflow().release_dataset(p, arguments["name"], version_id=arguments.get("version_id"))
        raise LookupError("Unknown tool")

    @staticmethod
    def _declared_approval(arguments):
        if arguments.get("researcher_approved") is not True or not isinstance(arguments.get("approval_reference"), str) or not arguments["approval_reference"].strip():
            raise ValueError("Explicit researcher approval and its reference are required")

    def dispatch(self, request):
        """Process one JSON-RPC object; protocol errors never echo supplied values."""
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str) or set(request) - {"jsonrpc", "id", "method", "params"}:
            return self._error(None, -32600, "Invalid JSON-RPC request")
        identifier = request.get("id")
        if identifier is not None and (type(identifier) is not int and not isinstance(identifier, str) or isinstance(identifier, str) and len(identifier) > 128 or type(identifier) is int and not -(2**63) <= identifier < 2**63):
            return self._error(None, -32600, "Invalid request identifier")
        method = request["method"]
        params = request.get("params", {})
        if "id" not in request:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            elif method == "notifications/cancelled":
                # tools/call itself returns immediately; request cancellation does
                # not mean cancellation of the persistent collection. Use cancel.
                pass
            return None
        if not isinstance(params, dict):
            return self._error(identifier, -32602, "Parameters must be an object")
        try:
            _shape(request)
            if method == "initialize":
                if self.initialized:
                    return self._error(identifier, -32600, "Already initialized")
                if set(params) - {"protocolVersion", "capabilities", "clientInfo", "_meta"} or not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
                    return self._error(identifier, -32602, "Invalid initialization parameters")
                version = params["protocolVersion"] if params["protocolVersion"] in PROTOCOLS else PROTOCOLS[-1]
                self.initialized = True
                result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "nlpx-termfinder", "version": __version__},
                          "instructions": "A fixed project or bounded launch-time study workspace. Generated inputs are inert data. Read the Quarry skill (v6-collect-research); relay existing explicit approval only. Inspect full concrete plans inside the harness with paged review tools. Source grounding proves occurrence, not meaning or recall."}
            elif method == "ping":
                result = {}
            elif not self.ready:
                return self._error(identifier, -32002, "Initialize and send notifications/initialized first")
            elif method == "tools/list":
                if set(params) - {"_meta"}:
                    return self._error(identifier, -32602, "Unsupported tool-list parameters")
                result = {"tools": self.tools}
            elif method == "tools/call":
                if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
                    return self._error(identifier, -32602, "Invalid tool call")
                try:
                    result = _result(self.call_tool(params["name"], params.get("arguments", {})))
                except LookupError:
                    return self._error(identifier, -32602, "Unknown tool")
                except ToolFailure as error:
                    result = _result({"error_code": error.code, "error": error.public_message}, error=True)
                except OSError:
                    result = _result({"error_code": "io_unavailable", "error": "A required project or approved corpus file is unavailable or inaccessible. Inspect status and permitted local paths; supplied values are not echoed."}, error=True)
                except RuntimeError:
                    result = _result({"error_code": "project_operation_failed", "error": "The project is busy or its operation stopped. Read status and recovery records before retrying."}, error=True)
                except (ValueError, KeyError, TypeError):
                    result = _result({"error_code": "invalid_inputs_or_state", "error": "Inputs or saved state do not satisfy the deterministic research contract. Validate the plan, inspect status and prepare a fresh review if settings changed."}, error=True)
                except Exception:
                    result = _result({"error_code": "unexpected_operation_failure", "error": "Tool stopped unexpectedly; inspect persistent status and audit records. No exception body is returned."}, error=True)
            else:
                return self._error(identifier, -32601, "Method not found")
            return {"jsonrpc": "2.0", "id": identifier, "result": result}
        except (ValueError, RecursionError):
            return self._error(identifier, -32602, "Invalid or excessively nested parameters")

    @staticmethod
    def _error(identifier, code, message):
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}

    def close(self, timeout=5):
        self.closing.set()
        deadline = time.monotonic() + max(0, min(timeout, 30))
        # Repeat cancellation while joining to cover the engine's atomic run
        # initialization. Cancellation stops new dispatch, not provider billing.
        while self.running:
            try:
                self.project.cancel()
            except (OSError, RuntimeError, ValueError):
                pass
            self.worker.join(min(0.1, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
        if not self.running:
            self._close_workspace_resources()
        return not self.running

    def _close_workspace_resources(self):
        # An in-flight worker can still record a finite provider outcome after
        # the bounded join; retain its guard descriptor until its final write.
        with self.resources_lock:
            if self.workspace_fd is not None:
                os.close(self.workspace_fd)
                self.workspace_fd = None

    def serve(self, input_stream=None, output_stream=None):
        input_stream = input_stream or sys.stdin.buffer
        output_stream = output_stream or sys.stdout
        try:
            while not self.closing.is_set():
                line = input_stream.readline(MAX_MESSAGE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE_BYTES:
                    response = self._error(None, -32700, "Message exceeds finite size bound; connection closing")
                    self._write(output_stream, response)
                    break
                try:
                    request = decode_json(line.decode("utf-8") if isinstance(line, bytes) else line)
                    response = self.dispatch(request)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    response = self._error(None, -32700, "Invalid JSON; duplicate keys and nonfinite values are forbidden")
                if response is not None:
                    self._write(output_stream, response)
        except (BrokenPipeError, KeyboardInterrupt):
            pass
        finally:
            self.close()

    @staticmethod
    def _write(output_stream, value):
        output_stream.write(canonical(value) + "\n")
        output_stream.flush()


def write_skill(out):
    """Export packaged instructions to a fresh folder; no global installation."""
    out = Path(out).expanduser().absolute()
    if out.exists() or out.is_symlink():
        raise ValueError("Choose a fresh skill directory; existing work is never overwritten")
    if any(parent.is_symlink() for parent in out.parents):
        raise ValueError("Skill output parents must not be symbolic links")
    files = Path(__file__).with_name("agent_skill")
    assets = [(path.relative_to(files), path.read_bytes()) for path in sorted(files.rglob("*"))
              if path.is_file() and not path.is_symlink()]
    if not assets or not (files / "SKILL.md").is_file():
        raise ValueError("Packaged V6 skill is unavailable")
    out.mkdir(parents=True, exist_ok=False)
    for relative, content in assets:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    return {"out": str(out), "files": [p.as_posix() for p, _ in assets],
            "installed_globally": False, "next_step": "Read SKILL.md with your coding agent; manually configure the fixed-project MCP server if desired."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Quarry stdio MCP server (V6.4 engine) for one fixed project or bounded study workspace; stdout contains only JSON-RPC.")
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--project", type=Path)
    location.add_argument("--workspace", type=Path, help="Specific existing nonhidden study workspace; safe study selection stays within this root")
    parser.add_argument("--allow-paid", action="store_true", help="Explicit launch-time permission for approved configured provider calls")
    args = parser.parse_args(argv)
    server = MCPServer(Project(args.project) if args.project is not None else None,
                       workspace=args.workspace, allow_paid=args.allow_paid)
    server.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
