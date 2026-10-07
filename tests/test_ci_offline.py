"""Launcher diagnostics stay useful without exposing arbitrary startup output."""
import importlib.util
import json
from pathlib import Path
import unittest

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
                 "host_network_namespace_isolated": True}
        self.assertEqual(ci.isolation_result(0, json.dumps(probe), linux=True), (probe, None))

    def test_failed_assertion_and_nonzero_exit_remain_fail_closed(self):
        probe = {"unrelated_file_read_denied": True, "network_denied": False}
        self.assertEqual(ci.isolation_result(0, json.dumps(probe), linux=False)[1], "isolation_assertion_failed")
        probe["network_denied"] = True
        self.assertIsNotNone(ci.isolation_result(1, json.dumps(probe), linux=False)[1])

    def test_startup_categories_never_return_raw_diagnostics(self):
        cases = [(1, "bwrap: Creating new namespace failed: Operation not permitted", "namespace_setup_failed"),
                 (1, "bwrap: Can't bind mount /private/location: Permission denied", "filesystem_setup_failed"),
                 (1, "bwrap: execvp /private/runtime: No such file or directory", "interpreter_launch_failed"),
                 (124, "arbitrary secret-like output", "startup_timeout"),
                 (1, "arbitrary secret-like output", "unrecognized_startup_output")]
        for code, output, category in cases:
            with self.subTest(category=category):
                self.assertEqual(ci.isolation_result(code, output, linux=True), ({}, category))
