"""Launcher diagnostics stay useful without exposing arbitrary startup output."""
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("quarry_ci_offline", Path(__file__).resolve().parents[1] / "tools" / "ci_offline.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class IsolationDiagnosticsTests(unittest.TestCase):
    def test_linux_requires_network_namespace_and_boolean_assertions(self):
        for probe in ({}, [], {"unrelated_file_read_denied": 1, "network_denied": True},
                      {"unrelated_file_read_denied": True, "network_denied": True}):
            with self.subTest(probe=probe):
                _, category = ci.isolation_result(0, json.dumps(probe), linux=True)
                self.assertIsNotNone(category)
        probe = {"unrelated_file_read_denied": True, "network_denied": True,
                 "host_network_namespace_isolated": True, "application_capabilities_dropped": True,
                 "no_new_privileges": True, "synthetic_account_home": True}
        self.assertEqual(ci.isolation_result(0, json.dumps(probe), linux=True), (probe, None))
        for name in ("application_capabilities_dropped", "no_new_privileges", "synthetic_account_home"):
            denied = dict(probe, **{name: False})
            self.assertIsNotNone(ci.isolation_result(0, json.dumps(denied), linux=True)[1])

    def test_failed_assertion_and_nonzero_exit_remain_fail_closed(self):
        probe = {"unrelated_file_read_denied": True, "network_denied": False}
        self.assertEqual(ci.isolation_result(0, json.dumps(probe), linux=False)[1], "isolation_assertion_failed")
        probe["network_denied"] = True
        self.assertIsNotNone(ci.isolation_result(1, json.dumps(probe), linux=False)[1])

    def test_startup_categories_never_return_raw_diagnostics(self):
        cases = [(1, "bwrap: Creating new namespace failed: Operation not permitted", "namespace_setup_failed"),
                 (1, "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted", "private_loopback_setup_failed"),
                 (1, "bwrap: Can't bind mount /private/location: Permission denied", "filesystem_setup_failed"),
                 (1, "bwrap: execvp /private/runtime: No such file or directory", "interpreter_launch_failed"),
                 (124, "arbitrary secret-like output", "startup_timeout"),
                 (1, "arbitrary secret-like output", "unrecognized_startup_output")]
        for code, output, category in cases:
            with self.subTest(category=category):
                self.assertEqual(ci.isolation_result(code, output, linux=True), ({}, category))

    def test_launcher_diagnostic_omits_paths_assignments_and_nonlauncher_output(self):
        self.assertEqual(ci.launcher_diagnostic("bwrap: Can't read /private/location: denied\nmore output"),
                         "bwrap: Can't read <path>: denied")
        for output in ("Traceback: personal diagnostic", "bwrap: KEY=synthetic-canary", "bwrap:" + "a" * 501):
            self.assertIsNone(ci.launcher_diagnostic(output))


class SQLiteArtifactTests(unittest.TestCase):
    def test_runtime_rejects_unpinned_library_hash_or_outside_path(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                ci.sqlite_runtime(project, root)
        # Inspect a synthetic artifact in a temporary project, with the actual
        # reviewed tool copied as data. No native library is loaded by this test.
        with tempfile.TemporaryDirectory() as temporary:
            root_project = Path(temporary)
            (root_project / "tools").mkdir()
            (root_project / "tools/ci_sqlite.py").write_bytes((project / "tools/ci_sqlite.py").read_bytes())
            sqlite_spec = importlib.util.spec_from_file_location("pins", root_project / "tools/ci_sqlite.py")
            pins = importlib.util.module_from_spec(sqlite_spec)
            sqlite_spec.loader.exec_module(pins)
            root = root_project / ".ci/sqlite"
            (root / "lib").mkdir(parents=True)
            filename = "libsqlite3.0.dylib" if ci.sys.platform == "darwin" else "libsqlite3.so.0"
            alias = "libsqlite3.dylib" if ci.sys.platform == "darwin" else "libsqlite3.so"
            (root / "lib" / filename).write_bytes(b"synthetic native artifact, never executed")
            (root / "lib" / alias).symlink_to(filename)
            manifest = {"schema_version": 1, "sqlite_version": pins.VERSION,
                        "sqlite_source_id": pins.SOURCE_ID, "archive_sha256": pins.ARCHIVE_SHA256,
                        "sqlite3_c_sha3_256": pins.C_SHA3_256, "library_filename": filename,
                        "platform": platform.system(), "machine": platform.machine(),
                        "aliases": {alias: filename},
                        "library_sha256": hashlib.sha256((root / "lib" / filename).read_bytes()).hexdigest()}
            (root / "manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(ci.sqlite_runtime(root_project, root)[0], root / "lib")
            extra = root / "lib/unrelated-native-library"
            extra.write_bytes(b"unreviewed")
            with self.assertRaisesRegex(ValueError, "unreviewed artifact"):
                ci.sqlite_runtime(root_project, root)
            extra.unlink()
            (root / "lib" / filename).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "build receipt"):
                ci.sqlite_runtime(root_project, root)
            manifest["sqlite_source_id"] = "unreviewed"
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "platform/release"):
                ci.sqlite_runtime(root_project, root)


class SyntheticIdentityTests(unittest.TestCase):
    def test_identity_has_only_current_uid_and_private_sandbox_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            passwd, group = ci.synthetic_identity(Path(temporary))
            fields = passwd.read_text().strip().split(":")
            self.assertEqual((fields[2], fields[3]), (str(os.getuid()), str(os.getgid())))
            self.assertEqual(fields[5], "/home/quarry-ci")
            self.assertEqual(len(passwd.read_text().splitlines()), 1)
            self.assertEqual(group.read_text().strip(), f"quarry-ci:x:{os.getgid()}:")
