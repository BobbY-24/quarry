"""Deterministic document parsing and explicitly scoped, public-web retrieval.

Offsets always address Python Unicode code points in the saved ``text`` field.
HTML/PDF extraction is an observation of extracted text, not a byte offset into
the original document. The original document hash is retained separately.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import mimetypes
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

PARSER_VERSION = "termfinder-parser/1.0"
_MAX_LOCAL_BYTES = 100_000_000
_MAX_PDF_PAGES = 2_000
_MAX_EXTRACTED_CHARACTERS = 20_000_000
_DNS_SLOTS = threading.BoundedSemaphore(4)
_SECRET_PARAMETERS = frozenset({
    "api_key", "apikey", "api-key", "key", "token", "access_token",
    "auth", "authorization", "password", "passwd", "secret", "credential",
    "signature", "sig", "x-amz-signature", "x-amz-credential",
    "access-token", "bearer", "sessionid", "session", "session_id", "client_secret",
    "oauth_token", "id_token", "refresh_token", "auth_token", "authkey", "x-api-key",
})


class SourceError(ValueError):
    """A safe category of ingestion failure; excludes response data/secrets."""


class UnsafeURLError(SourceError):
    pass


def error_category(exc: Exception) -> str:
    """Expose only our enumerated categories, never a transport error string."""
    categories = {
        "invalid_url", "unsupported_url_scheme", "url_credentials_forbidden",
        "invalid_hostname", "port_not_allowed", "domain_out_of_scope",
        "dns_resolution_failed", "invalid_dns_address", "nonpublic_address_forbidden",
        "fetch_timeout", "fetch_transport_failed", "source_too_large", "invalid_content_length",
        "unsupported_content_encoding", "redirect_location_missing", "redirect_limit_exceeded",
        "unsupported_media_type", "text_encoding_unresolved", "binary_text_unsupported",
        "pdf_dependency_unavailable", "encrypted_pdf_unsupported", "pdf_parse_failed",
        "pdf_page_limit_exceeded", "extracted_text_too_large", "invalid_turn_metadata",
        "invalid_turn_offsets", "local_file_not_found", "local_source_too_large",
        "local_file_unreadable", "adapter_returned_out_of_scope_source",
        "pdf_parse_timeout", "pdf_worker_unavailable", "pdf_resource_limit_exceeded",
        "pdf_output_limit_exceeded", "pdf_worker_invalid_response",
        "pdf_resource_limits_unavailable", "pdf_memory_monitor_unavailable",
    }
    message = str(exc)
    explicit_messages = {"local_sources_disabled": "local_sources_disabled",
                         "Source has no extractable text": "no_extractable_text",
                         "source text hash mismatch": "source_hash_mismatch"}
    if isinstance(exc, ValueError) and message in explicit_messages:
        return explicit_messages[message]
    if isinstance(exc, SourceError) and (message in categories or re.fullmatch(r"http_status_[1-5][0-9]{2}", message)):
        return message
    return "source_processing_failed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_url(url: str) -> str:
    """Validate a public-web URL's syntax, without performing DNS lookups."""
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url):
        raise UnsafeURLError("invalid_url")
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("invalid_url") from exc
    if parts.scheme.lower() not in {"http", "https"} or not hostname:
        raise UnsafeURLError("unsupported_url_scheme")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("url_credentials_forbidden")
    if any(key.lower() in _SECRET_PARAMETERS for key, _ in parse_qsl(parts.query)):
        raise UnsafeURLError("url_credentials_forbidden")
    try:
        hostname = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise UnsafeURLError("invalid_hostname") from exc
    if not hostname or "%" in hostname or any(c.isspace() for c in hostname):
        raise UnsafeURLError("invalid_hostname")
    if port not in {None, 80, 443}:
        raise UnsafeURLError("port_not_allowed")
    scheme = parts.scheme.lower()
    default_port = 443 if scheme == "https" else 80
    host_field = f"[{hostname}]" if ":" in hostname else hostname
    authority = host_field + (f":{port}" if port and port != default_port else "")
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="%=&?/:@!$'()*+,;~-._")
    return f"{scheme}://{authority}{path}" + (f"?{query}" if query else "")


def in_domain_scope(url: str, scope: dict | list[str] | tuple[str, ...] | None) -> bool:
    """Literal domains match exactly; ``*.example.org`` also matches its apex.

    Empty domains permit explicit public-web ingestion. Discovery separately
    requires a nonempty domain list before acquiring remotely found sources.
    """
    canonical = canonical_url(url)
    host = urlsplit(canonical).hostname
    domains = scope.get("domains", []) if isinstance(scope, dict) else (scope or [])
    if not domains:
        return True
    for entry in domains:
        domain = entry.lower().rstrip(".")
        if domain.startswith("*."):
            apex = domain[2:]
            if host == apex or host.endswith("." + apex):
                return True
        elif host == domain:
            return True
    return False


