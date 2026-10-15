"""Preview views, guides and live session stats."""

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.control import Controller
from webcam_mods.effects import ProfileEffect
from webcam_mods.geometry import Rect
from webcam_mods.output.native_preview import NativePreview
from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.settings import StartupSettings
from webcam_mods.stats import RateMeter


class Sink:
    def __init__(self, view: str) -> None:
        self.view = view
        self.published: list[tuple[np.ndarray, str, object]] = []

    def wants(self, view: str) -> bool:
        return view == self.view

    def publish(self, frame, view="output", guides=None) -> None:
        self.published.append((frame.copy(), view, guides))


class NativePreviewViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.preview = NativePreview(lambda: self.now)
        self.frame = np.full((48, 64, 3), 50, np.uint8)

    def test_only_requested_view_is_encoded_with_guides(self) -> None:
        self.assertFalse(self.preview.wants("source"))
        self.assertIsNone(self.preview.get("source"))
        self.assertTrue(self.preview.wants("source"))
        self.assertFalse(self.preview.wants("output"))
        self.preview.publish(self.frame)
        self.assertIsNone(self.preview.get("source"))
        guides = {"face": [0.1, 0.2, 0.3, 0.4]}
        self.preview.publish(self.frame, "source", guides)
        result = self.preview.get("source")
        assert result is not None
        self.assertEqual((result["view"], result["guides"]), ("source", guides))

    def test_switching_view_drops_previous_frame(self) -> None:
        self.preview.get()
        self.preview.publish(self.frame)
        output = self.preview.get()
        assert output is not None
        self.assertEqual(output["view"], "output")
        self.assertNotIn("guides", output)
        self.assertIsNone(self.preview.get("mask"))
        self.assertIsNone(self.preview.get("mask"))
        self.now = 1.5
        self.assertFalse(self.preview.wants("mask"))

    def test_invalid_view_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "view must be one of"):
            self.preview.get("depth")


class ProfileEffectPreviewTests(unittest.TestCase):
    frame = np.zeros((48, 64, 3), np.uint8)

    def setUp(self) -> None:
        self.frame = self.frame.copy()
        self.frame[:, :32] = 200

    def effect(self, profile: Profile, sink: Sink) -> ProfileEffect:
        effect = ProfileEffect(
            profile, StartupSettings(out_width=64, out_height=48), preview=sink
        )
        self.addCleanup(effect.close)
        return effect

    def test_source_view_is_oriented_camera_with_tracking_guides(self) -> None:
        sink = Sink("source")
        with patch("webcam_mods.effects.TrackingEffect") as tracking:
            tracker = tracking.return_value
            tracker.side_effect = lambda frame, region: frame[12:36, 16:48]
            tracker.face = Rect(w=16, h=12, t=12, l=24)
            tracker.crop = Rect(w=32, h=24, t=12, l=16)
            output = self.effect(Profile(track=True, mirror=True), sink)(self.frame)
        assert output is not None
        self.assertEqual(output.shape, (24, 32, 3))
        [(source, view, guides)] = sink.published
        self.assertEqual(view, "source")
        np.testing.assert_array_equal(source, self.frame[:, ::-1])
        self.assertEqual(
            guides,
            {"face": [0.375, 0.25, 0.25, 0.25], "framing": [0.25, 0.25, 0.5, 0.5]},
        )

    def test_mask_view_follows_segmentation_and_output_view_is_left_to_loop(
        self,
    ) -> None:
        sink = Sink("mask")
        with patch("webcam_mods.entry.BackgroundEffect") as background:
            background.return_value.side_effect = lambda frame: frame
            background.return_value.mask = np.full((48, 64), 0.5, np.float32)
            effect = self.effect(Profile(effect="blur"), sink)
            effect(self.frame)
        [(mask, view, guides)] = sink.published
        self.assertEqual((view, guides, mask.shape), ("mask", None, (48, 64, 3)))
        self.assertTrue(np.all(mask == 127))
        sink.view = "output"
        effect.update(Profile())
        effect(self.frame)
        self.assertEqual(len(sink.published), 1)

    def test_original_view_keeps_framing_without_effects(self) -> None:
        sink = Sink("original")
        effect = self.effect(Profile(crop=(0, 0, 0.5, 0.5), brightness=40), sink)
        output = effect(self.frame)
        assert output is not None
        [(original, view, guides)] = sink.published
        self.assertEqual(
            (view, guides, original.shape), ("original", None, (24, 32, 3))
        )
        np.testing.assert_array_equal(original, self.frame[:24, :32])
        self.assertGreater(int(output.max()), int(original.max()))

    def test_effect_records_processed_rate_and_time(self) -> None:
        effect = self.effect(Profile(brightness=3), Sink("output"))
        for _ in range(3):
            effect(self.frame)
        fps, seconds = effect.stats.snapshot()
        self.assertIsNotNone(fps)
        assert seconds is not None
        self.assertGreater(seconds, 0)


class RateMeterTests(unittest.TestCase):
    def test_rate_and_mean_duration_over_window(self) -> None:
        now = 0.0
        meter = RateMeter(window=2, clock=lambda: now)
        self.assertEqual(meter.snapshot(), (None, None))
        for tick in range(31):
            now = tick / 30
            meter.tick(0.01 if tick % 2 else 0.03)
        fps, seconds = meter.snapshot()
        assert fps is not None and seconds is not None
        self.assertAlmostEqual(fps, 30)
        self.assertAlmostEqual(seconds, 0.02, delta=0.001)
        now = 10
        self.assertEqual(meter.snapshot(), (None, None))


class ControllerPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.effect = Mock()
        self.effect.stats.snapshot.return_value = (29.94, 0.01234)
        self.effect.recording.return_value = {"recorder": "idle", "recorded_seconds": 0}
        self.started = threading.Event()
        self.frames = threading.Event()

        def runner(profile, stop, ready, source_ready, **callbacks):
            self.callbacks = callbacks
            callbacks["on_effect"](self.effect)
            ready()
            for _ in range(3):
                callbacks["on_frame"](np.zeros((8, 8, 3), np.uint8))
            self.started.set()
            stop.wait(5)

        with patch("webcam_mods.control.run_profile", runner):
            self.controller = Controller(
                ProfileStore(Path(directory.name) / "profiles.db"), lambda _: None
            )
        self.addCleanup(self.controller.stop)

    def test_views_and_stats_follow_session(self) -> None:
        dispatch = self.controller.dispatch
        self.assertIsNone(dispatch("session.stats", {}))
        with self.assertRaisesRegex(ValueError, "view must be one of"):
            dispatch("preview.get", {"view": "depth"})
        with self.assertRaisesRegex(ValueError, "accepts only view"):
            dispatch("preview.get", {"view": "mask", "size": 1})
        with self.assertRaisesRegex(ValueError, "params must be empty"):
            dispatch("session.stats", {"view": "mask"})
        self.controller.start(Profile(), "preview")
        self.assertTrue(self.started.wait(1))
        self.assertIs(self.callbacks["preview"], self.controller.preview)
        self.assertIsNone(dispatch("preview.get", {"view": "source"}))
        assert self.controller.preview is not None
        self.assertTrue(self.controller.preview.wants("source"))
        stats = dispatch("session.stats", {})
        self.assertEqual(stats["processed_fps"], 29.9)
        self.assertEqual(stats["effect_ms"], 12.3)
        self.assertIsNotNone(stats["sent_fps"])
        self.assertEqual(stats["recorder"], "idle")
        self.controller.stop()
        self.assertIsNone(dispatch("session.stats", {}))


if __name__ == "__main__":
    unittest.main()
