"""Offline regressions for request-scoped failures and reviewed child transport."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import termfinder.providers as providers
from termfinder.config import load_profile


class FailureClassificationTests(unittest.TestCase):
    def test_http_request_rejection_scope_does_not_imply_known_billing(self):
        profile = load_profile("glm-deepseek")
        request = {"expert": {"model": "glm"}, "prompt": "fixture only", "timeout_seconds": 1,
                   "max_output_tokens": 10}
        for status, scope in [(400, "request"), (422, "request"), (413, "request"),
                              (401, "provider"), (403, "provider"), (429, "provider")]:
            with self.subTest(status=status), patch.dict(os.environ, {"FIREWORKS_API_KEY": "fixture-only"}, clear=True), \
                 patch("termfinder.providers.build_opener") as opener:
                opener.return_value.open.side_effect = HTTPError("https://fixture.invalid", status, "", {}, None)
                with self.assertRaises(providers.ProviderError) as raised:
                    providers.HTTPProvider(profile, _direct=True).complete(request)
                self.assertEqual(getattr(raised.exception, "failure_scope", None), scope)
                self.assertTrue(raised.exception.uncertain)

    def test_scope_and_uncertainty_are_independent_dimensions(self):
        error = providers.ProviderError("http_400", uncertain=True)
        self.assertEqual(getattr(error, "failure_scope", None), "request")
        self.assertTrue(error.uncertain)

    def test_reviewed_rejection_contract_only_releases_declared_status(self):
        contract = providers.RejectionContract("fixture reviewed no-acceptance contract", frozenset({400}))
        request = {"expert": {"model": "glm"}, "prompt": "fixture only", "timeout_seconds": 1,
                   "max_output_tokens": 10}
        for status, uncertain in [(400, False), (401, True)]:
            with self.subTest(status=status), patch.dict(os.environ, {"FIREWORKS_API_KEY": "fixture-only"}, clear=True), \
                 patch("termfinder.providers.build_opener") as opener:
                opener.return_value.open.side_effect = HTTPError("https://fixture.invalid", status, "", {}, None)
                with self.assertRaises(providers.ProviderError) as raised:
                    providers.HTTPProvider("glm-deepseek", _direct=True, rejection_contract=contract).complete(request)
                self.assertEqual(raised.exception.uncertain, uncertain)

    def test_filtered_response_is_source_scoped_and_does_not_assert_free_execution(self):
        request = {"expert": {"model": "glm"}, "prompt": "fixture only", "timeout_seconds": 1,
                   "max_output_tokens": 10}
        envelope = {"choices": [{"finish_reason": "content_filter", "message": {"content": None}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 0}}
        with patch.dict(os.environ, {"FIREWORKS_API_KEY": "fixture-only"}, clear=True), \
             patch("termfinder.providers.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
            with self.assertRaises(providers.ProviderError) as raised:
                providers.HTTPProvider("glm-deepseek", _direct=True).complete(request)
            self.assertEqual(raised.exception.reason, "provider_content_blocked")
            self.assertEqual(raised.exception.failure_scope, "source")
            self.assertTrue(raised.exception.uncertain)

    def test_reported_model_identity_is_preserved_without_inventing_alias_equality(self):
        request = {"expert": {"model": "glm"}, "prompt": "fixture only", "timeout_seconds": 1,
                   "max_output_tokens": 10}
        envelope = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                    "model": "reported-fixture-revision", "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
        with patch.dict(os.environ, {"FIREWORKS_API_KEY": "fixture-only"}, clear=True), \
             patch("termfinder.providers.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
            self.assertEqual(providers.HTTPProvider("glm-deepseek", _direct=True).complete(request).model_version,
                             "reported-fixture-revision")


class ProcessBoundaryTests(unittest.TestCase):
    def provider(self, script, **kwargs):
        self.assertTrue(hasattr(providers, "ProcessProvider"), "Reviewed process provider is required")
        return providers.ProcessProvider([sys.executable, "-c", script], reviewed=True, **kwargs)

    def request(self, **changes):
        return dict({"job_id": "fixture-job", "attempt_number": 1, "timeout_seconds": 0.4,
                     "expert": {"model": "fixture"}, "prompt": "fixture text", "max_output_tokens": 10}, **changes)

    def test_never_returning_child_is_killed_with_finite_uncertain_outcome(self):
        provider = self.provider("import time; time.sleep(60)")
        started = time.monotonic()
        with self.assertRaises(providers.ProviderError) as raised:
            provider.complete(self.request())
        self.assertTrue(raised.exception.uncertain)
        self.assertLess(time.monotonic() - started, 3)

    def test_oversized_child_output_is_bounded_and_never_accepted(self):
        provider = self.provider("import os; os.write(1,b'x'*1000000)", max_response_bytes=1024)
        with self.assertRaises(providers.ProviderError) as raised:
            provider.complete(self.request(timeout_seconds=2))
        self.assertEqual(raised.exception.reason, "transport_response_size_limit")
        self.assertTrue(raised.exception.uncertain)

    def test_oversized_request_and_precancellation_never_start_adapter(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("termfinder.process_transport.subprocess.Popen") as spawn:
            with self.assertRaises(providers.ProviderError) as raised:
                self.provider("print('unreachable')", max_request_bytes=256).complete(self.request(prompt="x" * 1000))
            self.assertFalse(raised.exception.uncertain)
            self.assertEqual(raised.exception.failure_scope, "request")
            with self.assertRaises(providers.ProviderError) as raised:
                self.provider("print('unreachable')").complete(self.request(cancellation_event=cancelled))
            self.assertFalse(raised.exception.uncertain)
            spawn.assert_not_called()

    def test_running_adapter_can_be_cancelled_with_finite_uncertain_cleanup(self):
        cancelled = threading.Event()
        timer = threading.Timer(.15, cancelled.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(providers.ProviderError) as raised:
                self.provider("import time; time.sleep(60)").complete(self.request(timeout_seconds=10, cancellation_event=cancelled))
            self.assertTrue(raised.exception.uncertain)
            self.assertEqual(raised.exception.reason, "transport_cancelled_outcome_unknown")
            self.assertLess(time.monotonic() - started, 3)
        finally:
            timer.join()

    def test_child_crash_and_malformed_output_preserve_unknown_outcomes(self):
        for script in ["import os; os._exit(3)", "print('not JSON')"]:
            with self.subTest(script=script):
                with self.assertRaises(providers.ProviderError) as raised:
                    self.provider(script).complete(self.request(timeout_seconds=2))
                self.assertTrue(raised.exception.uncertain)

    def test_mixed_or_invalid_usage_envelopes_are_unknown_not_free_results(self):
        for value in [{"response": {"text": "{}", "input_tokens": True}},
                      {"response": {"text": "{}"}, "error": "fixture_error", "uncertain": False, "retryable": False},
                      {"response": {"text": "{}", "output_tokens": -1}}]:
            script = "print(" + repr(json.dumps(value)) + ")"
            with self.subTest(value=value), self.assertRaises(providers.ProviderError) as raised:
                self.provider(script).complete(self.request(timeout_seconds=2))
            self.assertTrue(raised.exception.uncertain)

    def test_runtime_environment_controls_cannot_be_passed_as_credentials(self):
        for name in ["PYTHONINSPECT", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "BASH_ENV"]:
            with self.subTest(name=name), patch.dict(os.environ, {name: "synthetic"}, clear=True), \
                 self.assertRaises(providers.ProviderError) as raised:
                self.provider("print('{}')", credential_env=(name,)).complete(self.request())
            self.assertFalse(raised.exception.uncertain)

    def test_reusable_adapter_cache_requires_pinned_revision(self):
        command = [sys.executable, "-c", "print('{}')"]
        first = providers.ProcessProvider(command, reviewed=True)
        second = providers.ProcessProvider(command, reviewed=True)
        self.assertNotEqual(first.cache_identity, second.cache_identity)
        self.assertEqual(first.cache_reuse_scope, "process_instance")
        pinned = providers.ProcessProvider(command, reviewed=True, adapter_version="fixture-v1")
        self.assertEqual(pinned.cache_identity,
                         providers.ProcessProvider(command, reviewed=True, adapter_version="fixture-v1").cache_identity)
        self.assertNotEqual(pinned.cache_identity,
                            providers.ProcessProvider(command, reviewed=True, adapter_version="fixture-v2").cache_identity)

    def test_reviewed_argv_rejects_obvious_credentials_before_any_child_starts(self):
        for arguments in [["--api-key", "synthetic-placeholder"], ["--password=synthetic-placeholder"],
                          ["https://name:password@fixture.invalid"], ["https://fixture.invalid?token=synthetic"],
                          ["Bearer synthetic-placeholder"], ["sk-" + "fixture" * 8]]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                providers.ProcessProvider([sys.executable, *arguments], reviewed=True)

    def test_unrelated_credentials_and_full_source_never_cross_process_boundary(self):
        script = """import json,os,sys
