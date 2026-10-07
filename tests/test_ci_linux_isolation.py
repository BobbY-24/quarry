"""CI prerequisite safety: inert system doubles and real bounded file reads."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("quarry_ci_linux_isolation",
    Path(__file__).resolve().parents[1] / "tools" / "ci_linux_isolation.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def command_result(code=0, output="", *, timed_out=False, bounded=True):
    return {"exit_code": code, "output": output, "timed_out": timed_out,
            "output_bounded": bounded, "launch_failed": False}


class LinuxIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile"
        self.profile.write_bytes(b"approved fixture policy\n")
        self.fixture_hash = hashlib.sha256(b"approved fixture policy\n").hexdigest()
        self.patches = [patch.object(ci, "PROFILE_PATH", self.profile),
                        patch.object(ci, "PROFILE_SHA256", self.fixture_hash),
                        patch.object(ci, "LOCAL_INCLUDES", (self.root / "local-one", self.root / "local-two"))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_changed_distro_policy_is_rejected_before_privileged_effect(self):
        self.profile.write_bytes(b"changed fixture policy\n")
        def unexpected_command(*args, **kwargs):
            self.fail("A mismatched policy must not trigger any privileged command")
        with patch.object(ci, "_run_trusted", unexpected_command):
            self.assertEqual(ci.provision(), {"status": "blocked", "category": "reviewed_distro_profile_hash_mismatch"})

    def test_symlink_or_oversized_policy_fails_before_privileged_effect(self):
        original = self.root / "original"
        self.profile.rename(original)
        self.profile.symlink_to(original)
        def unexpected_command(*args, **kwargs):
            self.fail("An unsafe profile path must not trigger a privileged command")
        with patch.object(ci, "_run_trusted", unexpected_command):
            self.assertEqual(ci.provision()["category"], "reviewed_distro_profile_unavailable")
            self.profile.unlink()
            with self.profile.open("wb") as stream:
                stream.truncate(ci.READ_LIMIT + 1)
            self.assertEqual(ci.provision()["category"], "reviewed_distro_profile_unavailable")

    def test_custom_local_includes_are_not_silently_applied(self):
        (self.root / "local-one").write_text("fixture local override")
        with patch.object(ci, "_run_trusted", side_effect=AssertionError("must not invoke loader")):
            self.assertEqual(ci.provision()["category"], "unreviewed_local_profile_include")

    def test_existing_bwrap_policy_is_preserved_without_a_loader_call(self):
        commands = []
        def system(command, **kwargs):
            commands.append(command)
            if command[2] != "/usr/bin/cat":
                self.fail("Existing policy must not be loaded or replaced")
            return command_result(output="unrelated (enforce)\nvendor_bwrap (enforce)\n")
        with patch.object(ci, "_run_trusted", system):
            self.assertEqual(ci.provision()["category"], "existing_bwrap_policy_preserved")
        self.assertEqual(commands, [["/usr/bin/sudo", "-n", "/usr/bin/cat", str(ci.LOADED_PROFILES)]])

    def test_hash_bound_loader_uses_add_only_and_verifies_enforcement(self):
        commands = []
        inventories = iter(["unrelated (enforce)\n", "bwrap (enforce)\nunpriv_bwrap (enforce)\n"])
        def system(command, **kwargs):
            commands.append(command)
            return command_result(output=next(inventories)) if command[2] == "/usr/bin/cat" else command_result()
        with patch.object(ci, "_run_trusted", system):
            result = ci.provision()
        self.assertEqual(result["status"], "loaded")
        self.assertEqual(commands[1], ["/usr/bin/sudo", "-n", "/usr/sbin/apparmor_parser", "--add", str(self.profile)])
        self.assertEqual(result["policy_operation"], "add_only")
        self.assertEqual(result["profile_sha256"], self.fixture_hash)

    def test_parser_timeout_and_missing_or_complain_policy_stay_unresolved(self):
        for loader, inventory in ((command_result(-9, timed_out=True), ""),
                                  (command_result(), "bwrap (enforce)\n"),
                                  (command_result(), "bwrap (enforce)\nunpriv_bwrap (complain)\n")):
            with self.subTest(loader=loader, inventory=inventory):
                responses = iter([command_result(output="unrelated (enforce)\n"), loader,
                                  command_result(output=inventory)])
                with patch.object(ci, "_run_trusted", side_effect=lambda *a, **kw: next(responses)):
                    self.assertEqual(ci.provision()["status"], "uncertain")

    def test_add_failure_stays_blocked_and_does_not_echo_parser_output(self):
        responses = iter([command_result(output=""), command_result(1, "private-fixture-canary\n")])
        with patch.object(ci, "_run_trusted", side_effect=lambda *a, **kw: next(responses)):
            result = ci.provision()
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("private-fixture-canary", json.dumps(result))

    def test_preflight_keeps_network_and_capability_isolation_with_only_system_true(self):
        commands = []
        def system(command, **kwargs):
            commands.append(command)
            return command_result(1, "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\nprivate-fixture-canary")
        with patch.object(ci, "_run_trusted", system):
            result = ci.preflight()
        self.assertEqual(result["category"], "private_loopback_setup_failed")
        command = commands[0]
        self.assertEqual(command[:6], ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL"])
        self.assertEqual(command[-1], "/usr/bin/true")
        self.assertNotIn("--share-net", command)
        self.assertNotIn("private-fixture-canary", json.dumps(result))

    def test_kernel_categories_ignore_unrelated_events_and_never_export_raw_lines(self):
        output = ('apparmor="DENIED" operation="capable" comm="bwrap" capname="net_admin" private-fixture-canary\n'
                  'apparmor="DENIED" operation="capable" comm="other" capname="net_admin"\n'
                  'apparmor="DENIED" operation="userns_create" comm="bwrap" private-location\n')
        with patch.object(ci, "_run_trusted", return_value=command_result(output=output)):
            result = ci.kernel_diagnostic()
        self.assertEqual(result["categories"], {"bwrap_cap_net_admin_denied": 1, "bwrap_user_namespace_denied": 1})
        self.assertTrue(result["audit_available"])
        self.assertNotIn("private-fixture-canary", json.dumps(result))
        self.assertNotIn("private-location", json.dumps(result))
        with patch.object(ci, "_run_trusted", return_value=command_result(output=output, bounded=False)):
            self.assertFalse(ci.kernel_diagnostic()["audit_available"])

    def test_without_hosted_declaration_provision_does_not_start_any_system_command(self):
        report = Path(__file__).resolve().parents[1] / "verification/ci/test-hosted-gate.json"
        with patch.object(ci.sys, "platform", "linux"), patch.dict(ci.os.environ, {}, clear=True), \
                patch.object(ci, "_run_trusted", side_effect=AssertionError("no undeclared host effect")):
            self.assertEqual(ci.main(["provision", "--report", str(report)]), 2)
        self.assertEqual(json.loads(report.read_text())["status"], "hosted_runner_declaration_required")


if __name__ == "__main__":
    unittest.main()
