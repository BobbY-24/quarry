"""Private transport worker reports every failure as one fixed, offline contract."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXED_ERROR = {"error": "transport_worker_error", "uncertain": True, "retryable": False}


class TransportWorkerTests(unittest.TestCase):
    def run_worker(self, stdin):
        # Minimal environment: the worker must not depend on or leak the caller's environment.
        return subprocess.run([sys.executable, "-m", "termfinder.transport_worker"], input=stdin,
                              capture_output=True, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")})

    def test_non_json_request_returns_fixed_error_without_echoing_input(self):
        result = self.run_worker(b"not json secret-looking-value")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), FIXED_ERROR)
        self.assertNotIn(b"secret-looking-value", result.stdout)

    def test_request_missing_required_fields_returns_fixed_error(self):
        result = self.run_worker(json.dumps({"profile": {}}).encode())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), FIXED_ERROR)


if __name__ == "__main__":
    unittest.main()
