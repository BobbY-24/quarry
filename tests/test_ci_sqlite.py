"""Source and loader contract checks; no network or compiler execution."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

SPEC = importlib.util.spec_from_file_location("quarry_ci_sqlite", Path(__file__).resolve().parents[1] / "tools/ci_sqlite.py")
CI_SQLITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI_SQLITE)


class SQLiteCIContractTests(unittest.TestCase):
    def test_archive_pin_is_checked_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "untrusted.zip"
            path.write_bytes(b"wrong archive")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                CI_SQLITE.inspect_archive(path)

    def test_unexpected_archive_members_are_rejected_after_digest_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../../unrelated.txt", "not an allowed source")
            with patch.object(CI_SQLITE, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "unexpected"):
                    CI_SQLITE.inspect_archive(path)

    def test_expansion_bound_applies_before_source_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(CI_SQLITE.ARCHIVE_ROOT + "/", b"")
                for name in CI_SQLITE.MEMBERS:
                    archive.writestr(name, b"x" * 20)
            with patch.object(CI_SQLITE, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()), patch.object(CI_SQLITE, "SOURCE_LIMIT", 30):
                with self.assertRaisesRegex(ValueError, "bound"):
                    CI_SQLITE.inspect_archive(path)

    def test_path_validation_rejects_symlink_and_outside_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            allowed = Path(temporary) / "allowed"
            allowed.mkdir()
            (allowed / "link").symlink_to(Path(temporary) / "other")
            for path in (Path(temporary) / "other/file", allowed / "link/file"):
                with self.assertRaises(ValueError):
                    CI_SQLITE.controlled_path(path, allowed)
            self.assertEqual(CI_SQLITE.controlled_path(allowed / "artifact", allowed), allowed / "artifact")

    def test_download_cannot_redirect_to_other_hosts_or_plaintext(self):
        handler = CI_SQLITE.OfficialRedirect()
        request = urllib.request.Request(CI_SQLITE.ARCHIVE_URL)
        for target in ("https://example.com/archive.zip", "http://www.sqlite.org/archive.zip", "https://user:password@www.sqlite.org/archive.zip"):
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "redirect", {}, target)

    def test_runtime_check_rejects_wrong_release_identity_or_thread_safety(self):
        metadata = (CI_SQLITE.VERSION, CI_SQLITE.SOURCE_ID, 3, ["THREADSAFE=1"])
        CI_SQLITE.validate_metadata(*metadata)
        for values in (("3.51.2", *metadata[1:]), (metadata[0], "unreviewed source", *metadata[2:]), (*metadata[:2], 1, metadata[3]), (*metadata[:3], ["THREADSAFE=0"])):
            with self.assertRaises(ValueError):
                CI_SQLITE.validate_metadata(*values)

    def test_build_uses_fixed_native_compiler_without_scripts(self):
        for system, compiler in (("Darwin", "/usr/bin/cc"), ("Linux", "/usr/bin/gcc")):
            command = CI_SQLITE.compiler_arguments(system, Path("source/sqlite3.c"), Path("lib/library"))
            self.assertEqual(command[0], compiler)
            self.assertIn("-DSQLITE_THREADSAFE=1", command)
            self.assertNotIn("/etc/alternatives", " ".join(command))
            self.assertNotIn("configure", command)
            self.assertNotIn("sh", command)
        with self.assertRaises(ValueError):
            CI_SQLITE.compiler_arguments("Windows", Path("source/sqlite3.c"), Path("lib/library"))

    def test_compiler_diagnostic_has_fixed_category_and_omits_paths_assignments(self):
        output = (b"<build>: fatal error: /private/fixture/include/stdio.h: No such file or directory\n"
                  b"error: KEY=synthetic-fixture-marker\n"
                  b"arbitrary noncompiler output\n")
        facts = CI_SQLITE.compiler_failure_facts(1, output, True)
        self.assertEqual(facts["compiler_failure_category"], "compiler_header_unavailable")
        self.assertIn("<path>", facts["compiler_diagnostics"][0])
        self.assertNotIn("/private", str(facts))
        self.assertNotIn("synthetic-fixture-marker", str(facts))
        self.assertNotIn("arbitrary noncompiler output", str(facts))

    def test_runtime_failure_facts_are_bounded_to_public_sqlite_identity(self):
        with self.assertRaises(CI_SQLITE.ProvisionFailure) as caught:
            CI_SQLITE.validate_metadata("3.51.2", CI_SQLITE.SOURCE_ID, 3, ["THREADSAFE=1"])
        self.assertEqual(caught.exception.category, "selected_runtime_release_mismatch")
        self.assertEqual(caught.exception.facts["actual_sqlite_version"], "3.51.2")
        self.assertEqual(CI_SQLITE.safe_runtime_facts("synthetic-key", "/private/fixture", "secret-like", []),
                         {"actual_sqlite_version": None, "actual_sqlite_source_id": None,
                          "actual_threadsafety": None, "serialized_compile_option": False})

    def test_native_linkage_parser_ignores_module_header_and_matches_only_dependencies(self):
        header = "/private/fixture/_sqlite3.cpython-312-darwin.so:\n"
        self.assertFalse(CI_SQLITE.shared_sqlite_dependency("Darwin", header + "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"))
        self.assertTrue(CI_SQLITE.shared_sqlite_dependency("Darwin", header + "\t@rpath/libsqlite3.0.dylib (compatibility version 9.0.0)\n"))
        self.assertTrue(CI_SQLITE.shared_sqlite_dependency("Linux", " 0x0001 (NEEDED) Shared library: [libsqlite3.so.0]\n"))
        self.assertFalse(CI_SQLITE.shared_sqlite_dependency("Linux", "/private/libsqlite3.so.0\n 0x0001 (NEEDED) Shared library: [libc.so.6]\n"))

    def test_builtin_runtime_facts_export_only_candidate_names_and_booleans(self):
        with patch.object(CI_SQLITE.Path, "is_file", return_value=False), patch.object(CI_SQLITE.subprocess, "Popen", side_effect=AssertionError("builtin needs no inspector")):
            facts = CI_SQLITE.native_runtime_facts(SimpleNamespace(), "Darwin")
        self.assertEqual(facts["sqlite_module_kind"], "builtin")
        self.assertIsNone(facts["native_sqlite_shared_dependency"])
        self.assertEqual(facts["homebrew_python_candidates"], {"3.11": False, "3.12": False, "3.13": False})
        self.assertNotIn("/", str(facts))

    def test_native_inspector_uses_fixed_tool_clean_env_and_never_exports_raw_output(self):
        commands = []
        def inspect(command, **options):
            commands.append(command)
            self.assertEqual(set(options["env"]), {"PATH", "TMPDIR"})
            options["stdout"].write(b"/private/fixture/_sqlite3.so:\n\t@rpath/libsqlite3.0.dylib (compatibility version 9.0.0)\nprivate-fixture-marker\n")
            return SimpleNamespace(wait=lambda **_: 0, returncode=0)
        with patch.object(CI_SQLITE.Path, "is_file", return_value=True), patch.object(CI_SQLITE.subprocess, "Popen", side_effect=inspect):
            facts = CI_SQLITE.native_runtime_facts(SimpleNamespace(__file__="/private/fixture/_sqlite3.so"), "Darwin")
        self.assertEqual(commands, [["/usr/bin/otool", "-L", "/private/fixture/_sqlite3.so"]])
        self.assertIs(facts["native_sqlite_shared_dependency"], True)
        self.assertEqual(facts["native_linkage_inspection"], "inspected")
        self.assertNotIn("private-fixture-marker", str(facts))
        self.assertNotIn("/private", str(facts))


if __name__ == "__main__":
    unittest.main()
