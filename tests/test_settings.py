"""Startup resolution, validation and propagation before device acquisition."""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from webcam_mods import entry
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.loopback import default_frame_output
from webcam_mods.input.video_dev import Webcam
from webcam_mods.uses.interactive_controls import KeyboardControls
from webcam_mods.session import RunSession
from webcam_mods.utils.config import Config


class SettingsTests(unittest.TestCase):
    def test_defaults_and_environment(self) -> None:
        self.assertEqual(load_settings({}), StartupSettings())
        settings = load_settings(
            {
                "IN_WIDTH": "1280",
                "IN_FPS": "29.97",
                "ON_DEMAND": "true",
                "PAN_CONTROL": "0",
            }
        )
        self.assertEqual(settings.in_width, 1280)
        self.assertEqual(settings.in_fps, 29.97)
        self.assertTrue(settings.on_demand)
        self.assertFalse(settings.pan_control)

    def test_override_wins_over_invalid_environment(self) -> None:
        self.assertEqual(load_settings({"IN_WIDTH": "bad"}, in_width=800).in_width, 800)
        with self.assertRaisesRegex(ValueError, "unknown startup"):
            load_settings({}, bogus=1)

    def test_invalid_settings_rejected(self) -> None:
        for name, value in (
            ("IN_WIDTH", "0"),
            ("VIDEO_IN", "-1"),
            ("IN_FPS", "nan"),
            ("MAX_OUT_FPS", "inf"),
            ("IN_FORMAT", "ABC"),
            ("ON_DEMAND", "maybe"),
            ("VIDEO_OUT", ""),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                load_settings({name: value})

    def test_snapshot_is_independent_of_later_environment(self) -> None:
        settings = load_settings(
            {},
            in_width=800,
            out_width=1024,
            in_fps=24,
            max_out_fps=20,
            pan_control=False,
            padding_control=False,
        )
        with patch.dict(os.environ, {"IN_WIDTH": "bad", "OUT_WIDTH": "bad"}):
            camera = Webcam(settings=settings)
            output = default_frame_output(24, backend="preview", settings=settings)
            session = RunSession(
                Config(path=None, width=settings.in_width, height=settings.in_height)
            )
            keyboard = KeyboardControls(session, settings)
            keyboard.start()
        self.assertEqual(camera.width, 800)
        self.assertEqual(output.width, 1024)
        self.assertEqual(output.fps, 20)
        self.assertIsNone(keyboard.listener)
        session.close()

    def test_help_survives_invalid_environment(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "webcam_mods", "--help"],
            env={**os.environ, "IN_WIDTH": "bad", "IN_FPS": "bad"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_validates_before_loop_and_passes_overrides(self) -> None:
        with (
            patch.object(entry, "live_loop") as loop,
            patch.dict(os.environ, {"IN_WIDTH": "bad"}),
        ):
            result = CliRunner().invoke(entry.app, ["--no-controls", "crop-cam"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("IN_WIDTH", result.output)
            loop.assert_not_called()
            result = CliRunner().invoke(
                entry.app,
                [
                    "--no-controls",
                    "--input-width",
                    "800",
                    "--output-fps",
                    "24",
                    "--no-on-demand",
                    "test-loop",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            settings = loop.call_args.kwargs["settings"]
            self.assertEqual(settings.in_width, 800)
            self.assertEqual(settings.max_out_fps, 24)
            self.assertFalse(settings.on_demand)

    def test_fractional_fps_face_transition_uses_whole_frame_count(self) -> None:
        from webcam_mods.mods.camera_motion import CropTracker
        from webcam_mods.geometry import Rect

        tracker = CropTracker(fps=29.97)
        tracker.generate_crop(Rect(l=0, t=0, w=20, h=20), None)
        for _ in range(35):
            tracker.generate_crop(Rect(l=100, t=100, w=20, h=20), None)
        self.assertIsInstance(tracker.fps, int)
        tracker.close()
