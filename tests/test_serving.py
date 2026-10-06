"""No GPU/server/network: reviewed vLLM lifecycle exercised through fake processes."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from termfinder.compute import build_compute_profile
from termfinder.serving import VLLMServer, normalize_server, ServingError


class Process:
    def __init__(self):
        self.returncode = None
        self.terminated = self.killed = False
    def poll(self): return self.returncode
    def terminate(self): self.terminated = True; self.returncode = -15
    def kill(self): self.killed = True; self.returncode = -9
    def wait(self, timeout=None): return self.returncode


class ServingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model = Path(self.temp.name) / "model"
        self.model.mkdir()
        files = {"config.json": b'{"model_type":"fixture"}', "tokenizer.json": b"{}",
                 "model.safetensors": b"synthetic fixture; never load"}
        for name, data in files.items(): (self.model / name).write_bytes(data)
        self.server = {"adapter": "vllm", "model_alias": "researcher", "local_model_dir": str(self.model),
            "artifact_files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "port": 18880, "startup_timeout_seconds": 1, "max_model_len": 8192,
            "tensor_parallel_size": 1, "gpu_memory_utilization": 0.8, "package_version": "0.11.0"}
        self.extractor = build_compute_profile(backend="local", base_url="http://127.0.0.1:18880/v1",
            model="fixture-model", model_version="reviewed-checkpoint", context_limit_tokens=8192, max_output_tokens=512)
        self.profile = {"gpus": 1, "runtime": {"python_executable": "/reviewed/python"}, "server": self.server,
                        "scratch_env": "SLURM_TMPDIR"}

    def create(self, *, readiness=None, process=None):
        process = process or Process()
        captured = []
        def factory(argv, **settings): captured.append((argv, settings)); return process
        server = VLLMServer(self.profile, self.extractor, process_factory=factory,
                            readiness=readiness or (lambda _: True))
        return server, process, captured

    def version(self, version="0.11.0"):
        return patch("termfinder.serving.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=(version + "\n").encode()))

    def test_profile_rejects_unbounded_resources_scope_and_shell_extensions(self):
        changes = [{"adapter": "anything"}, {"port": 80}, {"tensor_parallel_size": 2},
                   {"startup_timeout_seconds": 0}, {"gpu_memory_utilization": float("nan")},
                   {"max_model_len": 4096}, {"package_version": "latest"}, {"shell": "anything"},
                   {"model_alias": "unknown"}, {"artifact_files": {"../config.json": "a" * 64}}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_server(dict(self.server, **change), self.extractor, self.profile)
        remote = deepcopy(self.extractor)
        remote["providers"]["researcher"]["base_url"] = "https://service.example/v1"
        with self.assertRaises(ValueError): normalize_server(self.server, remote, self.profile)

    def test_artifacts_are_complete_and_code_and_symlinks_are_rejected(self):
        (self.model / "custom.py").write_text("# synthetic unexecuted code")
        with self.assertRaises(ValueError): normalize_server(self.server, self.extractor, self.profile)
        (self.model / "custom.py").unlink()
        (self.model / "unexpected.txt").write_text("unreviewed fixture")
        with self.assertRaises(ValueError): normalize_server(self.server, self.extractor, self.profile)
        (self.model / "unexpected.txt").unlink()
        (self.model / "linked.json").symlink_to(self.model / "config.json")
        with self.assertRaises(ValueError): normalize_server(self.server, self.extractor, self.profile)

    def test_start_verifies_hashes_before_executing_and_masks_error_details(self):
        server, process, captured = self.create()
        (self.model / "config.json").write_text("changed fixture")
        with self.version(), self.assertRaises(ServingError) as failure: server.start()
        self.assertEqual(failure.exception.reason, "model_artifact_integrity_failed")
        self.assertNotIn(str(self.model), str(failure.exception))
        self.assertFalse(captured)

    def test_warm_start_clean_environment_fixed_arguments_and_bounded_cleanup(self):
        server, process, captured = self.create()
        with self.version(), patch.dict("os.environ", {"UNRELATED_TOKEN": "synthetic", "CUDA_VISIBLE_DEVICES": "0"}, clear=True):
            first = server.start()
            second = server.start()
        self.assertEqual(len(captured), 1)
        self.assertEqual(first, second)
        argv, settings = captured[0]
        self.assertEqual(argv[:3], ["/reviewed/python", "-m", "vllm.entrypoints.openai.api_server"])
        self.assertNotIn("--trust-remote-code", argv)
        self.assertNotIn("--disable-log-requests", argv)
        self.assertNotIn("--enable-log-requests", argv)
        self.assertEqual(argv[argv.index("--load-format") + 1], "safetensors")
        self.assertEqual(argv[argv.index("--distributed-executor-backend") + 1], "mp")
        self.assertEqual(argv[argv.index("--host") + 1], "127.0.0.1")
        self.assertNotIn("UNRELATED_TOKEN", settings["env"])
        self.assertEqual(settings["env"]["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(settings["env"]["HF_HUB_OFFLINE"], "1")
        self.assertEqual(settings["env"]["VLLM_PLUGINS"], "")
        self.assertEqual(settings["env"]["VLLM_LOGGING_LEVEL"], "WARNING")
        self.assertEqual(settings["env"]["VLLM_HOST_IP"], "127.0.0.1")
        for name in ("XDG_CONFIG_HOME", "VLLM_CONFIG_ROOT", "HF_HOME", "VLLM_CACHE_ROOT"):
            self.assertTrue(Path(settings["env"][name]).is_relative_to(settings["cwd"]))
        self.assertTrue(settings["start_new_session"])
        self.assertTrue(Path(settings["cwd"]).name.startswith("quarry-vllm-"))
        self.assertFalse(first["checkpoint_remote_attested"])
        self.assertEqual(first["plugin_autoload"], "disabled")
        self.assertEqual(first["load_format"], "safetensors")
        self.assertEqual(first["generation_config"], "vllm")
        server.close()
        server.close()
        self.assertTrue(process.terminated)

    def test_package_version_mismatch_never_launches_model(self):
        server, _, captured = self.create()
        with self.version("0.11.1"), self.assertRaises(ServingError) as failure: server.start()
        self.assertEqual(failure.exception.reason, "vllm_package_version_mismatch")
        self.assertFalse(captured)

    def test_cancel_during_startup_closes_owned_process(self):
        cancelled = [False]
        def ready(_): cancelled[0] = True; return False
        server, process, _ = self.create(readiness=ready)
        server.cancelled = lambda: cancelled[0]
        with self.version(), self.assertRaises(ServingError) as error: server.start()
        self.assertEqual(error.exception.reason, "model_server_startup_cancelled")
        self.assertTrue(process.terminated)

    def test_prestart_cancellation_never_launches_or_checks_package(self):
        server, _, captured = self.create()
        server.cancelled = lambda: True
        with patch("termfinder.serving.subprocess.run") as probe, self.assertRaises(ServingError) as error:
            server.start()
        self.assertEqual(error.exception.reason, "model_server_startup_cancelled")
        self.assertFalse(probe.called)
        self.assertFalse(captured)

    def test_health_checks_served_identity_with_no_proxy_or_redirect(self):
        server, _, _ = self.create()
        for model, expected in (("fixture-model", True), ("other-model", False)):
            with patch("termfinder.serving.build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.read1.side_effect = [("{\"data\":[{\"id\":\"" + model + "\"}]}").encode(), b""]
                self.assertEqual(server._ready("http://127.0.0.1:18880/v1/models"), expected)
                self.assertEqual(opener.call_args.args[0].proxies, {})

    def test_stubborn_owned_process_is_killed_after_bounded_terminate_wait(self):
        class Stubborn(Process):
            def terminate(inner): inner.terminated = True
            def wait(inner, timeout=None):
                if not inner.killed: raise subprocess.TimeoutExpired("fixture", timeout)
                return inner.returncode
        process = Stubborn()
        server, _, _ = self.create(process=process)
        with self.version(): server.start()
        server.close()
        self.assertTrue(process.killed)

    def test_exited_frontend_still_cleans_its_owned_gpu_process_group(self):
        import signal
        server, _, _ = self.create()
        process = Process(); process.returncode = 1; process.pid = 12345
        server.factory = None
        server.process = process
        with patch("termfinder.serving.os.killpg") as groups:
            server.close()
            server.close()
        self.assertEqual(groups.call_count, 2)
        self.assertEqual(groups.call_args_list[0].args, (12345, signal.SIGTERM))
        self.assertEqual(groups.call_args_list[-1].args, (12345, signal.SIGKILL))

    def test_readiness_timeout_and_early_exit_cleanup_are_safe(self):
        server, process, _ = self.create(readiness=lambda _: False)
        with self.version(), self.assertRaises(ServingError) as failure: server.start()
        self.assertEqual(failure.exception.reason, "model_server_startup_timeout")
        self.assertTrue(process.terminated)
        early = Process(); early.returncode = 1
        server, _, _ = self.create(process=early)
        with self.version(), self.assertRaises(ServingError) as failure: server.start()
        self.assertEqual(failure.exception.reason, "model_server_exited_before_ready")

    def test_readiness_errors_and_invalid_cuda_environment_are_sanitized(self):
        def failure(_): raise RuntimeError("synthetic credential-like private detail")
        server, process, _ = self.create(readiness=failure)
        with self.version(), self.assertRaises(ServingError) as error: server.start()
        self.assertNotIn("private detail", str(error.exception))
        self.assertTrue(process.terminated)
        server, _, captured = self.create()
        with self.version(), patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "0;run-untrusted"}, clear=True), self.assertRaises(ServingError): server.start()
        self.assertFalse(captured)


if __name__ == "__main__": unittest.main()
