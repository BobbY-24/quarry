"""Source and loader contract checks; no network or compiler execution."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
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


if __name__ == "__main__":
    unittest.main()
