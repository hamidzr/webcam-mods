from pathlib import Path
import tempfile
import threading
import unittest
import sqlite3
from unittest.mock import patch

from webcam_mods.control import Controller
from webcam_mods.frame_producer import WorkerShutdownTimeout
from webcam_mods.profiles import Profile, ProfileStore


class ControllerStatusTests(unittest.TestCase):
    def test_profile_diagnostics_leave_valid_profiles_available(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "p.db")
            store.save("Valid", {"brightness": 10})
            with sqlite3.connect(store.path) as database:
                database.execute(
                    "INSERT INTO profiles VALUES (?, ?)",
                    ("Broken", "private-corrupt-data"),
                )
            controller = Controller(store, lambda event: None)
            self.assertEqual(
                [row["name"] for row in controller.dispatch("profiles.list", {})],
                ["Valid"],
            )
            diagnostics = controller.dispatch("profiles.errors", {})
            self.assertEqual(diagnostics[0]["name"], "Broken")
            self.assertNotIn("private-corrupt-data", diagnostics[0]["error"])

    def test_late_completion_does_not_hide_shutdown_timeout(self):
        started, release = threading.Event(), threading.Event()
        events = []

        def runner(profile, stop, ready, source_ready):
            ready()
            started.set()
            release.wait(2)

        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(
                ProfileStore(Path(directory) / "p.db"), events.append, runner
            )
            controller.start(Profile())
            try:
                self.assertTrue(started.wait(1))
                with patch("webcam_mods.control._STOP_TIMEOUT", 0.01):
                    failed = controller.stop()
                self.assertEqual(failed["state"], "error")
                self.assertTrue(failed["restart_required"])
                release.set()
                controller.thread.join(1)
                self.assertEqual(controller.status(), failed)
                self.assertEqual(events[-1]["data"], failed)
                with self.assertRaisesRegex(RuntimeError, "restart"):
                    controller.start(Profile())
            finally:
                release.set()
                controller.thread.join(1)

    def test_processing_timeout_is_terminal_and_actionable(self):
        def runner(*args):
            raise WorkerShutdownTimeout("processing is still active")

        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(
                ProfileStore(Path(directory) / "p.db"), lambda event: None, runner
            )
            controller.start(Profile())
            controller.thread.join(1)
            status = controller.status()
            self.assertEqual(status["state"], "error")
            self.assertTrue(status["restart_required"])
            self.assertIn("quit and reopen", status["error"])
            self.assertEqual(controller.stop(), status)
