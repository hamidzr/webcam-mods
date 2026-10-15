"""Camera orientation: rotation, flips and rotated default output size."""

import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.control import run_profile
from webcam_mods.effects import ProfileEffect
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings


def corners() -> np.ndarray:
    """3x2 frame whose blue channel numbers the pixels row by row."""
    frame = np.zeros((2, 3, 3), np.uint8)
    frame[:, :, 0] = np.arange(6, dtype=np.uint8).reshape(2, 3)
    return frame


class OrientationProfileTests(unittest.TestCase):
    def test_rotation_is_validated_and_restarts(self) -> None:
        self.assertEqual(Profile.parse({"rotate": 270}).rotate, 270)
        for rotate in (45, -90, 360, 90.0, True, "90"):
            with self.subTest(rotate=rotate):
                with self.assertRaisesRegex(ValueError, "rotate"):
                    Profile.parse({"rotate": rotate})
        with self.assertRaisesRegex(ValueError, "flip_vertical"):
            Profile.parse({"flip_vertical": 1})
        self.assertIn("rotate", RESTART_FIELDS)
        self.assertNotIn("flip_vertical", RESTART_FIELDS)

    def test_quarter_turns_swap_oriented_size(self) -> None:
        self.assertEqual(Profile(width=1280, height=720).oriented_size, (1280, 720))
        self.assertEqual(
            Profile(width=1280, height=720, rotate=180).oriented_size, (1280, 720)
        )
        self.assertEqual(
            Profile(width=1280, height=720, rotate=90).oriented_size, (720, 1280)
        )


class ProfileEffectOrientationTests(unittest.TestCase):
    def output(self, profile: Profile) -> np.ndarray:
        effect = ProfileEffect(profile, StartupSettings(out_width=3, out_height=2))
        self.addCleanup(effect.close)
        result = effect(corners())
        assert result is not None
        return result[:, :, 0]

    def test_rotation_then_flips(self) -> None:
        for profile, expected in (
            (Profile(), [[0, 1, 2], [3, 4, 5]]),
            (Profile(rotate=90), [[3, 0], [4, 1], [5, 2]]),
            (Profile(rotate=180), [[5, 4, 3], [2, 1, 0]]),
            (Profile(rotate=270), [[2, 5], [1, 4], [0, 3]]),
            (Profile(flip_vertical=True), [[3, 4, 5], [0, 1, 2]]),
            (Profile(mirror=True, flip_vertical=True), [[5, 4, 3], [2, 1, 0]]),
            # mirror applies to the rotated picture, as the viewer sees it
            (Profile(rotate=90, mirror=True), [[0, 3], [1, 4], [2, 5]]),
        ):
            with self.subTest(profile=profile):
                np.testing.assert_array_equal(self.output(profile), expected)

    def test_vertical_flip_updates_live_and_crop_uses_rotated_frame(self) -> None:
        effect = ProfileEffect(
            Profile(rotate=90, crop=(0, 0, 1, 2 / 3)),
            StartupSettings(out_width=2, out_height=3),
        )
        self.addCleanup(effect.close)
        result = effect(corners())
        assert result is not None
        np.testing.assert_array_equal(result[:, :, 0], [[3, 0], [4, 1]])
        effect.update(Profile(rotate=90, crop=(0, 0, 1, 2 / 3), flip_vertical=True))
        result = effect(corners())
        assert result is not None
        np.testing.assert_array_equal(result[:, :, 0], [[5, 2], [4, 1]])


class RotatedOutputSizeTests(unittest.TestCase):
    def settings(self, profile: Profile) -> StartupSettings:
        with (
            patch("webcam_mods.capture.create_camera", return_value=Mock()) as camera,
            patch("webcam_mods.effects.ProfileEffect", return_value=Mock()),
            patch("webcam_mods.loopback.live_loop"),
        ):
            run_profile(profile, threading.Event(), lambda: None, lambda source: None)
        settings: StartupSettings = camera.call_args.args[0]
        return settings

    def test_default_output_follows_rotation_and_explicit_size_wins(self) -> None:
        settings = self.settings(Profile(width=1280, height=720, rotate=270))
        self.assertEqual((settings.in_width, settings.in_height), (1280, 720))
        self.assertEqual((settings.out_width, settings.out_height), (720, 1280))
        settings = self.settings(
            Profile(width=1280, height=720, rotate=90, output_width=640)
        )
        self.assertEqual((settings.out_width, settings.out_height), (640, 1280))


if __name__ == "__main__":
    unittest.main()
