"""A cancellation delivered after a start receipt must survive worker startup."""
import threading
import unittest
from unittest.mock import patch

import test_mcp_server as fixtures
from termfinder import FakeProvider
from termfinder import workflow
from termfinder.web import ResearchServer


class CancelStartupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MCPTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.review = self.fixture.approved()
        self.project = self.fixture.project

    def browser(self):
        server = ResearchServer.__new__(ResearchServer)
        server.project = self.project
        server.allow_paid, server.worker, server.worker_lock = False, None, threading.Lock()
        return server

    def check_cancel(self, controller, launch, worker_name):
        entered, release = threading.Event(), threading.Event()
        actual = workflow.run_review
        provider = FakeProvider()
        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Synthetic worker gate timed out")
            kwargs["provider"] = provider
            return actual(*args, **kwargs)
        self.project.cancel()  # A preceding run's cancellation must still clear on launch.
        with patch("termfinder.workflow.run_review", side_effect=delayed):
            reply = launch()
            self.assertTrue(reply["started"])
            self.assertTrue(entered.wait(2))
            stale_cancel_cleared = not self.project.store.read_setting("cancel_requested")
            self.project.cancel()  # Exactly one cancellation after the start reply.
            release.set()
            getattr(controller, worker_name).join(5)
        self.assertFalse(getattr(controller, worker_name).is_alive())
        self.assertIsNone(controller.worker_error)
        self.assertEqual(provider.calls, [])
        self.assertTrue(stale_cancel_cleared)
        self.assertTrue(self.project.store.read_setting("cancel_requested"))
        self.assertEqual(controller.worker_result["stop_reason"], "cancelled_by_researcher")

    def test_mcp_cancel_before_reviewed_worker_entry_is_not_lost(self):
        server = self.fixture.server
        self.check_cancel(server, lambda: server.call_tool("collect", {"review_id": self.review["review_id"]}), "worker")

    def test_browser_cancel_before_reviewed_worker_entry_is_not_lost(self):
        server = self.browser()
        self.check_cancel(server, lambda: server.start_collection(review_id=self.review["review_id"]), "worker")

    def test_browser_cancel_before_advanced_worker_entry_is_not_lost(self):
        server = self.browser()
        entered, release = threading.Event(), threading.Event()
        actual = self.project.collect
        provider = FakeProvider()
        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Synthetic worker gate timed out")
            if args:
                args = (provider, *args[1:])
            else:
                kwargs["provider"] = provider
            return actual(*args, **kwargs)
        self.project.cancel()
        with patch.object(self.project, "collect", side_effect=delayed):
            self.assertTrue(server.start_collection()["started"])
            self.assertTrue(entered.wait(2))
            stale_cancel_cleared = not self.project.store.read_setting("cancel_requested")
            self.project.cancel()
            release.set()
            server.worker.join(5)
        self.assertFalse(server.worker.is_alive())
        self.assertIsNone(server.worker_error)
        self.assertEqual(provider.calls, [])
        self.assertTrue(stale_cancel_cleared)
        self.assertTrue(self.project.store.read_setting("cancel_requested"))


if __name__ == "__main__":
    unittest.main()
