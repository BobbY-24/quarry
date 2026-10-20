"""Offline project-local connection tests; no host or model is launched."""
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from quarry import harness
from quarry.harness import HarnessError, connect_harness

ASSETS = {"SKILL.md": b"---\nname: v6-collect-research\n---\nFixture instructions.\n",
          "references/workflow.md": b"Approval and source evidence remain required.\n"}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "lab-workspace"
        self.workspace.mkdir()
        self.assets = patch.object(harness, "_assets", return_value=dict(ASSETS))
        self.assets.start()
        self.addCleanup(self.assets.stop)
        self.launcher = patch.object(harness, "_launcher", return_value=("/verified/venv/bin/python", ["-m", "quarry.mcp_server"]))
        self.launcher.start()
        self.addCleanup(self.launcher.stop)

    def inventory(self):
        return {p.relative_to(self.workspace).as_posix(): p.read_bytes()
                for p in self.workspace.rglob("*") if p.is_file()}

    def test_codex_once_then_idempotent_exactmatch(self):
        result = connect_harness("codex", self.workspace)
        self.assertTrue(result["changed"])
        self.assertEqual(result["studies"], str(self.workspace / "v6-studies"))
        self.assertEqual(result["skill_path"], str(self.workspace / ".agents/skills/v6-collect-research"))
        entry = tomllib.loads(Path(result["config_path"]).read_text())["mcp_servers"]["v6"]
        self.assertEqual(entry, {"command": result["command"], "args": result["args"]})
        self.assertEqual(result["args"], ["-m", "quarry.mcp_server", "--workspace", result["studies"]])
        self.assertFalse(result["allow_paid"])
        self.assertFalse(result["connection_verified"])
        self.assertFalse(result["client_started"])
        self.assertFalse(result["installed_globally"])
        before = self.inventory()
        second = connect_harness("codex", self.workspace)
        self.assertFalse(second["changed"])
        self.assertEqual(before, self.inventory())
        self.assertFalse((self.workspace / ".v6-connect.lock").exists())

    def test_codex_preserves_unrelated_bytes_and_settings(self):
        config = self.workspace / ".codex/config.toml"
        config.parent.mkdir()
        original = b'# my setting\nmodel = "configured-model"\n\n[mcp_servers.existing]\ncommand = "other"\nargs = ["--local"]\n'
        config.write_bytes(original)
        connect_harness("codex", self.workspace)
        self.assertTrue(config.read_bytes().startswith(original))
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed["model"], "configured-model")
        self.assertEqual(parsed["mcp_servers"]["existing"], {"command": "other", "args": ["--local"]})

    def test_claude_project_config_discovery_and_paid_explicit(self):
        config = self.workspace / ".mcp.json"
        original = {"mcpServers": {"other": {"type": "stdio", "command": "local-other"}}, "metadata": {"description": "retained"}}
        config.write_text(json.dumps(original))
        result = connect_harness("claude", self.workspace, allow_paid=True)
        parsed = json.loads(config.read_text())
        self.assertEqual(parsed["metadata"], original["metadata"])
        self.assertEqual(parsed["mcpServers"]["other"], original["mcpServers"]["other"])
        self.assertEqual(parsed["mcpServers"]["v6"]["type"], "stdio")
        self.assertEqual(parsed["mcpServers"]["v6"]["args"][-1], "--allow-paid")
        self.assertTrue(Path(result["skill_path"]).is_relative_to(self.workspace / ".claude/skills"))
        self.assertIn("/v6-collect-research", result["prompt"])
        before = config.read_bytes()
        self.assertFalse(connect_harness("claude", self.workspace, allow_paid=True)["changed"])
        self.assertEqual(config.read_bytes(), before)

    def test_generic_exports_without_guessing_host(self):
        sentinel = self.workspace / ".mcp.json"
        sentinel.write_text('{"untouched": true}')
        result = connect_harness("generic", self.workspace)
        self.assertEqual(result["status"], "exported")
        self.assertEqual(Path(result["skill_path"]), self.workspace / "v6-collect-research")
        self.assertEqual(Path(result["config_path"]), self.workspace / "v6-mcp.json")
        self.assertEqual(sentinel.read_text(), '{"untouched": true}')
        self.assertFalse((self.workspace / ".agents").exists())
        self.assertFalse((self.workspace / ".claude").exists())
        self.assertFalse((self.workspace / ".codex").exists())

    def test_conflicting_server_is_not_replaced_or_partially_installed(self):
        config = self.workspace / ".mcp.json"
        original = b'{"mcpServers":{"v6":{"command":"different"}},"other":"retained"}'
        config.write_bytes(original)
        with self.assertRaisesRegex(HarnessError, "existing v6 MCP entry differs"):
            connect_harness("claude", self.workspace)
        self.assertEqual(self.inventory(), {".mcp.json": original})
        self.assertFalse((self.workspace / "v6-studies").exists())

    def test_paid_gate_or_group_change_needs_explicit_migration(self):
        connect_harness("codex", self.workspace)
        before = self.inventory()
        with self.assertRaisesRegex(HarnessError, "entry differs"):
            connect_harness("codex", self.workspace, allow_paid=True)
        self.assertEqual(self.inventory(), before)
        with self.assertRaisesRegex(HarnessError, "entry differs"):
            connect_harness("codex", self.workspace, self.workspace / "different-studies")
        self.assertFalse((self.workspace / "different-studies").exists())

    def test_owned_skill_customization_and_extra_files_are_preserved(self):
        result = connect_harness("claude", self.workspace)
        extra = Path(result["skill_path"]) / "my-notes.md"
        extra.write_text("Researcher notes")
        before = self.inventory()
        with self.assertRaisesRegex(HarnessError, "skill differs"):
            connect_harness("claude", self.workspace)
        self.assertEqual(before, self.inventory())

    def test_inline_credentials_refused_without_echo_or_other_changes(self):
        secret_marker = "PRIVATE-FIXTURE-VALUE-not-a-real-secret"
        for host, relative, content in (
                ("claude", ".mcp.json", json.dumps({"mcpServers": {"other": {"env": {"OTHER_API_KEY": secret_marker}}}})),
                ("codex", ".codex/config.toml", '[mcp_servers.other]\ncommand="other"\napi_key="' + secret_marker + '"\n')):
            with self.subTest(host=host):
                workspace = self.base / host
                workspace.mkdir()
                config = workspace / relative
                config.parent.mkdir(exist_ok=True)
                config.write_text(content)
                with self.assertRaises(HarnessError) as error:
                    connect_harness(host, workspace)
                self.assertNotIn(secret_marker, str(error.exception))
                self.assertIn("inline credentials", str(error.exception))
                self.assertEqual(config.read_text(), content)
                self.assertFalse((workspace / "v6-studies").exists())

    def test_symlink_workspace_studies_config_and_skill_are_rejected(self):
        link = self.base / "workspace-link"
        link.symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(HarnessError):
            connect_harness("codex", link)
        studies = self.workspace / "v6-studies"
        outside = self.base / "outside"
        outside.mkdir()
        studies.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HarnessError):
            connect_harness("codex", self.workspace)
        studies.unlink()
        config = self.workspace / ".mcp.json"
        target = self.base / "other-config.json"
        target.write_text("{}")
        config.symlink_to(target)
        with self.assertRaises(HarnessError):
            connect_harness("claude", self.workspace)
        self.assertEqual(target.read_text(), "{}")
        config.unlink()
        (self.workspace / ".agents").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HarnessError):
            connect_harness("codex", self.workspace)
        self.assertEqual(list(outside.iterdir()), [])

    def test_home_broad_hidden_and_missing_workspaces_are_not_installed(self):
        for path in (Path("/"), Path.home(), self.base / ".hidden", self.base / "missing"):
            with self.subTest(path=path), self.assertRaises(HarnessError):
                connect_harness("codex", path)
        with self.assertRaises(HarnessError):
            connect_harness("codex", self.workspace, self.base / "new-external")
        with self.assertRaises(HarnessError):
            connect_harness("unknown", self.workspace)
        with self.assertRaises(HarnessError):
            connect_harness("codex", self.workspace, allow_paid="yes")

    def test_explicit_existing_separate_studies_root(self):
        group = self.base / "separate-studies"
        group.mkdir()
        result = connect_harness("claude", self.workspace, group)
        self.assertEqual(result["studies"], str(group))
        self.assertEqual(list(group.iterdir()), [])
        self.assertEqual(result["args"][-1], str(group))

    def test_malformed_and_duplicate_configs_refuse_before_writes(self):
        for host, relative, text in (("codex", ".codex/config.toml", "[broken"),
                                     ("claude", ".mcp.json", '{"mcpServers":{},"mcpServers":{}}'),
                                     ("claude", ".mcp.json", "[]")):
            with self.subTest(text=text):
                workspace = self.base / (host + str(len(text)))
                workspace.mkdir()
                config = workspace / relative
                config.parent.mkdir(exist_ok=True)
                config.write_text(text)
                with self.assertRaises(HarnessError):
                    connect_harness(host, workspace)
                self.assertEqual(config.read_text(), text)
                self.assertFalse((workspace / "v6-studies").exists())

    def test_transaction_rolls_back_owned_files_and_keeps_existing_config(self):
        config = self.workspace / ".mcp.json"
        original = b'{"mcpServers":{"other":{"command":"retained"}}}'
        config.write_bytes(original)
        real_write = harness._Transaction.write

        def fail_config(transaction, path, old, content):
            if path == config:
                raise OSError("inert injected failure")
            return real_write(transaction, path, old, content)

        with patch.object(harness._Transaction, "write", fail_config), self.assertRaisesRegex(HarnessError, "rolled back"):
            connect_harness("claude", self.workspace)
        self.assertEqual(self.inventory(), {".mcp.json": original})
        self.assertEqual(set(p.name for p in self.workspace.iterdir()), {".mcp.json"})

    def test_concurrent_config_change_is_not_replaced(self):
        config = self.workspace / ".mcp.json"
        config.write_text('{"mcpServers":{}}')
        new_content = b'{"mcpServers":{},"concurrent":"preserve-me"}'
        real_write = harness._Transaction.write

        def concurrent_write(transaction, path, old, content):
            if path == config:
                config.write_bytes(new_content)
            return real_write(transaction, path, old, content)

        with patch.object(harness._Transaction, "write", concurrent_write), self.assertRaisesRegex(HarnessError, "changed during setup"):
            connect_harness("claude", self.workspace)
        self.assertEqual(self.inventory(), {".mcp.json": new_content})
        self.assertFalse((self.workspace / "v6-studies").exists())

    def test_failure_after_atomic_config_replace_restores_original_bytes(self):
        config = self.workspace / ".mcp.json"
        original = b'{\n  "mcpServers": {}, "retained": "original formatting"\n}\n'
        config.write_bytes(original)
        real_write = harness._Transaction.write

        def fail_after_replace(transaction, path, old, content):
            real_write(transaction, path, old, content)
            if path == config:
                self.assertIn("v6", json.loads(config.read_text())["mcpServers"])
                raise OSError("inert post-replacement failure")

        with patch.object(harness._Transaction, "write", fail_after_replace), self.assertRaisesRegex(HarnessError, "rolled back"):
            connect_harness("claude", self.workspace)
        self.assertEqual(self.inventory(), {".mcp.json": original})
        self.assertEqual(set(p.name for p in self.workspace.iterdir()), {".mcp.json"})

    def test_lock_collision_is_bounded_and_does_not_modify_existing_lock(self):
        lock = self.workspace / ".v6-connect.lock"
        lock.write_text("fixture lock")
        with self.assertRaisesRegex(HarnessError, "setup lock"):
            connect_harness("codex", self.workspace)
        self.assertEqual(self.inventory(), {".v6-connect.lock": b"fixture lock"})

    def test_regular_file_and_size_bounds(self):
        config = self.workspace / ".mcp.json"
        config.mkdir()
        with self.assertRaises(HarnessError):
            connect_harness("claude", self.workspace)
        config.rmdir()
        with config.open("wb") as stream:
            stream.truncate(harness.MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(HarnessError, "size bound"):
            connect_harness("claude", self.workspace)
        self.assertFalse((self.workspace / "v6-studies").exists())

    def test_launcher_prefers_installed_console_script_and_preserves_venv_python(self):
        self.launcher.stop()
        runtime = self.base / "installed-venv/bin"
        runtime.mkdir(parents=True)
        python = runtime / "python"
        base_python = self.base / "base-python"
        base_python.write_text("inert interpreter fixture")
        python.symlink_to(base_python)
        with patch.object(harness.sys, "executable", str(python)):
            self.assertEqual(harness._launcher(), (str(python), ["-m", "quarry.mcp_server"]))
            script = runtime / "quarry-mcp"
            script.write_text("inert console script fixture")
            script.chmod(0o700)
            self.assertEqual(harness._launcher(), (str(script), []))

    def test_packaged_skill_is_available_with_expected_name(self):
        self.assets.stop()
        assets = harness._assets()
        self.assertIn("SKILL.md", assets)
        self.assertIn(b"name: v6-collect-research", assets["SKILL.md"])


if __name__ == "__main__":
    unittest.main()