def _http_links(links: list[str], locator: str) -> list[str]:
    result = set()
    for value in links:
        try:
            result.add(canonical_url(urljoin(locator, value)))
        except UnsafeURLError:
            continue
    return sorted(result)


def _text_blocks(text: str, markdown: bool = False) -> list[dict]:
    """Preserve line locations, Markdown headings/table rows and named turns."""
    blocks: list[dict] = []
    heading = None
    position = 0
    for line_number, raw in enumerate(text.splitlines(keepends=True), start=1):
        line = raw.rstrip("\r\n")
        if line.strip():
            kind = "paragraph"
            if markdown and re.match(r"^\s{0,3}#{1,6}\s+", line):
                kind = "heading"
                heading = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
            elif markdown and "|" in line and (line.lstrip().startswith("|") or line.count("|") >= 2):
                kind = "table_row"
            elif re.match(r"^\s*(?:User|Assistant|Speaker\s+\w+|Researcher|Participant\s+\w+)\s*:", line, re.I):
                kind = "turn"
            elif markdown and re.match(r"^\s*(?:[-*+] |\d+[.)] )", line):
                kind = "list_item"
            blocks.append({"kind": kind, "start": position, "end": position + len(line),
                           "page": None, "heading": heading,
                           "location": {"line": line_number}})
        position += len(raw)
    return blocks


