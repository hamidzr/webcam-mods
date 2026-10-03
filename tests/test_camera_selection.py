"""Terminal camera selection must precede effects and preserve unattended launches."""

from contextlib import ExitStack
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from webcam_mods import entry
from webcam_mods.input import selection
from webcam_mods.macos.capture import CameraInfo


class CameraSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        stack.enter_context(patch("webcam_mods.input.selection.sys.platform", "darwin"))
        self.terminal = stack.enter_context(
            patch(
                "webcam_mods.input.selection._interactive_terminal", return_value=True
            )
        )
        self.inventory = stack.enter_context(
            patch(
                "webcam_mods.macos.capture.camera_inventory",
                return_value=[
                    CameraInfo(None, "OBS", (), "OBS output"),
                    CameraInfo(1, "Built-in camera", ()),
                    CameraInfo(3, "USB camera", ()),
                ],
            )
        )
        self.run = stack.enter_context(patch.object(entry, "_run"))

    def test_selection_reaches_capture_without_changing_other_settings(self) -> None:
        result = CliRunner().invoke(
            entry.app, ["test-loop", "--input-width", "1280"], input="3\n"
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("1: Built-in camera", result.output)
        self.assertIn("3: USB camera", result.output)
        self.assertNotIn("OBS", result.output)
        self.assertIn("--input-device 3", result.output)
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 3)
        self.assertEqual(self.run.call_args.args[0].settings.in_width, 1280)
        self.inventory.assert_called_once_with("auto")

    def test_enter_uses_first_eligible_camera_when_zero_is_excluded(self) -> None:
        result = CliRunner().invoke(entry.app, ["test-loop"], input="\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 1)

    def test_invalid_number_and_noninteger_retry(self) -> None:
        result = CliRunner().invoke(entry.app, ["test-loop"], input="oops\n2\n3\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Choose one of the listed", result.output)
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 3)

    def test_single_camera_auto_selects_without_prompt(self) -> None:
        self.inventory.return_value = [CameraInfo(4, "USB camera", ())]
        result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("Camera index", result.output)
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 4)

    def test_explicit_cli_indices_skip_picker_in_either_position(self) -> None:
        for args, expected in (
            (["--input-device", "1", "test-loop"], 1),
            (["test-loop", "--input-device", "3"], 3),
            (["--input-device", "1", "test-loop", "--input-device", "3"], 3),
        ):
            with self.subTest(args=args):
                result = CliRunner().invoke(entry.app, args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(self.run.call_args.args[0].settings.video_in, expected)
        self.assertEqual(self.inventory.call_count, 3)

    def test_environment_index_skips_picker(self) -> None:
        with patch.dict(os.environ, {"VIDEO_IN": "1"}):
            result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.inventory.assert_called_once_with("auto")
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 1)

    def test_no_terminal_checks_availability_without_prompt(self) -> None:
        self.terminal.return_value = False
        self.inventory.return_value = [CameraInfo(0, "USB camera", ())]
        result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.inventory.assert_called_once_with("auto")
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 0)

    def test_closed_lid_leaves_single_usb_camera_without_prompt(self) -> None:
        self.inventory.return_value = [
            CameraInfo(0, "USB camera", ()),
            CameraInfo(1, "MacBook camera", (), "laptop lid closed"),
        ]
        with patch("webcam_mods.input.selection.typer.prompt") as prompt:
            result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Warning: excluding MacBook camera", result.output)
        self.assertIn("lid closed", result.output)
        self.assertIn("Using USB camera", result.output)
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 0)
        prompt.assert_not_called()

    def test_unavailable_explicit_env_and_unattended_fail_before_effects(self) -> None:
        self.inventory.return_value = [
            CameraInfo(0, "MacBook camera", (), "laptop lid closed")
        ]
        for args, env, terminal in (
            (["bg-blur", "--input-device", "0"], {}, True),
            (["bg-blur"], {"VIDEO_IN": "0"}, True),
            (["bg-blur"], {}, False),
        ):
            with (
                self.subTest(args=args, env=env, terminal=terminal),
                patch.dict(os.environ, env),
                patch.object(entry, "BackgroundEffect") as effect,
            ):
                self.terminal.return_value = terminal
                result = CliRunner().invoke(entry.app, args)
                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn("lid closed", result.output)
                effect.assert_not_called()
        self.run.assert_not_called()

    def test_closed_lid_only_camera_fails_with_actionable_message(self) -> None:
        self.inventory.return_value = [
            CameraInfo(1, "MacBook camera", (), "laptop lid closed")
        ]
        result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("open laptop lid", result.output)
        self.run.assert_not_called()

    def test_non_macos_does_not_enumerate(self) -> None:
        with patch("webcam_mods.input.selection.sys.platform", "linux"):
            result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.inventory.assert_not_called()

    def test_help_screen_and_utility_commands_skip_picker(self) -> None:
        with patch("webcam_mods.input.screen.Screen"):
            for args in (["--help"], ["bg-blur", "--help"], ["share-screen"]):
                with self.subTest(args=args):
                    result = CliRunner().invoke(entry.app, args)
                    self.assertEqual(result.exit_code, 0, result.output)
        # list-cameras enumerates for diagnostics, but never prompts
        with patch("webcam_mods.input.selection.typer.prompt") as prompt:
            result = CliRunner().invoke(entry.app, ["list-cameras"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.inventory.assert_called_once_with("auto")
        prompt.assert_not_called()

    def test_cancellation_precedes_effect_initialization(self) -> None:
        with patch.object(entry, "BackgroundEffect") as effect:
            result = CliRunner().invoke(entry.app, ["bg-blur"], input="")
        self.assertEqual(result.exit_code, 1, result.output)
        effect.assert_not_called()
        self.run.assert_not_called()

    def test_empty_inventory_and_obs_only_fail_before_capture(self) -> None:
        for cameras in ([], [CameraInfo(None, "OBS", (), "OBS output")]):
            self.inventory.return_value = cameras
            result = CliRunner().invoke(entry.app, ["test-loop"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("no input cameras", result.output)
        self.run.assert_not_called()

    def test_missing_macos_extras_preserves_opencv_startup(self) -> None:
        self.inventory.side_effect = ImportError
        result = CliRunner().invoke(entry.app, ["test-loop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("uv sync --extra macos", result.output)
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 0)

    def test_native_backend_uses_native_inventory(self) -> None:
        with patch("webcam_mods.entry.importlib.util.find_spec", return_value=Mock()):
            result = CliRunner().invoke(
                entry.app,
                ["test-loop", "--capture-backend", "avfoundation"],
                input="3\n",
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.inventory.assert_called_once_with("avfoundation")
        self.assertEqual(self.run.call_args.args[0].settings.video_in, 3)


class TerminalTests(unittest.TestCase):
    def test_both_streams_must_be_terminals(self) -> None:
        for stdin, stdout in (
            (False, False),
            (False, True),
            (True, False),
            (True, True),
        ):
            with (
                self.subTest(stdin=stdin, stdout=stdout),
                patch.object(
                    selection,
                    "sys",
                    SimpleNamespace(
                        stdin=SimpleNamespace(isatty=lambda: stdin),
                        stdout=SimpleNamespace(isatty=lambda: stdout),
                    ),
                ),
            ):
                self.assertEqual(selection._interactive_terminal(), stdin and stdout)


if __name__ == "__main__":
    unittest.main()
