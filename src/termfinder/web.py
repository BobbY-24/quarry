"""Local browser interface. Loopback, strict Host/Origin and session tokens."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

STATIC = Path(__file__).with_name("static")
MAX_BODY = 32_000_000
MAX_DOWNLOAD = 20_000_000


def _read_artifact(project, relative):
    """Read a bounded saved export/annotation file without following symlinks."""
    if not isinstance(relative, str) or len(relative) > 1024 or "\\" in relative:
        raise ValueError("Use a saved export or annotation packet file")
    parts = relative.split("/")
    if len(parts) < 3 or parts[0] not in {"exports", "human-review"} or any(
        not part or part in {".", ".."} or part.startswith(".")
        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in part)
        for part in parts
    ) or Path(parts[-1]).suffix not in {".csv", ".json", ".jsonl", ".parquet", ".txt", ".md"}:
        raise ValueError("Use a saved export or annotation packet file")
    directory = os.open(project.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(file_descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DOWNLOAD:
                raise ValueError("Browser downloads require a regular file smaller than 20 MB; use the saved local directory for larger files")
            content = stream.read(MAX_DOWNLOAD + 1)
            if len(content) > MAX_DOWNLOAD:
                raise ValueError("Browser downloads require a file smaller than 20 MB")
        return content, parts[-1]
    finally:
        os.close(directory)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _decode_json(value):
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON values are not allowed")))


def _review_state(project, *, check=False):
    # Retain compatibility with lightweight interface integrations that expose
    # the earlier read API without persistent guided-workflow settings.
    if not hasattr(project, "store"):
        return {}
    from .workflow import current_review
    return current_review(project, check=check)


def _setup_revision(project):
    if not hasattr(project, "store"):
        return None
    revision = project.store.read_setting("ui_setup_revision")
    return revision if isinstance(revision, str) and len(revision) == 64 and all(ch in "0123456789abcdef" for ch in revision) else None


def _agent_setup_state(project):
    if not hasattr(project, "store"):
        return dict(project.agent_setup())
    # One SELECT reads the marker and its matching setup/proposal consistently;
    # a concurrent agent write cannot hide a new revision behind stale contents.
    with project.store.connection() as db:
        values = {key: _decode_json(value) for key, value in db.execute(
            "SELECT key,value FROM settings WHERE key IN ('agent_setup','agent_proposal','ui_setup_revision')")}
    setup = dict(values.get("agent_setup") or {})
    proposal = values.get("agent_proposal")
    from .store import digest
    if (isinstance(proposal, dict) and setup.get("brief_sha256")
            and proposal.get("brief_sha256") == setup.get("brief_sha256")
            and digest(proposal) != setup.get("bundle_sha256")):
        # This is an agent draft. Preparation revalidates it before any
        # source import or collection; GET does not approve or apply it.
        setup["proposed_bundle"] = proposal
    setup["ui_setup_revision"] = values.get("ui_setup_revision")
    return setup


class ResearchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, project, port=8765, allow_paid=False):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
        self.project = project
        self.allow_paid = allow_paid
        self.token = secrets.token_urlsafe(32)
        self.worker = None
        self.worker_error = None
        self.worker_result = None
        self.worker_lock = threading.Lock()
        self.request_slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.host = f"127.0.0.1:{self.server_port}"

    def get_request(self):
        request,address=super().get_request()
        request.settimeout(30)
        return request,address

    def process_request(self,request,address):
        if not self.request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request,address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self,request,address):
        try: super().process_request_thread(request,address)
        finally: self.request_slots.release()

    def start_collection(self, max_jobs=None, review_id=None):
        if max_jobs is not None and (type(max_jobs) is not int or max_jobs <= 0):
            raise ValueError("max_jobs must be a positive integer or null")
        profile = getattr(self.project, "profile", None) or {}
        if not self.allow_paid and (profile.get("id") or profile.get("name")) != "fake":
            raise ValueError("This browser session only permits the offline fake profile. Select Offline fake for a rehearsal, or restart the interface with explicit provider authorization for real collection.")
        with self.worker_lock:
            if self.worker is not None and self.worker.is_alive():
                raise ValueError("A collection is already running")
            if review_id is not None:
                from .workflow import check_review
                # Return a concrete stale/unapproved-plan error before claiming
                # dispatch. The worker repeats admission under the corpus lock.
                check_review(self.project, review_id, allow_paid=self.allow_paid)
            self.worker_error = None
            self.worker_result = None

            def collect():
                try:
                    if review_id is not None:
                        from .workflow import run_review
                        if self.allow_paid:
                            self.worker_result = run_review(self.project, review_id, allow_paid=True, max_jobs=max_jobs)
                        else:
                            from .providers import FakeProvider
                            self.worker_result = run_review(self.project, review_id, provider=FakeProvider(), max_jobs=max_jobs)
                    elif self.allow_paid:
                        self.worker_result = self.project.resume(allow_paid=True, max_jobs=max_jobs)
                    else:
                        from .providers import FakeProvider
                        self.worker_result = self.project.resume(provider=FakeProvider(), max_jobs=max_jobs)
                except Exception as exc:
                    # API/provider diagnostics may contain returned untrusted text;
                    # logs never dump exception bodies, credentials, or requests.
                    self.worker_error = {"type": type(exc).__name__, "message": "Collection stopped with an error; inspect persistent jobs and audit records."}

            self.worker = threading.Thread(target=collect, name="termfinder-collection", daemon=True)
            self.worker.start()
        return {"started": True, "offline": not self.allow_paid}


class Handler(BaseHTTPRequestHandler):
    server: ResearchServer

    def log_message(self, format, *args):
        # URL/log output may contain researcher source locators or query strings.
        pass

    def _send(self, code, data, content_type="application/json; charset=utf-8", filename=None):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def _trusted_host(self):
        if self.headers.get("Host") != self.server.host:
            self._send(403, {"error": "Use the printed loopback address; invalid Host"})
            return False
        return True

    def _authenticated(self, mutation=False):
        if not self._trusted_host():
            return False
        if mutation and self.headers.get("Origin") != self.server.origin:
            self._send(403, {"error": "Same-origin browser mutations required"})
            return False
        supplied = self.headers.get("X-Termfinder-Token", "")
        if not hmac.compare_digest(supplied, self.server.token):
            self._send(403, {"error": "Invalid session token; reload the local application"})
            return False
        return True

    def do_GET(self):
        if not self._trusted_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            page = (STATIC / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", self.server.token)
            self._send(200, page, "text/html; charset=utf-8")
        elif path in {"/app.js", "/style.css"}:
            name = path[1:]
            self._send(200, (STATIC / name).read_bytes(), "text/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8")
        elif path in {"/api/state", "/api/starters", "/api/agent-setup", "/api/source", "/api/review", "/api/download"}:
            if not self._authenticated():
                return
            try:
                query = parse_qs(urlsplit(self.path).query, max_num_fields=12)
                if path == "/api/download":
                    data, filename = _read_artifact(self.server.project, query.get("path", [""])[0])
                    self._send(200, data, "application/octet-stream", filename=filename)
                    return
                elif path == "/api/starters":
                    from .config import starter_recipe
                    result = {name: starter_recipe(name) for name in ("neologisms", "cultural", "jargon")}
                elif path == "/api/agent-setup":
                    result = _agent_setup_state(self.server.project)
                elif path == "/api/review":
                    result = _review_state(self.server.project, check=True)
                elif path == "/api/source":
                    source_id=query.get("id",[""])[0]
                    if len(source_id)>128: raise ValueError("Invalid source ID")
                    result=self.server.project.store.get("sources",source_id)
                    if result is None: raise ValueError("Unknown source ID")
                else:
                    inventory=self.server.project.page_inventory(offset=int(query.get("offset",["0"])[0]),limit=int(query.get("limit",["50"])[0]),query=query.get("query",[""])[0],record_id=query.get("record",[None])[0],evidence_offset=int(query.get("evidence_offset",["0"])[0]),recovery_offset=int(query.get("recovery_offset",["0"])[0])) if query.get("paged") == ["1"] else self.server.project.inventory()
                    status = self.server.project.status()
                    result = {"status": status, "inventory": inventory, "recipe": getattr(self.server.project, "recipe", None), "profile": getattr(self.server.project, "profile", None), "versions": self.server.project.versions(), "running": status.get("status") == "running" or self.server.worker is not None and self.server.worker.is_alive(), "worker_error": self.server.worker_error, "worker_result": self.server.worker_result, "offline": not self.server.allow_paid, "review": _review_state(self.server.project), "setup_revision": _setup_revision(self.server.project)}
                self._send(200, result)
            except ValueError:
                self._send(400, {"error":"Invalid query or page bounds"})
            except Exception:
                self._send(500, {"error": "Unable to load project; inspect project configuration and persistent status"})
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        if not self._authenticated(mutation=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("Request body must be between 1 byte and 32 MB")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Only application/json request bodies are accepted")
            body = _decode_json(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            path = urlsplit(self.path).path
            project = self.server.project
            if path in {"/api/agent-setup/prepare", "/api/agent-setup/apply", "/api/agent-setup/ingest", "/api/agent-setup/freeze", "/api/review", "/api/review/approve", "/api/release"} and self.server.worker and self.server.worker.is_alive():
                raise ValueError("Wait for collection to stop before changing or ingesting its study plan")
            if path == "/api/review":
                from .workflow import prepare_review
                bundle = _decode_json(body["bundle_text"]) if "bundle_text" in body else body.get("bundle")
                if bundle is not None and not isinstance(bundle, dict):
                    raise ValueError("The agent plan must be a JSON object")
                fetch_remote = body.get("fetch_remote", False)
                if type(fetch_remote) is not bool:
                    raise ValueError("Website fetching requires an explicit boolean")
                result = prepare_review(project, bundle=bundle, fetch_remote=fetch_remote)
            elif path == "/api/review/approve":
                from .workflow import approve_review
                result = approve_review(project, body["review_id"])
            elif path == "/api/review/run":
                review_id = body["review_id"]
                if not isinstance(review_id, str) or not review_id or len(review_id) > 128:
                    raise ValueError("Use the saved review ID")
                result = self.server.start_collection(body.get("max_jobs"), review_id=review_id)
            elif path == "/api/release":
                from .workflow import release_dataset
                result = release_dataset(project, body.get("name", "research-v1"), formats=body.get("formats", ["csv", "jsonl", "parquet", "annotation"]), version_id=body.get("version_id"))
            elif path == "/api/agent-setup/prepare":
                result = project.prepare_agent_setup(body["brief"])
            elif path in {"/api/agent-setup/validate", "/api/agent-setup/apply"}:
                bundle = _decode_json(body["bundle_text"]) if "bundle_text" in body else body["bundle"]
                if not isinstance(bundle, dict):
                    raise ValueError("The agent plan must be a JSON object")
                result = project.validate_agent_bundle(bundle) if path.endswith("/validate") else project.apply_agent_bundle(bundle)
            elif path == "/api/agent-setup/ingest":
                result = project.ingest_agent_sources()
            elif path == "/api/agent-setup/freeze":
                result = project.freeze_agent_corpus(name=body.get("name", "corpus-v1"), seed=body.get("seed", "v6-agent-study-v1"))
            elif path == "/api/configure":
                if self.server.worker and self.server.worker.is_alive():
                    raise ValueError("Wait for collection to stop before changing its recipe")
                profile = body.get("profile", "fake")
                if profile not in {"fake", "glm-deepseek", "gemini"}:
                    raise ValueError("Browser profile must be fake, glm-deepseek, or gemini; custom provider configuration uses the CLI")
                recipe = _decode_json(body["recipe_text"]) if "recipe_text" in body else body["recipe"]
                if "mode" in body:
                    recipe["mode"] = body["mode"]
                result = project.configure(recipe, profile)
            elif path == "/api/ingest":
                metadata = _decode_json(body["metadata_text"]) if "metadata_text" in body else body.get("metadata")
                result = {"source_ids": project.ingest(paths=body.get("paths", []), urls=body.get("urls", []), metadata=metadata)}
            elif path == "/api/estimate":
                assumptions = {key: body[key] for key in ("average_chars", "cache_hit_rate") if body.get(key) is not None}
                result = project.estimate(links=body.get("links"), **assumptions)
            elif path == "/api/collect":
                result = self.server.start_collection(body.get("max_jobs"))
            elif path == "/api/cancel":
                project.cancel()
                result = project.status()
            elif path == "/api/large-run":
                result = project.configure_large_run()
            elif path == "/api/reset-model":
                result = project.reset_model(body["model_alias"])
            elif path == "/api/retry-job":
                project.retry_failed(body["job_id"])
                result = {"job_id": body["job_id"], "status": "pending"}
            elif path == "/api/resolve-uncertain":
                retry = body.get("retry", False)
                acknowledge = body.get("acknowledge_possible_duplicate_billing", False)
                if type(retry) is not bool or type(acknowledge) is not bool:
                    raise ValueError("Retry and duplicate billing acknowledgement must be explicit booleans")
                project.resolve_uncertain(body["job_id"], retry=retry, acknowledge_possible_duplicate_billing=acknowledge)
                result = {"job_id": body["job_id"], "status": "pending" if retry else "failed", "unknown_reserves_retained": True}
            elif path == "/api/annotate":
                result = {"annotation_id": project.annotate(body["term_id"], body["status"], body.get("note", ""), body.get("attributes"), body.get("actor", "researcher"))}
            elif path == "/api/undo-annotation":
                project.undo_annotation(body["annotation_id"])
                result = {"undone": body["annotation_id"]}
            elif path == "/api/relate":
                result = {"relation_id": project.relate(body["term_a"], body["term_b"], body["kind"], body.get("actor", "researcher"))}
            elif path == "/api/undo-relation":
                project.undo_relation(body["relation_id"])
                result = {"undone": body["relation_id"]}
            elif path == "/api/snapshot":
                result = {"version_id": project.snapshot(body["name"])}
            elif path == "/api/publication-audit":
                result = project.publication_audit(body["version"])
            elif path == "/api/export":
                version = body["version"]
                if not isinstance(version, str) or not version or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in version) or version in {".", ".."}:
                    raise ValueError("Use a saved dataset version ID")
                project_path = Path(getattr(project, "path", "."))
                out = project_path / "exports" / version
                result = project.export(version, out, formats=body.get("formats", ["csv", "jsonl", "parquet", "annotation"]))
            else:
                self._send(404, {"error": "Not found"})
                return
            self._send(200, result if isinstance(result, dict) else {"result": result})
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"The returned plan is not valid JSON (line {exc.lineno}, column {exc.colno}). Ask your agent for one complete JSON object without code fences."})
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
            # Local validation messages are safe; never expose transport exception
            # bodies, which can include provider response/request data.
            safe = str(exc) if type(exc) in {ValueError, FileExistsError, KeyError, TypeError} else f"{type(exc).__name__}: operation failed; inspect persistent status"
            self._send(400, {"error": safe})
        except Exception:
            self._send(500, {"error": "Operation failed unexpectedly; inspect project status and persistent jobs"})


def serve(project, *, port=8765, allow_paid=False):
    server = ResearchServer(project, port, allow_paid)
    print(f"Open {server.origin} in your browser. Mode: {'configured provider APIs authorized for this session' if allow_paid else 'offline fake provider'}. Ctrl-C stops the interface.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        project.cancel()
    finally:
        server.server_close()