class _HTMLText(HTMLParser):
    _ignored = {"script", "style", "noscript", "template", "head"}
    _kinds = {"p": "paragraph", "li": "list_item", "tr": "table_row",
              "blockquote": "paragraph", "pre": "paragraph", "dt": "paragraph",
              "dd": "paragraph", "article": "paragraph", "div": "paragraph",
              "section": "paragraph"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocks: list[dict] = []
        self.links: list[str] = []
        self.pending: list[str] = []
        self.heading = None
        self.kind = "paragraph"
        self.location: dict = {}
        self.ignore_stack: list[str] = []
        self.language = None
        self.publication_date = None
        self.title = None
        self._title_parts: list[str] = []
        self._in_title = False
        self._position = 0
        self._block_stack: list[tuple[str, str, dict]] = []

    def flush(self):
        value = re.sub(r"\s+", " ", "".join(self.pending)).strip()
        self.pending.clear()
        if not value:
            return
        if self.parts:
            self.parts.append("\n\n")
            self._position += 2
        if self.kind == "heading":
            self.heading = value
        start = self._position
        self.parts.append(value)
        self._position += len(value)
        self.blocks.append({"kind": self.kind, "start": start, "end": self._position,
                            "page": None, "heading": self.heading,
                            "location": dict(self.location)})

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "html":
            self.language = attrs.get("lang") or attrs.get("xml:lang")
        if tag == "meta":
            name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
            if name in {"article:published_time", "datepublished", "date", "dc.date", "dcterms.issued"}:
                self.publication_date = self.publication_date or attrs.get("content")
        if tag == "time" and attrs.get("datetime") and (attrs.get("itemprop") == "datePublished"):
            self.publication_date = self.publication_date or attrs["datetime"]
        if tag == "title":
            self._in_title = True
        if tag in self._ignored:
            if not self.ignore_stack:
                self.flush()
            self.ignore_stack.append(tag)
            return
        if self.ignore_stack:
            return
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "br":
            self.pending.append("\n")
        elif tag in {"td", "th"}:
            if self.pending:
                self.pending.append(" | ")
        elif tag in self._kinds or re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self._block_stack.append((tag, self.kind, self.location))
            inherited_speaker = self.location.get("speaker") if self.kind == "turn" else None
            self.kind = "heading" if tag.startswith("h") and len(tag) == 2 else self._kinds[tag]
            self.location = {"html_tag": tag}
            if attrs.get("id"):
                self.location["element_id"] = attrs["id"]
            if attrs.get("data-speaker") or inherited_speaker:
                self.kind = "turn"
                self.location["speaker"] = attrs.get("data-speaker") or inherited_speaker

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            self.title = re.sub(r"\s+", " ", "".join(self._title_parts)).strip() or None
        if self.ignore_stack:
            if tag in self.ignore_stack:
                index = len(self.ignore_stack) - 1 - self.ignore_stack[::-1].index(tag)
                del self.ignore_stack[index:]
            return
        if tag in self._kinds or re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.kind = "paragraph"
            self.location = {}
            for index in range(len(self._block_stack) - 1, -1, -1):
                if self._block_stack[index][0] == tag:
                    _, self.kind, self.location = self._block_stack[index]
                    del self._block_stack[index:]
                    break

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        if not self.ignore_stack:
            self.pending.append(data)


def _decode(data: bytes, media_type: str) -> str:
    match = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", media_type, re.I)
    encoding = match.group(1) if match else "utf-8-sig"
    try:
        return data.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise SourceError("text_encoding_unresolved") from exc


def _run_pdf_worker(data: bytes) -> subprocess.CompletedProcess:
    """Pass bytes as private FDs and monitor only the known parser child."""
    worker = Path(__file__).with_name("pdf_worker.py").resolve()
    command = [sys.executable, "-I", str(worker)]
    deadline = time.monotonic() + 30
    with tempfile.TemporaryFile() as input_file, tempfile.TemporaryFile() as output_file:
        input_file.write(data)
        input_file.seek(0)
        process = subprocess.Popen(command, stdin=input_file, stdout=output_file,
                                   stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"})
        try:
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceError("pdf_parse_timeout")
                try:
                    process.wait(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
            output_file.seek(0)
            output = output_file.read(90_000_001)
            return subprocess.CompletedProcess(command, process.returncode, stdout=output)
        finally:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass


def _parse_pdf(data: bytes) -> dict:
    """Bound trusted pinned parsing code without inheriting provider secrets."""
    if len(data) > _MAX_LOCAL_BYTES:
        raise SourceError("local_source_too_large")
    try:
        result = _run_pdf_worker(data)
    except subprocess.TimeoutExpired as exc:
        raise SourceError("pdf_parse_timeout") from exc
    except OSError as exc:
        raise SourceError("pdf_worker_unavailable") from exc
    if result.returncode:
        raise SourceError("pdf_resource_limit_exceeded" if result.returncode < 0 or result.returncode == 72 else "pdf_parse_failed")
    if len(result.stdout) > 90_000_000:
        raise SourceError("pdf_output_limit_exceeded")
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise SourceError("pdf_worker_invalid_response") from exc
    if not isinstance(parsed, dict):
        raise SourceError("pdf_worker_invalid_response")
    if parsed.get("error"):
        if parsed["error"] not in {"pdf_dependency_unavailable", "local_source_too_large", "encrypted_pdf_unsupported",
                                   "pdf_page_limit_exceeded", "extracted_text_too_large", "pdf_resource_limit_exceeded",
                                   "pdf_output_limit_exceeded", "pdf_parse_failed", "pdf_resource_limits_unavailable"}:
            raise SourceError("pdf_worker_invalid_response")
        raise SourceError(parsed["error"])
    pages = parsed.get("pages")
    if not isinstance(pages, list) or len(pages) > _MAX_PDF_PAGES or any(not isinstance(page, str) for page in pages):
        raise SourceError("pdf_worker_invalid_response")
    if sum(map(len, pages)) > _MAX_EXTRACTED_CHARACTERS:
        raise SourceError("extracted_text_too_large")
    if parsed.get("title") is not None and not isinstance(parsed["title"], str):
        raise SourceError("pdf_worker_invalid_response")
    return parsed


def parse_document(data: bytes, media_type: str, locator: str, metadata: dict | None = None) -> dict:
    """Parse a frozen document without network access or model execution."""
    metadata = dict(metadata or {})
    if urlsplit(locator).scheme.lower() in {"http", "https"}:
        locator = canonical_url(locator)
    mime = media_type.split(";", 1)[0].lower().strip()
    parser_info = {}
    detected_language = None
    publication_date = metadata.get("publication_date")
    title = metadata.get("title")
    if mime in {"text/html", "application/xhtml+xml"}:
        parser = _HTMLText()
        parser.feed(_decode(data, media_type))
        parser.close()
        parser.flush()
        text = "".join(parser.parts)
        blocks, links = parser.blocks, _http_links(parser.links, locator)
        detected_language = parser.language
        publication_date = publication_date or parser.publication_date
        title = title or parser.title
    elif mime == "application/pdf":
        parsed = _parse_pdf(data)
        pages = parsed["pages"]
        blocks = []
        position = 0
        for page_number, page_text in enumerate(pages, start=1):
            if page_number > 1:
                position += 2
            for block in _text_blocks(page_text):
                block["start"] += position
                block["end"] += position
                block["page"] = page_number
                block["location"]["page"] = page_number
                blocks.append(block)
            position += len(page_text)
        text = "\n\n".join(pages)
        links = _http_links(re.findall(r"https?://[^\s<>]+", text), locator)
        parser_info = {"pages": len(pages), "ocr_performed": False,
                       "ocr_reason": "ocr_is_an_optional_extension",
                       "parser_isolation": "clean_environment_process_with_resource_limits",
                       "wall_timeout_seconds": 30, "cpu_limit_seconds": 20,
                       "memory_limit_bytes": 1_073_741_824,
                       "memory_limit_kind": "sampled_self_rss" if sys.platform == "darwin" else "kernel_address_space",
                       "memory_limit_reason": "sampling_can_transiently_overshoot" if sys.platform == "darwin" else None}
        title = title or parsed.get("title")
        if not text.strip():
            parser_info["needs_ocr"] = True
    elif mime in {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}:
        if mime == "application/octet-stream" and Path(urlsplit(locator).path).suffix.lower() not in {".txt", ".md", ".markdown"}:
            raise SourceError("unsupported_media_type")
        text = _decode(data, media_type)
        if "\x00" in text:
            raise SourceError("binary_text_unsupported")
        markdown = mime in {"text/markdown", "text/x-markdown"} or Path(locator).suffix.lower() in {".md", ".markdown"}
        blocks = _text_blocks(text, markdown=markdown)
        links = _http_links(re.findall(r"https?://[^\s<>\[\]()]+", text), locator)
    else:
        raise SourceError("unsupported_media_type")
    if len(text) > _MAX_EXTRACTED_CHARACTERS:
        raise SourceError("extracted_text_too_large")
    publication_reason = metadata.get("publication_date_reason", "not_available_in_source_or_metadata")
    if publication_date is not None:
        try:
            if not isinstance(publication_date, str):
                raise ValueError("invalid_date")
            # Retain the original date/time spelling once its date is validated.
            datetime.fromisoformat(publication_date[:10])
        except ValueError:
            publication_date = None
            publication_reason = "publication_date_unparseable"
    if metadata.get("turns"):
        for turn in metadata["turns"]:
            if not isinstance(turn, dict):
                raise SourceError("invalid_turn_metadata")
            start, end = turn.get("start"), turn.get("end")
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise SourceError("invalid_turn_offsets")
            blocks.append({"kind": "turn", "start": start, "end": end, "page": turn.get("page"),
                           "heading": None, "location": {"speaker": turn.get("speaker")}})
        blocks.sort(key=lambda block: (block["start"], block["end"], block["kind"]))
    domain = urlsplit(locator).hostname if urlsplit(locator).scheme in {"http", "https"} else "local"
    return {
        "locator": locator, "raw_sha256": hashlib.sha256(data).hexdigest(),
        "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "media_type": mime, "retrieved_at": metadata.get("retrieved_at") or utc_now(),
        "publication_date": publication_date,
        "publication_date_reason": None if publication_date else publication_reason,
        "language": metadata.get("language") or detected_language or "und",
        "community": metadata.get("community"), "domain": metadata.get("domain") or domain,
        "constraints": metadata.get("constraints") or {
            "license": None, "license_reason": "not_provided", "permitted_use": None,
            "permitted_use_reason": "researcher_must_record_source_use_constraints"},
        "blocks": blocks, "links": links, "parser_version": PARSER_VERSION,
        "title": title, "title_reason": None if title else "not_available_in_source_or_metadata",
        "parser_info": parser_info,
        "text_origin": "observed_extracted_text",
        "offset_unit": "unicode_code_point",
    }


def load_local(path: str | Path, metadata: dict | None = None) -> dict:
    """Load one explicitly supplied file; never recurse through a directory."""
    path = Path(path).expanduser().resolve()
    try:
        if not path.is_file():
            raise SourceError("local_file_not_found")
        if path.stat().st_size > _MAX_LOCAL_BYTES:
            raise SourceError("local_source_too_large")
        with path.open("rb") as handle:
            data = handle.read(_MAX_LOCAL_BYTES + 1)
    except OSError as exc:
        raise SourceError("local_file_unreadable") from exc
    if len(data) > _MAX_LOCAL_BYTES:
        raise SourceError("local_source_too_large")
    mime = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
            ".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf"}.get(path.suffix.lower())
    mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return parse_document(data, mime, str(path), metadata)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: tuple, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self.address = address

    def connect(self):
        family, socktype, protocol, _, sockaddr = self.address
        connection = socket.socket(family, socktype, protocol)
        connection.settimeout(self.timeout)
        try:
            connection.connect(sockaddr)
        except BaseException:
            connection.close()
            raise
        self.sock = connection


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    def connect(self):
        super().connect()
        try:
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)
        except BaseException:
            self.sock.close()
            raise


class SafeFetcher:
    """Bounded retrieval with DNS pinning, verified TLS and scoped redirects.

    No cookies, credentials, proxy environment variables, or browser sessions
    are consumed. Only HTTP/HTTPS on ports 80/443 is implemented. Tests inject a
    resolver or subclass ``_request``; production connects to a validated IP.
    """

    def __init__(self, scope: dict | list[str] | None, timeout: float = 30, max_bytes: int = 20_000_000,
                 *, max_redirects: int = 3, resolver=None):
        if timeout <= 0 or max_bytes <= 0 or max_redirects < 0:
            raise ValueError("invalid_fetch_limits")
        self.scope, self.timeout, self.max_bytes = scope, timeout, max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver or socket.getaddrinfo

    def _addresses(self, url: str, deadline: float | None = None) -> list[tuple]:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        deadline = deadline or time.monotonic() + self.timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not _DNS_SLOTS.acquire(timeout=max(0, remaining)):
            raise SourceError("fetch_timeout")
        resolved: list = []
        completed = threading.Event()

        def resolve():
            try:
                resolved.append(self.resolver(parts.hostname, port, type=socket.SOCK_STREAM))
            except Exception:
                resolved.append(None)
            finally:
                _DNS_SLOTS.release()
                completed.set()

        # OS DNS has no cancellation primitive; at most four daemon calls can
        # survive a timeout. This bounds both caller latency and residual work.
        threading.Thread(target=resolve, daemon=True, name="termfinder-dns").start()
        if not completed.wait(max(0, deadline - time.monotonic())):
            raise SourceError("fetch_timeout")
        addresses = resolved[0]
        if not addresses:
            raise SourceError("dns_resolution_failed")
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address[4][0].split("%", 1)[0])
            except ValueError as exc:
                raise UnsafeURLError("invalid_dns_address") from exc
            if not parsed.is_global or parsed.is_multicast or parsed.is_unspecified:
                raise UnsafeURLError("nonpublic_address_forbidden")
        return addresses

    def _request(self, url: str, addresses: list[tuple], deadline: float) -> tuple[int, dict, bytes]:
        parts = urlsplit(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("fetch_timeout")
        connection_cls = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
        connection = connection_cls(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                    addresses[0], remaining)
        try:
            path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
            connection.request("GET", path, headers={"User-Agent": "TermFinder/6 research-ingestion",
                               "Accept": "text/html,text/plain,text/markdown,application/pdf",
                               "Accept-Encoding": "identity", "Connection": "close"})
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                return response.status, headers, b""
            if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise SourceError("unsupported_content_encoding")
            length = headers.get("content-length")
            if length:
                try:
                    if int(length) > self.max_bytes:
                        raise SourceError("source_too_large")
                except ValueError as exc:
                    if isinstance(exc, SourceError):
                        raise
                    raise SourceError("invalid_content_length") from exc
            chunks = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceError("fetch_timeout")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read(min(65536, self.max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > self.max_bytes:
                    raise SourceError("source_too_large")
            return response.status, headers, b"".join(chunks)
        except (socket.timeout, TimeoutError) as exc:
            raise SourceError("fetch_timeout") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise SourceError("fetch_transport_failed") from exc
        finally:
            connection.close()

    def fetch(self, url: str, metadata: dict | None = None) -> dict:
        original = canonical_url(url)
        current = original
        deadline = time.monotonic() + self.timeout
        redirects = []
        for _ in range(self.max_redirects + 1):
            if not in_domain_scope(current, self.scope):
                raise UnsafeURLError("domain_out_of_scope")
            addresses = self._addresses(current, deadline)
            if time.monotonic() >= deadline:
                raise SourceError("fetch_timeout")
            status, headers, data = self._request(current, addresses, deadline)
            if status in {301, 302, 303, 307, 308}:
                if not headers.get("location"):
                    raise SourceError("redirect_location_missing")
                redirects.append(current)
                current = canonical_url(urljoin(current, headers["location"]))
                continue
            if not 200 <= status < 300:
                raise SourceError(f"http_status_{status}")
            if len(data) > self.max_bytes:
                raise SourceError("source_too_large")
            document = parse_document(data, headers.get("content-type", "application/octet-stream"), current, metadata)
            document["retrieval"] = {"requested_locator": original, "redirects": redirects,
                                     "http_status": status, "received_bytes": len(data)}
            return document
        raise SourceError("redirect_limit_exceeded")
