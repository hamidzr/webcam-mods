"""Snapshots and the app's record/replay loop."""

from datetime import datetime
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.control import Controller
from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.record_replay import Recorder, save_snapshot
from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.settings import StartupSettings


def picture(value: int, width: int = 64, height: int = 48) -> np.ndarray:
    return np.full((height, width, 3), value, np.uint8)


class RecorderTests(unittest.TestCase):
    def test_compressed_recording_replays_close_to_the_original(self) -> None:
        times = iter([10.0, 10.5, 11.25])
        recorder = Recorder(compress=True, clock=lambda: next(times))
        self.assertEqual((recorder.state, recorder.seconds), ("idle", 0))
        recorder.command("record")
        noise = np.random.default_rng(1).integers(0, 255, (48, 64, 3), np.uint8)
        frames = [picture(40), picture(120), cv2.GaussianBlur(noise, (9, 9), 0)]
        for frame in frames:
            self.assertIs(recorder.engage(frame), frame)
        self.assertEqual((recorder.state, recorder.seconds), ("recording", 1.25))
        self.assertLess(recorder.size_bytes, sum(frame.nbytes for frame in frames))
        self.assertTrue(recorder.command("replay"))
        self.assertEqual(recorder.state, "replaying")
        replayed = [recorder.engage(picture(0)) for _ in range(4)]
        for frame, original in zip(replayed, frames + frames[:1]):
            self.assertEqual(frame.shape, original.shape)
            self.assertLess(np.abs(frame.astype(int) - original).mean(), 5)
        recorder.command("stop")
        self.assertEqual((recorder.state, recorder.seconds), ("idle", 1.25))
        # a new recording starts the clock again
        recorder.command("record")
        self.assertEqual(recorder.seconds, 0)

    def test_the_limit_ends_a_recording(self) -> None:
        recorder = Recorder(max_bytes=5000, compress=True)
        recorder.command("record")
        noise = np.random.default_rng(2)
        for _ in range(20):
            recorder.engage(noise.integers(0, 255, (48, 64, 3), np.uint8))
        self.assertEqual(recorder.state, "idle")
        self.assertLessEqual(recorder.size_bytes, 5000)
        self.assertGreater(len(recorder.frames), 0)


class SnapshotFileTests(unittest.TestCase):
    def test_snapshots_are_lossless_and_never_replace_files(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name) / "Webcam Mods"
        frame = np.random.default_rng(3).integers(0, 255, (48, 64, 3), np.uint8)
        now = datetime(2026, 10, 15, 14, 3, 22)
        first = save_snapshot(frame, folder, now)
        second = save_snapshot(picture(9), folder, now)
        self.assertEqual(first.name, "Webcam Mods 2026-10-15 at 14.03.22.png")
        self.assertEqual(second.name, "Webcam Mods 2026-10-15 at 14.03.22 (2).png")
        np.testing.assert_array_equal(cv2.imread(str(first)), frame)
        np.testing.assert_array_equal(cv2.imread(str(second)), picture(9))


class EffectRecordingTests(unittest.TestCase):
    def test_replay_loops_finished_frames_instead_of_the_camera(self) -> None:
        effect = ProfileEffect(
            Profile(brightness=40), StartupSettings(out_width=64, out_height=48)
        )
        self.addCleanup(effect.close)
        with self.assertRaisesRegex(ValueError, "nothing recorded"):
            effect.record("replay")
        with self.assertRaisesRegex(ValueError, "record, stop or replay"):
            effect.record("pause")
        self.assertEqual(
            effect.record("record"), {"recorder": "recording", "recorded_seconds": 0}
        )
        recorded = [effect(picture(value)) for value in (50, 100)]
        self.assertEqual(effect.record("replay")["recorder"], "replaying")
        with patch.object(effect, "_process", wraps=effect._process) as process:
            replayed = [effect(picture(200)) for _ in range(3)]
        process.assert_not_called()
        for frame, original in zip(replayed, recorded + recorded[:1]):
            assert frame is not None and original is not None
            # brightness was applied once, when recording
            self.assertLess(np.abs(frame.astype(int) - original).max(), 3)
        effect.record("stop")
        live = effect(picture(200))
        assert live is not None
        self.assertEqual(int(live[0, 0, 0]), 240)
        effect.close()
        self.assertEqual(effect.recorder.frames, [])


class ControllerSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name) / "Pictures"
        self.started = threading.Event()
        self.frame = np.random.default_rng(4).integers(0, 255, (48, 64, 3), np.uint8)

        def runner(profile, stop, ready, source_ready, **callbacks):
            effect = ProfileEffect(
                profile, StartupSettings(out_width=64, out_height=48)
            )
            callbacks["on_effect"](effect)
            ready()
            callbacks["on_frame"](self.frame)
            self.started.set()
            stop.wait(5)
            effect.close()

        with patch("webcam_mods.control.run_profile", runner):
            self.controller = Controller(
                ProfileStore(Path(directory.name) / "profiles.db"), lambda _: None
            )
        self.addCleanup(self.controller.stop)

    def test_snapshot_saves_what_calls_received(self) -> None:
        dispatch = self.controller.dispatch
        for method in ("session.snapshot", "session.record"):
            with self.subTest(method=method):
                params = {"action": "record"} if method == "session.record" else {}
                with self.assertRaisesRegex(RuntimeError, "not running|no video"):
                    dispatch(method, params)
        self.controller.start(Profile(), "preview")
        self.assertTrue(self.started.wait(1))
        with self.assertRaisesRegex(ValueError, "params must be empty"):
            dispatch("session.snapshot", {"path": "/tmp/x.png"})
        with patch("webcam_mods.control.SNAPSHOT_DIR", self.folder):
            path = Path(dispatch("session.snapshot", {})["path"])
        self.assertEqual(path.parent, self.folder)
        np.testing.assert_array_equal(cv2.imread(str(path)), self.frame)
        dispatch("session.pause", {"paused": True})
        with self.assertRaisesRegex(RuntimeError, "paused"):
            dispatch("session.snapshot", {})
        dispatch("session.pause", {"paused": False})

    def test_record_commands_reach_the_effect_and_show_in_stats(self) -> None:
        dispatch = self.controller.dispatch
        self.controller.start(Profile(), "preview")
        self.assertTrue(self.started.wait(1))
        for params in ({}, {"action": "pause"}, {"action": "record", "x": 1}):
            with self.subTest(params=params):
                with self.assertRaisesRegex(ValueError, "record, stop or replay"):
                    dispatch("session.record", params)
        with self.assertRaisesRegex(ValueError, "nothing recorded"):
            dispatch("session.record", {"action": "replay"})
        self.assertEqual(
            dispatch("session.record", {"action": "record"})["recorder"], "recording"
        )
        stats = dispatch("session.stats", {})
        self.assertEqual(
            (stats["recorder"], stats["recorded_seconds"]), ("recording", 0)
        )
        self.assertEqual(
            dispatch("session.record", {"action": "stop"})["recorder"], "idle"
        )


if __name__ == "__main__":
    unittest.main()
