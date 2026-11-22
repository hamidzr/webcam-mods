"""Startup resolution, validation and propagation before device acquisition."""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from cli_fixtures import HeadlessCliTestCase

from webcam_mods import entry
from webcam_mods.settings import StartupSettings, hotkey_groups, load_settings
from webcam_mods.loopback import default_frame_output
from webcam_mods.input.video_dev import Webcam
from webcam_mods.uses.interactive_controls import KeyboardControls
from webcam_mods.session import RunSession
from webcam_mods.utils.config import Config


class SettingsTests(HeadlessCliTestCase):
    def test_defaults_and_environment(self) -> None:
        self.assertEqual(load_settings({}), StartupSettings())
        settings = load_settings(
            {
                "IN_WIDTH": "1280",
                "IN_FPS": "29.97",
                "ON_DEMAND": "true",
                "HOTKEYS": "pad",
            }
        )
        self.assertEqual(settings.in_width, 1280)
        self.assertEqual(settings.in_fps, 29.97)
        self.assertTrue(settings.on_demand)
        self.assertEqual(settings.hotkeys, "pad")

    def test_hotkey_groups(self) -> None:
        self.assertEqual(hotkey_groups("crop,pad"), {"crop", "pad"})
        self.assertEqual(hotkey_groups(" Pad "), {"pad"})
        self.assertEqual(hotkey_groups("none"), frozenset())
        self.assertEqual(hotkey_groups(""), frozenset())
        with self.assertRaisesRegex(ValueError, "zoom"):
            hotkey_groups("zoom")

    def test_hotkeys_limit_keyboard_groups(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock

        keys = SimpleNamespace(
            ctrl="ctrl", alt="alt", shift="shift", right="r", left="l", up="u", down="d"
        )
        session = Mock()
        controls = KeyboardControls(session, load_settings({}, hotkeys="pad"))
        controls.key_type = keys
        for key in ("ctrl", "r"):
            controls.on_press(key)
        session.submit.assert_not_called()
        controls.keys.clear()
        for key in ("alt", "r"):
            controls.on_press(key)
        session.submit.assert_called_once()
        self.assertEqual(session.submit.call_args.args[0].action, "pad")

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
            ("SIGNAL_PATTERN", "invalid"),
            ("HOTKEYS", "crop,zoom"),
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
            hotkeys="none",
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

    def test_fractional_fps_face_tracker_preserves_rate(self) -> None:
        from webcam_mods.mods.camera_motion import CropTracker
        from webcam_mods.geometry import Rect

        tracker = CropTracker(fps=29.97)
        tracker.generate_crop(Rect(l=0, t=0, w=20, h=20), None, frame_size=(640, 480))
        for _ in range(35):
            tracker.generate_crop(
                Rect(l=100, t=100, w=20, h=20), None, frame_size=(640, 480)
            )
        self.assertEqual(tracker.fps, 29.97)
        tracker.close()

    def test_linux_missing_extra_has_actionable_error(self) -> None:
        import builtins

        original_import = builtins.__import__

        def missing_extra(name, *args, **kwargs):
            if name == "webcam_mods.output.v4l2loopback":
                raise ModuleNotFoundError("No module named v4l2", name="v4l2")
            return original_import(name, *args, **kwargs)

        with (
            patch("webcam_mods.loopback.platform.system", return_value="Linux"),
            patch("builtins.__import__", side_effect=missing_extra),
        ):
            with self.assertRaisesRegex(RuntimeError, "uv sync --extra linux"):
                default_frame_output(30)
