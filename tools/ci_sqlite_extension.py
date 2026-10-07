"""Build CPython's stock native SQLite module for static macOS CI runtimes.

Acquire the exact official source archive separately. Run build inside the
existing OS sandbox. Only the unmodified Modules/_sqlite C/header files are
compiled; no installer, configure script, Python shim or .pth file is executed.
The overlay contains one ABI-named native extension and its build manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import ssl
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("quarry_pinned_sqlite", PROJECT / "tools/ci_sqlite.py")
SQLITE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SQLITE)

# The 3.11/3.12 digests are the official release .sigstore messageDigest values;
# 3.13.15 publishes SHA256 directly on its release page. Signature verification
# is not claimed here. Every archive is checked against these committed pins.
CPYTHON_SOURCES = {
    "3.11.9": "9b1e896523fc510691126c864406d9360a3d1e986acbda59cda57b5abda45b87",
    "3.12.10": "07ab697474595e06f06647417d3c7fa97ded07afc1a7e4454c5639919b46eaea",
    "3.13.15": "1e66a7945a48390ee4c2a4268a0e4185884059a13c4aab6d148aa208deea4a76",
}
C_FILES = {name + ".c" for name in ("blob", "connection", "cursor", "microprotocols", "module", "prepare_protocol", "row", "statement", "util")}
ARCHIVE_LIMIT = 30_000_000
EXPANDED_LIMIT = 250_000_000
SOURCE_LIMIT = 8_000_000
MEMBER_LIMIT = 12_000


def source_url(version):
    if version not in CPYTHON_SOURCES:
        raise SQLITE.ProvisionFailure("unreviewed_cpython_source_version")
    return f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz"


def validate_abi(version, implementation, suffix, soabi, *, builtin, debug, gil_disabled):
    if implementation != "cpython" or version not in CPYTHON_SOURCES:
        raise SQLITE.ProvisionFailure("unreviewed_cpython_runtime")
    if builtin:
        raise SQLITE.ProvisionFailure("builtin_sqlite_cannot_use_native_overlay")
    tag = "cpython-" + "".join(version.split(".")[:2]) + "-darwin"
    if soabi != tag or suffix != "." + tag + ".so" or debug or gil_disabled:
        raise SQLITE.ProvisionFailure("unreviewed_cpython_module_abi")
    return "_sqlite3" + suffix


def selected_runtime():
    import _sqlite3
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "x86_64"}:
        raise SQLITE.ProvisionFailure("native_sqlite_overlay_is_macos_ci_only")
    version = platform.python_version()
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    soabi = sysconfig.get_config_var("SOABI")
    filename = validate_abi(version, sys.implementation.name, suffix, soabi,
                            builtin=getattr(_sqlite3, "__file__", None) is None,
                            debug=bool(sysconfig.get_config_var("Py_DEBUG")),
                            gil_disabled=bool(sysconfig.get_config_var("Py_GIL_DISABLED")))
    return {"python_version": version, "implementation": "cpython", "soabi": soabi,
            "extension_suffix": suffix, "module_filename": filename,
            "platform": "Darwin", "machine": platform.machine()}


class PythonReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "www.python.org" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise SQLITE.ProvisionFailure("cpython_source_redirect_left_official_host")
        return super().redirect_request(request, response, code, message, headers, url)


def acquire(archive, version):
    expected = CPYTHON_SOURCES[version]
    if archive.exists():
        if archive.stat().st_size > ARCHIVE_LIMIT or SQLITE.sha256(archive) != expected:
            raise SQLITE.ProvisionFailure("cpython_source_archive_pin_mismatch")
        return {"downloaded": False, "archive_sha256": expected}
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PythonReleaseRedirect(), urllib.request.HTTPSHandler(context=context))
    started = time.monotonic()
    chunks, size = [], 0
    with opener.open(source_url(version), timeout=10) as response:
        while True:
            if time.monotonic() - started > 60:
                raise SQLITE.ProvisionFailure("cpython_source_acquisition_timeout")
            chunk = response.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > ARCHIVE_LIMIT:
                raise SQLITE.ProvisionFailure("cpython_source_archive_size_limit")
            chunks.append(chunk)
    payload = b"".join(chunks)
    if hashlib.sha256(payload).hexdigest() != expected:
        raise SQLITE.ProvisionFailure("cpython_source_archive_pin_mismatch")
    SQLITE.write_atomic(archive, payload)
    return {"downloaded": True, "archive_sha256": expected, "archive_bytes": size}


def read_sources(archive, version, expected_sha256):
    if archive.stat().st_size > ARCHIVE_LIMIT or SQLITE.sha256(archive) != expected_sha256:
        raise SQLITE.ProvisionFailure("cpython_source_archive_pin_mismatch")
    root = f"Python-{version}"
    selected, expanded, members, bytes_selected = {}, 0, 0, 0
    with tarfile.open(archive, "r|xz") as bundle:
        for item in bundle:
            members += 1
            expanded += item.size
            if members > MEMBER_LIMIT or item.size < 0 or expanded > EXPANDED_LIMIT:
                raise SQLITE.ProvisionFailure("cpython_source_expansion_limit")
            prefix = root + "/Modules/_sqlite/"
            if item.name == root + "/LICENSE":
                relative = "LICENSE"
            elif item.name.startswith(prefix):
                relative = item.name[len(prefix):]
                if not relative.endswith((".c", ".h")):
                    continue
                path = PurePosixPath(relative)
                if path.is_absolute() or ".." in path.parts or len(path.parts) > 2 or not re.fullmatch(r"[A-Za-z0-9_./]+", relative):
                    raise SQLITE.ProvisionFailure("cpython_source_path_rejected")
                if len(path.parts) == 2 and path.parts[0] != "clinic":
                    raise SQLITE.ProvisionFailure("cpython_source_path_rejected")
            else:
                continue
            if not item.isfile() or relative in selected:
                raise SQLITE.ProvisionFailure("cpython_source_member_rejected")
            bytes_selected += item.size
            if item.size > 2_000_000 or bytes_selected > SOURCE_LIMIT:
                raise SQLITE.ProvisionFailure("cpython_curated_source_size_limit")
            stream = bundle.extractfile(item)
            if stream is None:
                raise SQLITE.ProvisionFailure("cpython_source_member_unreadable")
            payload = stream.read(item.size + 1)
            if len(payload) != item.size:
                raise SQLITE.ProvisionFailure("cpython_source_member_size_mismatch")
            selected[relative] = payload
    if {name for name in selected if name.endswith(".c")} != C_FILES or "LICENSE" not in selected:
        raise SQLITE.ProvisionFailure("cpython_stock_sqlite_sources_incomplete")
    return selected


def sqlite_library(prefix):
    manifest_path = SQLITE.controlled_path(prefix / "manifest.json", PROJECT / ".ci")
    if manifest_path.stat().st_size > 16_384:
        raise SQLITE.ProvisionFailure("sqlite_manifest_size_limit")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("sqlite_version") != SQLITE.VERSION or manifest.get("sqlite_source_id") != SQLITE.SOURCE_ID
            or manifest.get("archive_sha256") != SQLITE.ARCHIVE_SHA256
            or manifest.get("sqlite3_c_sha3_256") != SQLITE.C_SHA3_256
            or manifest.get("platform") != "Darwin" or manifest.get("machine") != platform.machine()
            or manifest.get("library_filename") != "libsqlite3.0.dylib"):
        raise SQLITE.ProvisionFailure("sqlite_library_release_mismatch")
    library = SQLITE.controlled_path(prefix / "lib/libsqlite3.0.dylib", PROJECT / ".ci")
    if not 1 <= library.stat().st_size <= 32_000_000 or SQLITE.sha256(library) != manifest.get("library_sha256"):
        raise SQLITE.ProvisionFailure("sqlite_library_build_receipt_mismatch")
    alias = prefix / "lib/libsqlite3.dylib"
    if not alias.is_symlink() or os.readlink(alias) != library.name:
        raise SQLITE.ProvisionFailure("sqlite_library_alias_mismatch")
    archive = SQLITE.controlled_path(prefix / (SQLITE.ARCHIVE_ROOT + ".zip"), PROJECT / ".ci")
    header = SQLITE.inspect_archive(archive)["sqlite3.h"]
    header_path = SQLITE.controlled_path(prefix / "source/sqlite3.h", PROJECT / ".ci")
    if not header_path.is_file() or header_path.stat().st_size != len(header) or header_path.read_bytes() != header:
        raise SQLITE.ProvisionFailure("sqlite_compilation_header_pin_mismatch")
    return library, manifest["library_sha256"], hashlib.sha256(header).hexdigest()


def installed_headers(version):
    directories = {Path(sysconfig.get_path(name)).resolve() for name in ("include", "platinclude")}
    headers = {}
    for directory in directories:
        if not directory.is_dir():
            raise SQLITE.ProvisionFailure("cpython_installed_headers_unavailable")
        for path in directory.rglob("*.h"):
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
                raise SQLITE.ProvisionFailure("cpython_installed_header_rejected")
            key = path.relative_to(directory).as_posix()
            value = SQLITE.sha256(path)
            if key in headers and headers[key] != value:
                raise SQLITE.ProvisionFailure("cpython_installed_header_conflict")
            headers[key] = value
            if len(headers) > 1000:
                raise SQLITE.ProvisionFailure("cpython_installed_header_count_limit")
        marker = directory / "patchlevel.h"
        if not marker.is_file() or not re.search(r'^#define\s+PY_VERSION\s+"' + re.escape(version) + r'"\s*$', marker.read_text(), re.MULTILINE):
            raise SQLITE.ProvisionFailure("cpython_installed_header_version_mismatch")
        if not (directory / "Python.h").is_file() or not (directory / "pyconfig.h").is_file():
            raise SQLITE.ProvisionFailure("cpython_installed_headers_incomplete")
    return sorted(directories), headers


def compiler_arguments(headers, source_root, library_root, destination):
    arguments = ["/usr/bin/cc", "-O2", "-fPIC", "-bundle", "-undefined", "dynamic_lookup", "-DPy_BUILD_CORE_MODULE=1"]
    # Match the exact header to the pinned library before system/Python paths.
    arguments.extend(["-I", str(library_root.parent / "source")])
    for directory in headers:
        arguments.extend(["-I", str(directory), "-I", str(directory / "internal")])
    arguments.extend(["-I", str(source_root)])
    arguments.extend(str(source_root / name) for name in sorted(C_FILES))
    arguments.extend(["-L", str(library_root), "-Wl,-rpath," + str(library_root), "-lsqlite3", "-o", str(destination)])
    return arguments


def overlay_layout(root, filename):
    SQLITE.controlled_path(root, PROJECT / ".ci")
    if root.exists() and any(path.name not in {filename, "manifest.json"} or path.is_symlink() or not path.is_file() for path in root.iterdir()):
        raise SQLITE.ProvisionFailure("native_overlay_has_unreviewed_artifacts")


def source_layout(root, selected):
    """Prevent pre-existing extra headers from changing quoted include lookup."""
    SQLITE.controlled_path(root, PROJECT / ".ci")
    if not root.exists():
        return
    directories = {PurePosixPath(name).parent.as_posix() for name in selected} - {"."}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or (path.is_dir() and name not in directories) or (not path.is_dir() and (not path.is_file() or name not in selected)):
            raise SQLITE.ProvisionFailure("native_source_has_unreviewed_artifacts")


def build(prefix, runtime):
    version = runtime["python_version"]
    archive = SQLITE.controlled_path(prefix / f"Python-{version}.tar.xz", PROJECT / ".ci")
    selected = read_sources(archive, version, CPYTHON_SOURCES[version])
    library, library_hash, sqlite_header_hash = sqlite_library(prefix)
    header_roots, header_hashes = installed_headers(version)
    source_root = SQLITE.controlled_path(prefix / "extension-source" / version, PROJECT / ".ci")
    source_layout(source_root, selected)
    for name, payload in selected.items():
        SQLITE.write_atomic(SQLITE.controlled_path(source_root / name, PROJECT / ".ci"), payload)
    root = SQLITE.controlled_path(prefix / "python", PROJECT / ".ci")
    overlay_layout(root, runtime["module_filename"])
    root.mkdir(parents=True, exist_ok=True)
    destination = SQLITE.controlled_path(root / runtime["module_filename"], PROJECT / ".ci")
    environment = {"PATH": "/usr/bin:/bin", "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir())}
    sdk = subprocess.check_output(["/usr/bin/xcrun", "--no-cache", "--show-sdk-path"], env=environment, timeout=10, text=True, stderr=subprocess.DEVNULL).strip()
    if not sdk.startswith(("/Library/Developer/CommandLineTools/", "/Applications/Xcode")) or not Path(sdk).is_dir():
        raise SQLITE.ProvisionFailure("reviewed_system_compiler_sdk_unavailable")
    environment["SDKROOT"] = sdk
    descriptor, staging = tempfile.mkstemp(prefix=".native-sqlite-", suffix=".so", dir=root)
    os.close(descriptor)
    try:
        command = compiler_arguments(header_roots, source_root, library.parent, Path(staging))
        compiler_hash = SQLITE.compile_bounded(command, environment)
        with open(staging, "rb") as native:
            os.fsync(native.fileno())
        os.replace(staging, destination)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
    manifest = {"schema_version": 1, "runtime_component": "stock_cpython_sqlite_native_extension",
                "license_identifiers": ["PSF-2.0", "Zlib"], "source_checkpoint": "CPython v" + version,
                "source_url": source_url(version), "source_release": "https://www.python.org/downloads/release/python-" + version.replace(".", "") + "/",
                "source_archive_sha256": CPYTHON_SOURCES[version],
                "source_files_sha256": {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(selected.items())},
                "installed_headers_sha256": header_hashes,
                "sqlite_version": SQLITE.VERSION, "sqlite_source_id": SQLITE.SOURCE_ID, "sqlite_library_sha256": library_hash,
                "sqlite_header_sha256": sqlite_header_hash,
                "sqlite_archive_sha256": SQLITE.ARCHIVE_SHA256,
                "native_module_sha256": SQLITE.sha256(destination),
                "compiler_output_sha256": compiler_hash, "compiler_deadline_seconds": 120,
                "compiler_arguments": [str(Path(value).relative_to(PROJECT)) if value.startswith(str(PROJECT) + "/") else value for value in command],
                **runtime}
    SQLITE.write_atomic(SQLITE.controlled_path(root / "manifest.json", PROJECT / ".ci"), (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    overlay_layout(root, runtime["module_filename"])
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "build"))
    parser.add_argument("--prefix", type=Path, default=PROJECT / ".ci/sqlite")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    prefix = SQLITE.controlled_path(args.prefix, PROJECT / ".ci")
    if prefix != PROJECT / ".ci/sqlite":
        parser.error("Native SQLite overlay must use the fixed .ci/sqlite artifact")
    report = SQLITE.controlled_path(args.report or PROJECT / f"verification/ci/sqlite-extension-{args.command}.json", PROJECT / "verification")
    started = time.monotonic()
    try:
        runtime = selected_runtime()
        archive = SQLITE.controlled_path(prefix / f"Python-{runtime['python_version']}.tar.xz", PROJECT / ".ci")
        result = acquire(archive, runtime["python_version"]) if args.command == "acquire" else build(prefix, runtime)
    except SQLITE.ProvisionFailure as error:
        result = {"success": False, "category": error.category, **error.facts}
    except Exception as error:
        result = {"success": False, "category": type(error).__name__}
    else:
        result["success"] = True
    receipt = {"schema_version": 1, "stage": args.command, "elapsed_seconds": round(time.monotonic() - started, 3), **result}
    SQLITE.write_atomic(report, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"compiler_arguments", "source_files_sha256", "installed_headers_sha256"}}, sort_keys=True))
    return 0 if result["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
