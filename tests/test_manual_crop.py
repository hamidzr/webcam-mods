"""Manual crop profiles: validation, live cropping and tracking inside the crop."""

from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.effects import ProfileEffect, TrackingEffect
from webcam_mods.geometry import Rect
from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.settings import StartupSettings


def columns(height: int = 48, width: int = 64) -> np.ndarray:
    """Frame whose blue channel is the column index and green the row index."""
    frame = np.zeros((height, width, 3), np.uint8)
    frame[:, :, 0] = np.arange(width, dtype=np.uint8)[None, :]
    frame[:, :, 1] = np.arange(height, dtype=np.uint8)[:, None]
    return frame


class Sink:
    def __init__(self) -> None:
        self.guides: list[object] = []

    def wants(self, view: str) -> bool:
        return view == "source"

    def publish(self, frame, view="output", guides=None) -> None:
        self.guides.append(guides)


class CropProfileTests(unittest.TestCase):
    def test_crop_is_validated_and_round_trips_as_json(self) -> None:
        profile = Profile.parse({"crop": [0.25, 0, 0.5, 0.75]})
        self.assertEqual(profile.crop, (0.25, 0.0, 0.5, 0.75))
        self.assertEqual(hash(profile), hash(Profile(crop=(0.25, 0, 0.5, 0.75))))
        self.assertEqual(
            json.loads(json.dumps(asdict(profile)))["crop"], [0.25, 0, 0.5, 0.75]
        )
        for crop in (
            [0.1, 0.1, 0.5],
            [0, 0, True, 0.5],
            [0, 0, math.nan, 0.5],
            [0, 0, 0.01, 0.5],
            [0.6, 0, 0.5, 0.5],
            [-0.1, 0, 0.5, 0.5],
            "0,0,1,1",
        ):
            with self.subTest(crop=crop), self.assertRaisesRegex(ValueError, "crop"):
                Profile.parse({"crop": crop})
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save("Framed", {"crop": [0.1, 0.2, 0.5, 0.5]})
            self.assertEqual(store.get("Framed").crop, (0.1, 0.2, 0.5, 0.5))
            store.save("Full", {})
            self.assertIsNone(store.get("Full").crop)


class ProfileEffectCropTests(unittest.TestCase):
    def effect(self, profile: Profile, **kwargs: object) -> ProfileEffect:
        effect = ProfileEffect(
            profile, StartupSettings(out_width=64, out_height=48), **kwargs  # type: ignore[arg-type]
        )
        self.addCleanup(effect.close)
        return effect

    def test_crop_applies_after_mirror_and_updates_live(self) -> None:
        sink = Sink()
        frame = columns()
        effect = self.effect(Profile(crop=(0.5, 0.5, 0.5, 0.5)), preview=sink)
        result = effect(frame)
        assert result is not None
        self.assertEqual(result.shape, (24, 32, 3))
        self.assertEqual((result[0, 0, 0], result[0, 0, 1]), (32, 24))
        self.assertEqual(sink.guides[-1], {"crop": [0.5, 0.5, 0.5, 0.5]})
        effect.update(Profile(crop=(0, 0, 0.25, 0.5), mirror=True))
        result = effect(frame)
        assert result is not None
        self.assertEqual(result.shape, (24, 16, 3))
        # mirrored frame starts at the original right edge
        self.assertEqual(result[0, 0, 0], 63)
        effect.update(Profile())
        result = effect(frame)
        assert result is not None
        self.assertEqual(result.shape, (48, 64, 3))
        self.assertEqual(sink.guides[-1], {})

    def test_crop_stays_inside_frame_after_rounding(self) -> None:
        result = self.effect(Profile(crop=(0.98, 0.98, 0.02, 0.02)))(columns())
        assert result is not None
        self.assertEqual(result.shape, (2, 2, 3))
        self.assertEqual((result[-1, -1, 0], result[-1, -1, 1]), (63, 47))


class TrackingInsideCropTests(unittest.TestCase):
    def tracking(self, face: Rect | None) -> TrackingEffect:
        detector = Mock()
        detector.predict.return_value = face
        with patch("webcam_mods.mods.mp_face.FaceDetector", return_value=detector):
            effect = TrackingEffect(StartupSettings(out_width=64, out_height=48))
        self.addCleanup(effect.close)
        self.detector = detector
        return effect

    def test_framing_stays_in_region_and_guides_use_frame_pixels(self) -> None:
        frame = columns(96, 128)
        region = Rect(w=64, h=48, t=48, l=64)
        effect = self.tracking(Rect(w=12, h=12, t=60, l=90))
        result = effect(frame, region)
        assert result is not None and effect.crop is not None
        self.detector.predict.assert_called_once()
        self.assertIs(self.detector.predict.call_args.args[0], frame)
        self.assertGreaterEqual(int(result[:, :, 0].min()), 64)
        self.assertGreaterEqual(int(result[:, :, 1].min()), 48)
        self.assertGreaterEqual(effect.crop.left, 64)
        self.assertGreaterEqual(effect.crop.top, 48)
        self.assertLessEqual(effect.crop.left + effect.crop.width, 128)
        self.assertEqual(effect.face.left, 90)  # type: ignore[union-attr]

    def test_face_outside_region_is_ignored(self) -> None:
        frame = columns(96, 128)
        effect = self.tracking(Rect(w=12, h=12, t=4, l=4))
        result = effect(frame, Rect(w=64, h=48, t=48, l=64))
        assert result is not None
        self.assertGreaterEqual(int(result[:, :, 0].min()), 64)

    def test_profile_crop_reaches_tracking_as_pixel_region(self) -> None:
        with patch("webcam_mods.effects.TrackingEffect") as tracking:
            tracker = tracking.return_value
            tracker.side_effect = lambda frame, region: frame[:10, :10]
            tracker.face = tracker.crop = None
            effect = ProfileEffect(
                Profile(track=True, crop=(0.25, 0.5, 0.5, 0.5)),
                StartupSettings(out_width=64, out_height=48),
            )
            self.addCleanup(effect.close)
            effect(columns())
        region = tracker.call_args.args[1]
        self.assertEqual(
            (region.left, region.top, region.width, region.height), (16, 24, 32, 24)
        )


if __name__ == "__main__":
    unittest.main()
