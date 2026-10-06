import io
import json
import unittest
import threading
from email.message import Message
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from termfinder import cli
from termfinder.web import Handler, ResearchServer, MAX_BODY


class FakeProject:
    path = "/tmp/test-project"
    recipe = {"mode": "broad"}
    profile = {"name": "fake"}

    def __init__(self):
        self.calls = []

    def status(self):
        return {"status": "ready", "counts": {"sources": 0}}

    def versions(self):
        return []

    def inventory(self):
        return {name: [] for name in ("terms", "occurrences", "sources", "runs", "jobs", "audit", "annotations", "relations", "discovery", "costs")}

    def estimate(self, **kwargs):
        self.calls.append(("estimate", kwargs))
        return {"total_usd": [0, 1]}

    def configure(self, *args):
        self.calls.append(("configure", args))
        return {"configured": True}

    def annotate(self, *args):
        self.calls.append(("annotate", args))
        return "a1"

    def resolve_uncertain(self, job_id, *, retry=False, acknowledge_possible_duplicate_billing=False):
        if retry and not acknowledge_possible_duplicate_billing:
            raise ValueError("Retry requires acknowledgement of possible duplicate billing")
        self.calls.append(("resolve_uncertain", job_id, retry, acknowledge_possible_duplicate_billing))


def handler(project=None, *, host="127.0.0.1:8765", origin="http://127.0.0.1:8765", token="session", path="/api/annotate", body=None):
    instance = Handler.__new__(Handler)
    instance.server = SimpleNamespace(project=project or FakeProject(), token="session", host="127.0.0.1:8765", origin="http://127.0.0.1:8765", worker=None, worker_error=None, worker_result=None, allow_paid=False)
    instance.path = path
    instance.headers = Message()
    instance.headers["Host"] = host
    instance.headers["Origin"] = origin
    instance.headers["X-Termfinder-Token"] = token
    data = json.dumps(body or {"term_id": "t1", "status": "approved"}).encode()
    instance.headers["Content-Type"] = "application/json"
    instance.headers["Content-Length"] = str(len(data))
    instance.rfile = io.BytesIO(data)
    instance.wfile = io.BytesIO()
    instance.responses = []
    instance._send = lambda code, data, content_type=None: instance.responses.append((code, data, content_type))
    return instance


class InterfaceTests(unittest.TestCase):
    def test_browser_request_bulkhead_and_socket_timeout(self):
        server=ResearchServer.__new__(ResearchServer)
        server.request_slots=threading.BoundedSemaphore(1)
        with patch.object(ThreadingHTTPServer,"process_request") as dispatch,patch.object(ResearchServer,"shutdown_request") as close:
            server.process_request(object(),("127.0.0.1",1))
            server.process_request(object(),("127.0.0.1",2))
            self.assertEqual(dispatch.call_count,1);self.assertEqual(close.call_count,1)
        with patch.object(ThreadingHTTPServer,"process_request_thread"):
            server.process_request_thread(object(),("127.0.0.1",1))
        self.assertTrue(server.request_slots.acquire(blocking=False))
        with patch.object(ThreadingHTTPServer,"get_request") as accept:
            from unittest.mock import Mock
            connection=Mock();accept.return_value=(connection,("127.0.0.1",1))
            server.get_request();connection.settimeout.assert_called_once_with(30)
    def test_loopback_host_token_and_origin_reject_cross_site_mutation(self):
        for options in ({"host": "evil.example:8765"}, {"origin": "https://evil.example"}, {"token": "wrong"}):
            request = handler(**options)
            request.do_POST()
            self.assertEqual(request.responses[0][0], 403)
            self.assertEqual(request.server.project.calls, [])
        request = handler()
        request.do_POST()
        self.assertEqual(request.responses[0][0], 200)
        self.assertEqual(request.server.project.calls[0][0], "annotate")

    def test_state_does_not_mutate_and_oversize_body_rejected(self):
        request = handler(path="/api/state")
        request.do_GET()
        self.assertEqual(request.responses[0][0], 200)
        self.assertTrue(request.responses[0][1]["offline"])
        request = handler()
        request.headers.replace_header("Content-Length", str(MAX_BODY+1))
        request.do_POST()
        self.assertEqual(request.responses[0][0], 400)
        self.assertEqual(request.server.project.calls, [])

    def test_recipe_setup_rejects_credentials_and_traversal_export(self):
        request = handler(path="/api/configure", body={"recipe": {}, "profile": "https://secret.example/key"})
        request.do_POST()
        self.assertEqual(request.responses[0][0], 400)
        request = handler(path="/api/configure", body={"recipe_text": '{"mode":"broad","mode":"specialists"}', "profile": "fake"})
        request.do_POST()
        self.assertEqual(request.responses[0][0], 400)
        request = handler(path="/api/export", body={"version": "../../outside"})
        request.do_POST()
        self.assertEqual(request.responses[0][0], 400)

    def test_cli_explicit_provider_authorization_and_workflow_parser(self):
        args = cli.parser().parse_args(["--project", "demo", "collect", "--offline", "--max-jobs", "1"])
        self.assertTrue(args.offline)
        self.assertFalse(args.allow_paid)
        args = cli.parser().parse_args(["serve", "--allow-paid"])
        self.assertTrue(args.allow_paid)
        for argv in (["init", "demo", "--recipe", "cultural", "--profile", "gemini", "--mode", "specialists"], ["ingest", "sample.pdf", "--url-list", "urls.txt"], ["export", "v1", "out", "--formats", "csv,jsonl"], ["evaluate", "v1", "gold.jsonl", "--unit", "source_term"]):
            self.assertIsNotNone(cli.parser().parse_args(argv).command)

    def test_uncertain_retry_requires_explicit_acknowledgement(self):
        request = handler(path="/api/resolve-uncertain", body={"job_id": "j1", "retry": True})
        request.do_POST()
        self.assertEqual(request.responses[0][0], 400)
        self.assertFalse(request.server.project.calls)
        request = handler(path="/api/resolve-uncertain", body={"job_id": "j1", "retry": True, "acknowledge_possible_duplicate_billing": True})
        request.do_POST()
        self.assertEqual(request.responses[0][0], 200)
        self.assertEqual(request.server.project.calls[0], ("resolve_uncertain", "j1", True, True))

    def test_cli_cost_assumptions_forwarded(self):
        project = FakeProject()
        with patch("termfinder.project.Project", return_value=project), patch("sys.stdout", new_callable=io.StringIO) as output:
            code = cli.main(["estimate", "--links", "300", "--average-chars", "8000", "--cache-hit-rate", "0.4"])
        self.assertEqual(code, 0)
        self.assertEqual(project.calls[0][1], {"links": 300, "average_chars": 8000, "cache_hit_rate": .4})
        self.assertIn("total_usd", output.getvalue())


if __name__ == "__main__":
    unittest.main()
