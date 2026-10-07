"""Finite POSIX pipe exchange. A deadline is not a security sandbox.

Only reviewed operator commands belong here. All descendants must remain in the
created session/process group; deliberately daemonizing commands are unsupported.
The guardian monitors owner pipe EOF and a monotonic deadline independently.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class TransportResult:
    stdout: bytes
    returncode: int


class TransportFailure(Exception):
    def __init__(self, reason, *, started=False, retryable=False):
        super().__init__(reason)
        self.reason, self.started, self.retryable = reason, started, retryable


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass


def bounded_exchange(command, payload, *, env, timeout_seconds,
                     max_request_bytes=20_000_000, max_response_bytes=8_000_000,
                     cancellation_event=None):
    """Return bounded stdout, reaping the direct child and killing descendants.

    A local timeout/crash can follow remote acceptance. Caller must retain that
    uncertainty. stderr is intentionally discarded, never persisted as errors.
    """
    if os.name != "posix":
        raise TransportFailure("process_boundary_requires_posix")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 1800):
        raise TransportFailure("invalid_transport_deadline")
    if (type(max_request_bytes) is not int or not 1 <= max_request_bytes <= 20_000_000
            or type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 8_000_000):
        raise TransportFailure("invalid_transport_limits")
    if not isinstance(payload, bytes) or len(payload) > max_request_bytes:
        raise TransportFailure("transport_request_size_limit")
    if cancellation_event is not None and cancellation_event.is_set():
        raise TransportFailure("transport_cancelled_before_start")
    deadline = time.monotonic() + timeout_seconds
    child = None
    owner_read = owner_write = None
    selector = selectors.DefaultSelector()
    try:
        try:
            owner_read, owner_write = os.pipe()
            launcher = [sys.executable, "-m", "termfinder.process_launcher", str(owner_read),
                        str(deadline), json.dumps(command, ensure_ascii=True)]
            child = subprocess.Popen(launcher, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=env, close_fds=True,
                                     start_new_session=True, pass_fds=(owner_read,))
            os.close(owner_read)
            owner_read = None
        except OSError:
            raise TransportFailure("transport_worker_not_started") from None
        os.set_blocking(child.stdin.fileno(), False)
        os.set_blocking(child.stdout.fileno(), False)
        selector.register(child.stdout, selectors.EVENT_READ, "read")
        if payload:
            selector.register(child.stdin, selectors.EVENT_WRITE, "write")
        else:
            child.stdin.close()
        output = bytearray()
        offset = 0
        while True:
            if cancellation_event is not None and cancellation_event.is_set():
                raise TransportFailure("transport_cancelled_outcome_unknown", started=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportFailure("request_wall_timeout_outcome_unknown", started=True, retryable=True)
            for key, _ in selector.select(min(.05, remaining)):
                if key.data == "write":
                    try:
                        offset += os.write(key.fd, payload[offset:offset + 65536])
                    except BrokenPipeError:
                        offset = len(payload)
                    except BlockingIOError:
                        continue
                    if offset == len(payload):
                        selector.unregister(child.stdin)
                        child.stdin.close()
                else:
                    try:
                        block = os.read(key.fd, min(65536, max_response_bytes - len(output) + 1))
                    except BlockingIOError:
                        continue
                    if not block:
                        selector.unregister(child.stdout)
                        child.stdout.close()
                    else:
                        output.extend(block)
                        if len(output) > max_response_bytes:
                            raise TransportFailure("transport_response_size_limit", started=True)
            if child.poll() is not None and child.stdout.closed:
                return TransportResult(bytes(output), child.returncode)
    except TransportFailure:
        raise
    except (OSError, ValueError):
        raise TransportFailure("transport_local_io_outcome_unknown", started=child is not None) from None
    finally:
        selector.close()
        if child is not None:
            _kill_group(child)  # also after success: a child must not leak workers
            for stream in (child.stdin, child.stdout):
                if stream and not stream.closed:
                    stream.close()
            try:
                child.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                pass  # finite cleanup; direct child was SIGKILLed
        if owner_read is not None:
            os.close(owner_read)
        if owner_write is not None:
            try:
                os.write(owner_write, b"D")
            except OSError:
                pass
            finally:
                os.close(owner_write)
