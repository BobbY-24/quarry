"""Stable offline response and fault tapes do not depend on completion order."""
import importlib
from concurrent.futures import ThreadPoolExecutor
import unittest

from termfinder.providers import FakeProvider, ProviderError, Response


class FaultTapeTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("termfinder.fault_provider")
        except ImportError:
            self.fail("Stable keyed offline fault providers are required")

    def request(self, job, attempt=1):
        return {"job_id": job, "attempt_number": attempt, "expert": {"id": "broad"},
                "recipe": {"id": "fixture"}, "text": "", "prompt": ""}

    def test_response_assignment_is_stable_under_reversed_concurrent_order(self):
        provider = self.module().KeyedFakeProvider({("a", 1): Response("A"), ("b", 1): Response("B")})
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(provider.complete, [self.request("b"), self.request("a")]))
        self.assertEqual([v.text for v in result], ["B", "A"])
        self.assertEqual(provider.complete(self.request("a")).text, "A")

    def test_scripted_responses_and_attempts_are_part_of_tape_identity(self):
        cls = self.module().KeyedFakeProvider
        first = cls({("a", 1): Response("A")})
        self.assertEqual(first.cache_identity, cls({("a", 1): Response("A")}).cache_identity)
        self.assertNotEqual(first.cache_identity, cls({("a", 1): Response("B")}).cache_identity)
        self.assertNotEqual(first.cache_identity, cls({("a", 2): Response("A")}).cache_identity)
        with self.assertRaises(ProviderError) as raised:
            first.complete(self.request("a", 2))
        self.assertFalse(raised.exception.uncertain)

    def test_runtime_faults_preserve_underlying_cache_unless_requested(self):
        module = self.module()
        base = FakeProvider([])
        tape = {("a", 1): ProviderError("fixture_timeout", uncertain=True, failure_scope="request")}
        fault = module.FaultTapeProvider(base, tape)
        self.assertEqual(fault.cache_identity, base.cache_identity)
        with self.assertRaises(ProviderError) as raised:
            fault.complete(self.request("a"))
        self.assertEqual(raised.exception.failure_scope, "request")
        self.assertEqual(fault.complete(self.request("a", 2)).finish_reason, "stop")
        self.assertNotEqual(module.FaultTapeProvider(base, tape, cache_faults=True).cache_identity, base.cache_identity)

    def test_tape_types_and_delay_bounds_are_validated_before_calls(self):
        module = self.module()
        for key in [("a", True), ("a", 0), ("", 1)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.KeyedFakeProvider({key: Response("A")})
        with self.assertRaises(ValueError):
            module.FaultAction(delay_seconds=float("nan"))
        with self.assertRaises(ValueError):
            module.FaultAction(delay_seconds=31)

    def test_request_key_breaks_job_cache_identity_cycle(self):
        module = self.module()
        request = self.request("old-job-id")
        key = module.request_fingerprint(request)
        provider = module.KeyedFakeProvider({(key, 1): Response("A")}, key_scheme="request")
        request["job_id"] = "new-job-derived-from-response-tape-hash"
        self.assertEqual(module.request_fingerprint(request), key)
        self.assertEqual(provider.complete(request).text, "A")
        request["prompt"] = "changed prompt"
        self.assertNotEqual(module.request_fingerprint(request), key)


if __name__ == "__main__":
    unittest.main()
