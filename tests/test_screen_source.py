"""Screen areas as a profile source, chosen in the app instead of a camera."""

from dataclasses import replace
import threading
import unittest
from unittest.mock import Mock, patch

from webcam_mods.control import run_profile
from webcam_mods.input.screen import Screen
from webcam_mods.profiles import RESTART_FIELDS, Profile


class ScreenSourceProfileTests(unittest.TestCase):
    def test_screen_region_is_validated_and_restarts(self) -> None:
        profile = Profile.parse(
            {"source": "screen", "screen_region": [-1920, -120, 1920, 1080]}
        )
        self.assertEqual(profile.screen_region, (-1920, -120, 1920, 1080))
        self.assertEqual(profile.capture_size, (1920, 1080))
        self.assertEqual(replace(profile, rotate=90).oriented_size, (1080, 1920))
        # a saved region stays with the profile while the camera is in use
        camera = Profile(screen_region=(0, 0, 800, 600))
        self.assertEqual(camera.capture_size, (640, 480))
        with self.assertRaisesRegex(ValueError, "requires screen_region"):
            Profile.parse({"source": "screen"})
        with self.assertRaisesRegex(ValueError, "invalid source"):
            Profile.parse({"source": "window"})
        for region in (
            [0, 0, 1920],
            [0, 0, 8, 1080],
            [0, 0, 1920, 9000],
            [0.5, 0, 1920, 1080],
            [True, 0, 1920, 1080],
            [99999999, 0, 1920, 1080],
            "0 0 1920 1080",
        ):
            with self.subTest(region=region):
                with self.assertRaisesRegex(ValueError, "screen_region"):
                    Profile.parse({"screen_region": region})
        self.assertLessEqual({"source", "screen_region"}, RESTART_FIELDS)

    def test_run_profile_captures_the_screen_area_without_a_camera(self) -> None:
        profile = Profile(
            source="screen",
            screen_region=(-1280, 40, 1280, 800),
            fps=15,
            camera_id="saved-camera",
        )
        with (
            patch("webcam_mods.capture.camera_index_for_id") as lookup,
            patch("webcam_mods.capture.create_camera") as camera,
            patch("webcam_mods.loopback.live_loop") as loop,
        ):
            run_profile(profile, threading.Event(), lambda: None, lambda _: None)
        lookup.assert_not_called()
        camera.assert_not_called()
        source = loop.call_args.kwargs["fIn"]
        self.assertIsInstance(source, Screen)
        self.assertEqual(
            (source.left, source.top, source.width, source.height, source.fps),
            (-1280, 40, 1280, 800, 15),
        )
        settings = loop.call_args.kwargs["settings"]
        self.assertEqual(
            (settings.in_width, settings.in_height, settings.out_width),
            (1280, 800, 1280),
        )
        loop.call_args.kwargs["mod"].close()

    def test_camera_source_ignores_a_saved_screen_region(self) -> None:
        source = Mock()
        with (
            patch("webcam_mods.capture.create_camera", return_value=source),
            patch("webcam_mods.loopback.live_loop") as loop,
        ):
            run_profile(
                Profile(screen_region=(0, 0, 800, 600)),
                threading.Event(),
                lambda: None,
                lambda _: None,
            )
        self.assertIs(loop.call_args.kwargs["fIn"], source)
        self.assertEqual(loop.call_args.kwargs["settings"].in_width, 640)
        loop.call_args.kwargs["mod"].close()


if __name__ == "__main__":
    unittest.main()
