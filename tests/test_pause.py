"""User pause: capture closes, output shows the loading picture, resume is live."""

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from test_frame_repetition import Sink, Source

from webcam_mods.control import Controller
from webcam_mods.loopback import live_loop
from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.settings import StartupSettings


class LiveLoopPauseTests(unittest.TestCase):
    def test_pause_closes_capture_and_resume_returns_live_frames(self) -> None:
        source = Source()
        paused = threading.Event()
        paused.set()
        held: list[np.ndarray] = []

        def delivered(frame: np.ndarray) -> None:
            if paused.is_set():
                held.append(frame.copy())
                if len(held) == 5:
                    paused.clear()
            elif np.all(frame >= 1):
                sink.stop = True
            if len(sink.frames) >= 200:
                raise AssertionError("live frame never arrived after resume")

        sink = Sink(delivered)
        live_loop(
            fIn=source,
            fOut=sink,
            interactive_listener=None,
            settings=StartupSettings(repeat_frames=True, processing_fps=30),
            should_pause=paused.is_set,
        )
        # the paused picture is the loading pattern, never a camera frame
        self.assertGreater(int(np.ptp(held[0])), 0)
        self.assertGreater(source.calls, 0)
        self.assertFalse(source.active)


class ControllerPauseTests(unittest.TestCase):
    def test_pause_needs_running_session_and_reaches_runner(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        events: list[dict] = []
        started = threading.Event()
        checks: list = []

        def runner(profile, stop, ready, source_ready, **callbacks):
            checks.append(callbacks["should_pause"])
            ready()
            started.set()
            stop.wait(5)

        with patch("webcam_mods.control.run_profile", runner):
            controller = Controller(
                ProfileStore(Path(directory.name) / "profiles.db"), events.append
            )
        self.addCleanup(controller.stop)
        dispatch = controller.dispatch
        with self.assertRaisesRegex(RuntimeError, "not running"):
            dispatch("session.pause", {"paused": True})
        controller.start(Profile(), "preview")
        self.assertTrue(started.wait(1))
        for params in ({}, {"paused": 1}, {"paused": True, "x": 0}):
            with self.subTest(params=params):
                with self.assertRaisesRegex(ValueError, "paused true or false"):
                    dispatch("session.pause", params)
        self.assertFalse(checks[0]())
        events.clear()
        self.assertTrue(dispatch("session.pause", {"paused": True})["paused"])
        self.assertTrue(checks[0]())
        self.assertEqual(events[-1]["data"]["paused"], True)
        # repeating the same request does not emit another status
        dispatch("session.pause", {"paused": True})
        self.assertEqual(len(events), 1)
        self.assertNotIn("paused", dispatch("session.pause", {"paused": False}))
        self.assertFalse(checks[0]())
        controller.stop()
        self.assertNotIn("paused", controller.status())


class BoundedPauseTests(unittest.TestCase):
    def test_bounded_pause_sends_loading_picture_without_capture(self) -> None:
        source, sink = Source(), Sink()
        live_loop(
            fIn=source,
            fOut=sink,
            interactive_listener=None,
            max_frames=3,
            pace=False,
            should_pause=lambda: True,
        )
        self.assertEqual(len(sink.frames), 3)
        self.assertEqual(source.calls, 0)
        self.assertFalse(source.active)


if __name__ == "__main__":
    unittest.main()
