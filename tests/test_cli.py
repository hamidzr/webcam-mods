"""CLI startup and per-command settings propagation without desktop access."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from webcam_mods import entry
from webcam_mods.utils.config import Config


class CliTests(unittest.TestCase):
    def test_import_has_no_desktop_or_persistence_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = (
                "import pathlib, sys, threading; "
                f"pathlib.Path.home = classmethod(lambda cls: pathlib.Path({directory!r})); "
                "before = len(threading.enumerate()); import webcam_mods.entry; "
                "print(len(threading.enumerate()) - before); "
                "print('pynput' in sys.modules)"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.splitlines(), ["0", "False"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_help_exposes_explicit_backends(self) -> None:
        result = CliRunner().invoke(entry.app, ["--help"], terminal_width=160)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("capture-backend", result.output)
        self.assertIn("no-controls", result.output)

    def test_no_controls_and_freeze_propagate_for_basic_commands(self) -> None:
        for command in ("crop-cam", "brighten", "test-loop"):
            with self.subTest(command=command):
                with (
                    patch.object(entry, "live_loop") as loop,
                    patch("webcam_mods.session.Config", return_value=Config(path=None)),
                    patch.object(entry, "ControlAdapters") as controls,
                ):
                    result = CliRunner().invoke(
                        entry.app, ["--no-controls", "--freeze-on-error", command]
                    )
                    self.assertEqual(result.exit_code, 0, result.output)
                    controls.assert_not_called()
                    self.assertIsNone(loop.call_args.kwargs["interactive_listener"])
                    self.assertTrue(loop.call_args.kwargs["freeze_on_error"])

    def test_background_backend_selection_and_cleanup(self) -> None:
        with (
            patch("webcam_mods.mods.person_segmentation.PersonEffects") as effects,
            patch.object(entry, "live_loop") as loop,
            patch("webcam_mods.session.Config", return_value=Config(path=None)),
        ):
            result = CliRunner().invoke(
                entry.app,
                [
                    "--no-controls",
                    "--segmentation-backend",
                    "vision",
                    "--processing-backend",
                    "coreimage",
                    "--vision-quality",
                    "fast",
                    "bg-blur",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            effects.assert_called_once_with(
                backend="vision", processing="coreimage", quality="fast"
            )
            effects.return_value.close.assert_called_once()
            self.assertIsNone(loop.call_args.kwargs["interactive_listener"])

    def test_effect_and_session_close_when_capture_fails(self) -> None:
        effect = Mock()
        with (
            patch.object(
                entry, "live_loop", side_effect=RuntimeError("capture failed")
            ),
            patch.object(entry, "RunSession") as session,
        ):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                entry._run(entry.Common(controls=False), effect)
            effect.close.assert_called_once()
            session.return_value.close.assert_called_once()

    def test_invalid_background_or_kernel_fails_before_capture(self) -> None:
        for args in (
            ["bg-swap", "--img-path", "/nonexistent/background.jpg"],
            ["bg-blur", "--kernel-size", "2"],
        ):
            with patch.object(entry, "live_loop") as loop:
                result = CliRunner().invoke(entry.app, args)
                self.assertNotEqual(result.exit_code, 0)
                loop.assert_not_called()