value=json.load(sys.stdin)
allowed=set(os.environ) & {'SELECTED_FIXTURE_KEY','UNRELATED_FIXTURE_KEY'}
assert allowed == {'SELECTED_FIXTURE_KEY'}
assert 'source' not in value['request']
print(json.dumps({'response':{'text':'{}','input_tokens':1,'output_tokens':1}}))
"""
        with patch.dict(os.environ, {"SELECTED_FIXTURE_KEY": "synthetic-placeholder", "UNRELATED_FIXTURE_KEY": "unrelated-placeholder"}, clear=True):
            response = self.provider(script, credential_env=("SELECTED_FIXTURE_KEY",)).complete(
                self.request(timeout_seconds=2, source={"text": "not allowed across transport"}))
        self.assertEqual(response.text, "{}")

    def test_model_routing_passes_only_that_services_required_credentials(self):
        script = """import json,os,sys
request=json.load(sys.stdin)['request']
actual=set(os.environ) & {'FIXTURE_A_KEY','FIXTURE_B_KEY'}
expected={'FIXTURE_A_KEY'} if request['expert']['model']=='a' else {'FIXTURE_B_KEY'}
assert actual == expected
print(json.dumps({'response':{'text':'{}'}}))
"""
        with patch.dict(os.environ, {"FIXTURE_A_KEY": "synthetic-a", "FIXTURE_B_KEY": "synthetic-b"}, clear=True):
            provider = self.provider(script, credential_env_by_model={"a": ["FIXTURE_A_KEY"], "b": ["FIXTURE_B_KEY"]})
            for alias in ("a", "b"):
                self.assertEqual(provider.complete(self.request(expert={"model": alias}, timeout_seconds=2)).text, "{}")

    def test_descendants_are_cleaned_even_after_successful_parent_output(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            script = """import json,subprocess,sys
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdout=subprocess.DEVNULL)
open(sys.argv[1],'w').write(str(child.pid))
print(json.dumps({'response':{'text':'{}'}}))
"""
            self.assertTrue(hasattr(providers, "ProcessProvider"), "Reviewed process provider is required")
            provider = providers.ProcessProvider([sys.executable, "-c", script, str(pidfile)], reviewed=True)
            try:
                self.assertEqual(provider.complete(self.request(timeout_seconds=2)).text, "{}")
                pid = int(pidfile.read_text())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.02)
                else:
                    self.fail("Transport descendant remained alive")
            finally:
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_owner_sigkill_is_detected_by_independent_watchdog(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child-pid"
            child_script = "import os,time,sys; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(60)"
            owner_script = """from termfinder.providers import ProcessProvider
import sys
provider=ProcessProvider([sys.executable,'-c',sys.argv[1],sys.argv[2]],reviewed=True)
provider.complete({'job_id':'owner-fixture','timeout_seconds':10,'expert':{},'prompt':'','max_output_tokens':1})
"""
            owner = subprocess.Popen([sys.executable, "-c", owner_script, child_script, str(pidfile)],
                                     env=providers._environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            try:
                deadline = time.monotonic() + 3
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(pidfile.exists(), "Reviewed adapter did not start")
                child_pid = int(pidfile.read_text())
                owner.kill()
                owner.wait(timeout=1)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.02)
                else:
                    self.fail("Owner death left its reviewed adapter alive")
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(timeout=1)
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
