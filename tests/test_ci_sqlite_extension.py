"""Native stdlib component provenance/admission; no compiler or network calls."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

SPEC = importlib.util.spec_from_file_location("quarry_native_sqlite", Path(__file__).resolve().parents[1] / "tools/ci_sqlite_extension.py")
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class NativeSQLiteRuntimeTests(unittest.TestCase):
    def archive(self, root, extras=()):
        path = root / "source.tar.xz"
        with tarfile.open(path, "w:xz") as archive:
            for name in sorted(NATIVE.C_FILES) + ["connection.h", "clinic/module.c.h"]:
                item = tarfile.TarInfo("Python-3.12.10/Modules/_sqlite/" + name)
                payload = b"/* synthetic fixture; never compiled */\n"
                item.size = len(payload)
                archive.addfile(item, io.BytesIO(payload))
            item = tarfile.TarInfo("Python-3.12.10/LICENSE")
            payload = b"Synthetic licensing fixture\n"
            item.size = len(payload)
            archive.addfile(item, io.BytesIO(payload))
            for item, payload in extras:
                archive.addfile(item, io.BytesIO(payload) if payload is not None else None)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_only_exact_reviewed_native_abis_are_admitted(self):
        for version in NATIVE.CPYTHON_SOURCES:
            soabi = "cpython-" + "".join(version.split(".")[:2]) + "-darwin"
            suffix = "." + soabi + ".so"
            self.assertEqual(NATIVE.validate_abi(version, "cpython", suffix, soabi, builtin=False, debug=False, gil_disabled=False), "_sqlite3" + suffix)
        cases = [("3.12.14", "cpython", ".cpython-312-darwin.so", "cpython-312-darwin", False, False, False),
                 ("3.12.10", "pypy", ".cpython-312-darwin.so", "cpython-312-darwin", False, False, False),
                 ("3.12.10", "cpython", ".cpython-311-darwin.so", "cpython-311-darwin", False, False, False),
                 ("3.12.10", "cpython", ".cpython-312-darwin.so", "cpython-312-darwin", True, False, False),
                 ("3.12.10", "cpython", ".cpython-312-darwin.so", "cpython-312-darwin", False, True, False),
                 ("3.12.10", "cpython", ".cpython-312-darwin.so", "cpython-312-darwin", False, False, True)]
        for version, implementation, suffix, soabi, builtin, debug, gil in cases:
            with self.assertRaises(NATIVE.SQLITE.ProvisionFailure):
                NATIVE.validate_abi(version, implementation, suffix, soabi, builtin=builtin, debug=debug, gil_disabled=gil)

    def test_archive_digest_is_required_before_source_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, _ = self.archive(Path(temporary))
            with self.assertRaisesRegex(NATIVE.SQLITE.ProvisionFailure, "pin_mismatch"):
                NATIVE.read_sources(path, "3.12.10", "0" * 64)

    def test_extracts_stock_translation_units_and_headers_without_scripts(self):
        item = tarfile.TarInfo("Python-3.12.10/Modules/_sqlite/setup.py")
        item.size = 6
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = self.archive(Path(temporary), [(item, b"unsafe")])
            selected = NATIVE.read_sources(path, "3.12.10", digest)
        self.assertEqual({name for name in selected if name.endswith(".c")}, NATIVE.C_FILES)
        self.assertIn("clinic/module.c.h", selected)
        self.assertIn("LICENSE", selected)
        self.assertNotIn("setup.py", selected)

    def test_rejects_curated_symlink_duplicate_and_traversal(self):
        link = tarfile.TarInfo("Python-3.12.10/Modules/_sqlite/secret.h")
        link.type = tarfile.SYMTYPE
        link.linkname = "/private/fixture"
        duplicate = tarfile.TarInfo("Python-3.12.10/Modules/_sqlite/module.c")
        duplicate.size = 1
        traversal = tarfile.TarInfo("Python-3.12.10/Modules/_sqlite/../secret.h")
        traversal.size = 1
        for entry, payload in ((link, None), (duplicate, b"x"), (traversal, b"x")):
            with self.subTest(entry=entry.name), tempfile.TemporaryDirectory() as temporary:
                path, digest = self.archive(Path(temporary), [(entry, payload)])
                with self.assertRaises(NATIVE.SQLITE.ProvisionFailure):
                    NATIVE.read_sources(path, "3.12.10", digest)

    def test_expansion_and_member_bounds_stop_before_unbounded_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = self.archive(Path(temporary))
            for variable, limit in (("MEMBER_LIMIT", 3), ("EXPANDED_LIMIT", 2), ("SOURCE_LIMIT", 3)):
                with self.subTest(variable=variable), patch.object(NATIVE, variable, limit):
                    with self.assertRaises(NATIVE.SQLITE.ProvisionFailure):
                        NATIVE.read_sources(path, "3.12.10", digest)

    def test_download_redirect_never_expands_to_unreviewed_service(self):
        handler = NATIVE.PythonReleaseRedirect()
        request = urllib.request.Request(NATIVE.source_url("3.12.10"))
        for url in ("http://www.python.org/archive", "https://example.com/archive", "https://user:password@www.python.org/archive"):
            with self.assertRaises(NATIVE.SQLITE.ProvisionFailure):
                handler.redirect_request(request, None, 302, "redirect", {}, url)

    def test_compile_uses_verified_sqlite_header_first_and_exact_native_units(self):
        headers = [Path("/reviewed/python/include/python3.12")]
        source = Path("/reviewed/project/.ci/sqlite/extension-source/3.12.10")
        library = Path("/reviewed/project/.ci/sqlite/lib")
        command = NATIVE.compiler_arguments(headers, source, library, Path("/reviewed/project/.ci/sqlite/python/native.so"))
        self.assertEqual(command[0], "/usr/bin/cc")
        self.assertEqual(command[command.index("-I") + 1], str(library.parent / "source"))
        self.assertEqual({Path(value).name for value in command if value.endswith(".c")}, NATIVE.C_FILES)
        self.assertIn("-Wl,-rpath," + str(library), command)
        self.assertNotIn("configure", command)
        self.assertNotIn("sh", command)

    def test_curated_source_directory_rejects_unreviewed_extra_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            root = project / ".ci/sqlite/extension-source/3.12.10"
            root.mkdir(parents=True)
            (root / "module.c").write_bytes(b"inert fixture")
            (root / "clinic").mkdir()
            (root / "clinic/module.c.h").write_bytes(b"inert fixture")
            selected = {"module.c": b"inert fixture", "clinic/module.c.h": b"inert fixture"}
            with patch.object(NATIVE, "PROJECT", project):
                NATIVE.source_layout(root, selected)
                (root / "unreviewed.h").write_bytes(b"inert fixture")
                with self.assertRaisesRegex(NATIVE.SQLITE.ProvisionFailure, "unreviewed_artifacts"):
                    NATIVE.source_layout(root, selected)

    def test_overlay_accepts_only_expected_native_module_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            root = project / ".ci/sqlite/python"
            root.mkdir(parents=True)
            name = "_sqlite3.cpython-312-darwin.so"
            (root / name).write_bytes(b"inert fixture; never loaded")
            (root / "manifest.json").write_text("{}")
            with patch.object(NATIVE, "PROJECT", project):
                NATIVE.overlay_layout(root, name)
                for extra in ("_sqlite3.py", "sitecustomize.py", "unsafe.pth"):
                    (root / extra).write_text("inert fixture")
                    with self.assertRaises(NATIVE.SQLITE.ProvisionFailure):
                        NATIVE.overlay_layout(root, name)
                    (root / extra).unlink()
                (root / name).unlink()
                (root / name).symlink_to(project / "unrelated")
                with self.assertRaises(NATIVE.SQLITE.ProvisionFailure):
                    NATIVE.overlay_layout(root, name)


if __name__ == "__main__":
    unittest.main()
