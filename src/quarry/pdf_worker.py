"""Reviewed, finite PDF parser worker. Receives only PDF bytes on stdin.

This process uses no provider, project, recipe, network client, or credentials.
Production uses a clean environment and OS resource limits. It is resource
isolation, not a filesystem/network security sandbox; high-risk documents should
also be processed under the documented macOS/Linux OS isolation workflow.
"""
from __future__ import annotations

import json
import logging
import os
import resource
import sys
import threading
import time
from io import BytesIO

MAX_BYTES = 100_000_000
MAX_PAGES = 2_000
MAX_CHARACTERS = 20_000_000
MAX_OUTPUT_BYTES = 90_000_000
MAX_MEMORY_BYTES = 1_073_741_824


def guard_memory():
    """Sample only this process; a parser crash/exit also ends the daemon."""
    while True:
        # Darwin reports bytes, Linux KiB. Linux additionally enforces RLIMIT_AS.
        maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        resident_bytes = maximum_rss if sys.platform == "darwin" else maximum_rss * 1024
        if resident_bytes > MAX_MEMORY_BYTES:
            os._exit(72)
        time.sleep(0.05)


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    # macOS exposes RLIMIT_AS but rejects useful finite values. This worker
    # samples its own RSS; Linux enforces the kernel address-space limit.
    if sys.platform == "linux" and hasattr(resource, "RLIMIT_AS"):
        resource.setrlimit(resource.RLIMIT_AS, (1_073_741_824, 1_073_741_824))


def emit(record):
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_OUTPUT_BYTES:
        payload = b'{"error":"pdf_output_limit_exceeded"}'
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main():
    try:
        limits()
    except (OSError, ValueError):
        emit({"error": "pdf_resource_limits_unavailable"})
        return 0
    threading.Thread(target=guard_memory, daemon=True, name="pdf-memory-guard").start()
    # Library warnings can contain raw PDF headers or object values. Expose only
    # enumerated safe errors over stdout; the parent additionally discards stderr.
    logging.disable(logging.CRITICAL)
    try:
        from pypdf import PdfReader
    except ImportError:
        emit({"error": "pdf_dependency_unavailable"})
        return 0
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            emit({"error": "local_source_too_large"})
            return 0
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            emit({"error": "encrypted_pdf_unsupported"})
            return 0
        if len(reader.pages) > MAX_PAGES:
            emit({"error": "pdf_page_limit_exceeded"})
            return 0
        pages = []
        characters = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            characters += len(text) + 2
            if characters > MAX_CHARACTERS:
                emit({"error": "extracted_text_too_large"})
                return 0
            pages.append(text)
        title = reader.metadata.title if reader.metadata else None
        emit({"pages": pages, "title": str(title)[:4096] if title else None})
    except MemoryError:
        emit({"error": "pdf_resource_limit_exceeded"})
    except Exception:
        emit({"error": "pdf_parse_failed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
