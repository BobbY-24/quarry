"""Provision one reviewed SQLite release for offline CI, without installers.

Acquire the pinned archive separately with network access. Run build/check only
through the repository's fail-closed OS isolation launcher. The builder invokes
the system C compiler on the verified amalgamation; it executes no archive
scripts. check validates the SQLite actually loaded by the selected Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
VERSION = "3.51.3"
SOURCE_ID = "2026-03-13 10:38:09 737ae4a34738ffa0c3ff7f9bb18df914dd1cad163f28fd6b6e114a344fe6d618"
ARCHIVE_URL = "https://www.sqlite.org/2026/sqlite-amalgamation-3510300.zip"
ARCHIVE_SHA256 = "acb1e6f5d832484bf6d32b681e858c38add8b2acdfd42ac5df24b8afb46552b4"
C_SHA3_256 = "32d5424f97e0a7fc5ed2f6335afbb58be4e0298bd7117a34e39d345ff13d859e"
ARCHIVE_ROOT = "sqlite-amalgamation-3510300"
ARCHIVE_LIMIT = 5_000_000
SOURCE_LIMIT = 16_000_000
MEMBERS = {f"{ARCHIVE_ROOT}/{name}" for name in ("sqlite3.c", "sqlite3.h", "sqlite3ext.h", "shell.c")}
FLAGS = ["-O2", "-fPIC", "-DSQLITE_THREADSAFE=1", "-DSQLITE_ENABLE_COLUMN_METADATA"]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def controlled_path(path, parent):
    path = Path(path).absolute()
    if not path.resolve().is_relative_to(parent.resolve()):
        raise ValueError("CI artifact path is outside its allowed directory")
    current = path
    while current != parent.parent:
        if current.is_symlink():
            raise ValueError("CI artifact paths must not traverse symlinks")
        current = current.parent
    return path


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".quarry-sqlite-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def inspect_archive(archive):
    if archive.stat().st_size > ARCHIVE_LIMIT or sha256(archive) != ARCHIVE_SHA256:
        raise ValueError("SQLite archive size or SHA256 does not match the pin")
    with zipfile.ZipFile(archive) as bundle:
        items = bundle.infolist()
        names = [item.filename for item in items]
        if len(names) != len(set(names)) or set(names) != MEMBERS | {ARCHIVE_ROOT + "/"}:
            raise ValueError("SQLite archive has unexpected or duplicate members")
        if any(item.file_size < 0 or item.file_size > SOURCE_LIMIT for item in items) or sum(item.file_size for item in items) > SOURCE_LIMIT:
            raise ValueError("SQLite archive expands beyond the reviewed bound")
        source = {name.rsplit("/", 1)[1]: bundle.read(name) for name in sorted(MEMBERS) if not name.endswith("/shell.c")}
    if hashlib.sha3_256(source["sqlite3.c"]).hexdigest() != C_SHA3_256:
        raise ValueError("SQLite C source differs from the official release hash")
    return source


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "www.sqlite.org" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("SQLite download redirect leaves the official HTTPS host")
        return super().redirect_request(request, response, code, message, headers, url)


def acquire(archive):
    if archive.exists():
        inspect_archive(archive)
        return {"downloaded": False, "archive_sha256": ARCHIVE_SHA256}
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), OfficialRedirect(), urllib.request.HTTPSHandler(context=context))
    started = time.monotonic()
    chunks = []
    size = 0
    with opener.open(ARCHIVE_URL, timeout=10) as response:
        while True:
            if time.monotonic() - started > 30:
                raise TimeoutError("SQLite acquisition exceeded its finite deadline")
            chunk = response.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > ARCHIVE_LIMIT:
                raise ValueError("SQLite acquisition exceeded its size bound")
            chunks.append(chunk)
    payload = b"".join(chunks)
    if hashlib.sha256(payload).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Downloaded SQLite archive does not match the SHA256 pin")
    write_atomic(archive, payload)
    inspect_archive(archive)
    return {"downloaded": True, "archive_sha256": ARCHIVE_SHA256, "archive_bytes": size}


def compiler_arguments(system, source, output):
    if system == "Darwin":
        compiler = "/usr/bin/cc"
        linkage = ["-dynamiclib", "-Wl,-install_name,@rpath/libsqlite3.0.dylib", "-Wl,-compatibility_version,9.0.0", "-Wl,-current_version,9.51.3"]
        libraries = ["-lm", "-pthread"]
    elif system == "Linux":
        # Ubuntu's cc alias traverses /etc/alternatives, which intentionally is
        # absent from the sandbox. The GCC driver stays within /usr/bin.
        compiler = "/usr/bin/gcc"
        linkage = ["-shared", "-Wl,-soname,libsqlite3.so.0"]
        libraries = ["-lm", "-ldl", "-pthread"]
    else:
        raise ValueError("SQLite CI provisioning supports Linux and macOS only")
    return [compiler, *FLAGS, *linkage, str(source), "-o", str(output), *libraries]


def compile_bounded(command, environment):
    with tempfile.TemporaryFile(dir=environment["TMPDIR"]) as log:
        process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=120)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
            raise
        log.seek(0)
        output = log.read(1_048_577)
    if len(output) > 1_048_576 or process.returncode:
        raise RuntimeError("SQLite compiler failed or exceeded its bounded output")
    return hashlib.sha256(output).hexdigest()


def build(archive, prefix):
    source = inspect_archive(archive)
    source_root = controlled_path(prefix / "source", PROJECT / ".ci")
    library_root = controlled_path(prefix / "lib", PROJECT / ".ci")
    for name, payload in source.items():
        write_atomic(controlled_path(source_root / name, PROJECT / ".ci"), payload)
    library_root.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    filename = "libsqlite3.0.dylib" if system == "Darwin" else "libsqlite3.so.0"
    destination = controlled_path(library_root / filename, PROJECT / ".ci")
    environment = {"PATH": "/usr/bin:/bin", "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir())}
    if system == "Darwin":
        sdk = subprocess.check_output(["/usr/bin/xcrun", "--no-cache", "--show-sdk-path"], env=environment, timeout=10, text=True, stderr=subprocess.DEVNULL).strip()
        if not sdk.startswith(("/Library/Developer/CommandLineTools/", "/Applications/Xcode")) or not Path(sdk).is_dir():
            raise ValueError("Compiler SDK must be an installed system developer runtime")
        environment["SDKROOT"] = sdk
    descriptor, staging = tempfile.mkstemp(prefix=".quarry-sqlite-library-", dir=library_root)
    os.close(descriptor)
    try:
        command = compiler_arguments(system, source_root / "sqlite3.c", Path(staging))
        if system == "Linux" and not Path(command[0]).resolve().is_relative_to(Path("/usr/bin")):
            raise ValueError("Linux compiler must resolve inside the reviewed /usr/bin toolchain")
        output_hash = compile_bounded(command, environment)
        with open(staging, "rb") as binary:
            os.fsync(binary.fileno())
        os.replace(staging, destination)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
    alias = library_root / ("libsqlite3.dylib" if system == "Darwin" else "libsqlite3.so")
    if alias.is_symlink() and os.readlink(alias) == filename:
        alias.unlink()
    elif alias.exists() or alias.is_symlink():
        raise ValueError("SQLite library alias already contains an unexpected artifact")
    alias.symlink_to(filename)
    manifest = {"schema_version": 1, "sqlite_version": VERSION, "sqlite_source_id": SOURCE_ID,
            "platform": system, "machine": platform.machine(),
            "archive_sha256": ARCHIVE_SHA256, "sqlite3_c_sha3_256": C_SHA3_256,
            "compiler_arguments": [str(Path(value).relative_to(PROJECT)) if value.startswith(str(PROJECT) + "/") else value for value in command],
            "compiler_output_sha256": output_hash, "compiler_deadline_seconds": 120,
            "library_filename": filename, "library": destination.relative_to(PROJECT).as_posix(),
            "aliases": {alias.name: filename}, "library_sha256": sha256(destination)}
    write_atomic(controlled_path(prefix / "manifest.json", PROJECT / ".ci"), (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    return manifest


def validate_metadata(version, source_id, threadsafety, compile_options):
    if version != VERSION or source_id != SOURCE_ID:
        raise ValueError("Selected Python did not load the pinned patched SQLite release")
    if threadsafety != 3 or "THREADSAFE=1" not in compile_options:
        raise ValueError("Selected SQLite runtime must support serialized thread safety")


def check_runtime():
    import sqlite3
    with sqlite3.connect(":memory:") as database:
        source_id = database.execute("select sqlite_source_id()").fetchone()[0]
        options = sorted(row[0] for row in database.execute("pragma compile_options"))
        validate_metadata(sqlite3.sqlite_version, source_id, sqlite3.threadsafety, options)
        if database.execute("select json_extract('{\"value\":\"é🧪\"}', '$.value')").fetchone()[0] != "é🧪":
            raise ValueError("Selected SQLite runtime lacks working Unicode JSON extraction")
    with tempfile.TemporaryDirectory(prefix="quarry-sqlite-health-") as temporary:
        path = Path(temporary) / "health.sqlite3"
        with sqlite3.connect(path, timeout=2) as first, sqlite3.connect(path, timeout=2) as second:
            if first.execute("pragma journal_mode=WAL").fetchone()[0] != "wal":
                raise ValueError("Selected SQLite runtime cannot activate WAL")
            first.execute("create table health (id integer primary key, data text)")
            first.commit()
            first.execute("insert into health(data) values (?)", ("é🧪",))
            first.commit()
            if second.execute("select data from health").fetchone()[0] != "é🧪":
                raise ValueError("Selected SQLite WAL connection visibility is incorrect")
            first.execute("pragma wal_checkpoint(TRUNCATE)")
            if first.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise ValueError("Selected SQLite runtime failed its WAL integrity check")
    return {"sqlite_version": sqlite3.sqlite_version, "sqlite_source_id": source_id,
            "threadsafety": sqlite3.threadsafety, "compile_options": options,
            "checks": {"exact_release": True, "serialized_thread_safety": True, "unicode_json": True, "wal_two_connections": True, "integrity": True}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "build", "check"))
    parser.add_argument("--prefix", type=Path, default=PROJECT / ".ci/sqlite")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    prefix = controlled_path(args.prefix, PROJECT / ".ci")
    archive = controlled_path(prefix / "sqlite-amalgamation-3510300.zip", PROJECT / ".ci")
    report = controlled_path(args.report or PROJECT / f"verification/ci/sqlite-{args.command}.json", PROJECT / "verification")
    started = time.monotonic()
    try:
        result = acquire(archive) if args.command == "acquire" else build(archive, prefix) if args.command == "build" else check_runtime()
    except Exception as error:
        result = {"success": False, "category": type(error).__name__}
    else:
        result["success"] = True
    receipt = {"schema_version": 1, "stage": args.command, "sqlite_pin": VERSION,
               "source_url": ARCHIVE_URL, "source_release": "https://www.sqlite.org/releaselog/3_51_3.html",
               "platform": platform.system(), "machine": platform.machine(), "python_version": platform.python_version(),
               "elapsed_seconds": round(time.monotonic() - started, 3), **result}
    write_atomic(report, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"compile_options", "compiler_arguments"}}, sort_keys=True))
    return 0 if result["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
