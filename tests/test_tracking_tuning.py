"""Auto-framing preferences: profile validation and live tracker changes."""

import unittest
from unittest.mock import patch

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.geometry import Rect
from webcam_mods.mods.camera_motion import CropTracker
from webcam_mods.profiles import Profile
from webcam_mods.settings import StartupSettings


class TrackingProfileTests(unittest.TestCase):
    def test_defaults_match_cli_and_ranges_are_enforced(self) -> None:
        profile = Profile()
        self.assertEqual(
            (
                profile.track_face_height,
                profile.track_target_y,
                profile.track_max_zoom,
                profile.track_follow_seconds,
                profile.track_deadzone,
            ),
            (0.4, 0.42, 2.0, 0.25, 0.08),
        )
        self.assertEqual(Profile.parse({"track_max_zoom": 3}).track_max_zoom, 3)
        for key, value in (
            ("track_face_height", 0.05),
            ("track_target_y", 0.9),
            ("track_max_zoom", 5),
            ("track_follow_seconds", 0),
            ("track_deadzone", True),
            ("track_deadzone", float("nan")),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(ValueError, key):
                    Profile.parse({key: value})


class CropTrackerConfigureTests(unittest.TestCase):
    def test_configure_keeps_motion_state_and_rejects_invalid_values(self) -> None:
        tracker = CropTracker(30, aspect_ratio=4 / 3, face_height=0.4)
        face = Rect(w=60, h=60, t=180, l=290)
        first = tracker.generate_crop(face, frame_size=(640, 480), now=0)
        tracker.configure(face_height=0.2, pan_seconds=1)
        self.assertEqual(tracker.cur_crop.h, first.h)  # type: ignore[union-attr]
        # a smaller target face widens the crop gradually, not in one jump
        second = tracker.generate_crop(face, frame_size=(640, 480), now=1 / 30)
        self.assertGreater(second.h, first.h)
        self.assertLess(second.h, 300)
        with self.assertRaisesRegex(ValueError, "Face height"):
            tracker.configure(face_height=0)
        self.assertEqual(tracker.face_height, 0.2)


class ProfileTrackingTests(unittest.TestCase):
    def test_framing_fields_reach_tracker_live(self) -> None:
        with patch("webcam_mods.effects.TrackingEffect") as tracking:
            tracking.return_value.side_effect = lambda frame, region: frame
            effect = ProfileEffect(
                Profile(track=True, track_follow_seconds=0.5),
                StartupSettings(out_width=64, out_height=48),
            )
            self.addCleanup(effect.close)
            frame = np.zeros((48, 64, 3), np.uint8)
            effect(frame)
            options = tracking.call_args.kwargs
            self.assertEqual(options["pan_seconds"], 0.5)
            self.assertEqual(options["zoom_seconds"], 1.2)
            self.assertEqual(options["face_height"], 0.4)
            effect.update(Profile(track=True, track_follow_seconds=0.5, brightness=4))
            effect(frame)
            tracking.return_value.configure.assert_not_called()
            effect.update(
                Profile(track=True, track_face_height=0.3, track_deadzone=0.2)
            )
            effect(frame)
        tracking.assert_called_once()
        configured = tracking.return_value.configure.call_args.kwargs
        self.assertEqual(
            (
                configured["face_height"],
                configured["pan_deadzone"],
                configured["zoom_deadzone"],
                configured["pan_seconds"],
            ),
            (0.3, 0.2, 0.2, 0.25),
        )


if __name__ == "__main__":
    unittest.main()
