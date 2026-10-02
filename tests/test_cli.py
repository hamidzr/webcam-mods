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
            patch.object(entry.sys, "platform", "darwin"),
            patch.object(entry.importlib.util, "find_spec", return_value=Mock()),
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

    def test_preview_output_propagates_for_camera_commands(self) -> None:
        for command in (
            "crop-cam",
            "bg-color",
            "bg-swap",
            "bg-blur",
            "brighten",
            "track-face",
            "test-loop",
        ):
            with (
                self.subTest(command=command),
                patch.object(entry, "live_loop") as loop,
                patch("webcam_mods.session.Config", return_value=Config(path=None)),
            ):
                result = CliRunner().invoke(
                    entry.app, ["--no-controls", "--output", "preview", command]
                )
                self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                self.assertEqual(loop.call_args.kwargs["output_backend"], "preview")

    def test_invalid_output_rejected_before_capture(self) -> None:
        with patch.object(entry, "live_loop") as loop:
            result = CliRunner().invoke(entry.app, ["--output", "unknown", "crop-cam"])
            self.assertNotEqual(result.exit_code, 0)
            loop.assert_not_called()

    def test_native_backend_rejected_on_other_platforms(self) -> None:
        with (
            patch.object(entry.sys, "platform", "linux"),
            patch.object(entry, "live_loop") as loop,
        ):
            result = CliRunner().invoke(
                entry.app, ["--segmentation-backend", "vision", "bg-blur"]
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("require macOS", result.output)
            loop.assert_not_called()

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


class CliPipelineTests(unittest.TestCase):
    def test_camera_commands_run_real_pipeline_without_desktop_controls(self) -> None:
        import cv2
        from test_pipeline import ImageSequence, ImageWriter
        from webcam_mods.loopback import live_loop

        fixture = Path(__file__).parent / "fixtures/astronaut.png"
        with tempfile.TemporaryDirectory() as directory:
            for command in (
                "crop-cam",
                "bg-color",
                "bg-swap",
                "bg-blur",
                "brighten",
                "track-face",
                "test-loop",
            ):
                with self.subTest(command=command):
                    source = ImageSequence([fixture] * 3)
                    source.width = source.height = 512
                    sink = ImageWriter(Path(directory) / command)

                    def bounded_loop(**kwargs):
                        kwargs["fIn"] = source
                        live_loop(
                            **kwargs,
                            fOut=sink,
                            max_frames=3,
                            strict_errors=True,
                            pace=False,
                        )

                    with (
                        patch.object(entry, "live_loop", side_effect=bounded_loop),
                        patch(
                            "webcam_mods.session.Config",
                            return_value=Config(path=None, width=512, height=512),
                        ),
                    ):
                        result = CliRunner().invoke(
                            entry.app, ["--no-controls", command]
                        )
                    self.assertEqual(
                        result.exit_code, 0, (result.output, result.exception)
                    )
                    self.assertEqual(len(sink.paths), 3)
                    self.assertFalse(source.is_setup())
                    self.assertFalse(sink.is_setup())
                    self.assertEqual(
                        cv2.imread(str(sink.paths[0])).shape, (120, 160, 3)
                    )
