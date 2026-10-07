"""Pre-engine background admission failures remain visible after reconnect."""
import threading
import unittest
from unittest.mock import patch

import test_mcp_server as fixtures
from termfinder import Project
from termfinder.web import ResearchServer


class ControllerFailureRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MCPTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.review = self.fixture.approved()

    def controller(self, kind):
        if kind == "mcp":
            return self.fixture.server
        server = ResearchServer.__new__(ResearchServer)
        server.project = self.project
        server.allow_paid, server.worker, server.worker_lock = False, None, threading.Lock()
        return server

    def check_failure(self, kind):
        controller = self.controller(kind)
        def launch():
            return controller._start(self.review["review_id"]) if kind == "mcp" else controller.start_collection(review_id=self.review["review_id"])
        marker = "Synthetic private admission exception body"
        with patch("termfinder.workflow.run_review", side_effect=ValueError(marker)):
            self.assertTrue(launch()["started"])
            controller.worker.join(3)
        self.assertFalse(controller.worker.is_alive())
        self.assertIsNotNone(controller.worker_error)
        reopened = Project(self.project.path)
        self.assertEqual(reopened.store.count("runs"), 0)
        self.assertEqual(reopened.store.count("jobs"), 0)
        status = reopened.status()
        self.assertEqual(status["status"], "partial")
        incident_id = reopened.store.read_setting("controller_failure_id")
        self.assertTrue(incident_id)
        saved = reopened.store.get("incidents", incident_id)
        self.assertIsNotNone(saved)
        self.assertNotIn(marker, str(saved))
        # A later trusted launch clears the active marker, retaining history.
        entered, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Synthetic admission gate deadline")
            return {"status": "synthetic-complete"}
        with patch("termfinder.workflow.run_review", side_effect=blocked):
            self.assertTrue(launch()["started"])
            self.assertTrue(entered.wait(2))
            self.assertIsNone(self.project.store.read_setting("controller_failure_id"))
            release.set()
            controller.worker.join(3)
        self.assertIsNotNone(Project(self.project.path).store.get("incidents", incident_id))

    def test_mcp_pre_engine_failure_survives_reopen(self):
        self.check_failure("mcp")

    def test_browser_pre_engine_failure_survives_reopen(self):
        self.check_failure("browser")


if __name__ == "__main__":
    unittest.main()
