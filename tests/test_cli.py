"""CLI startup and per-command settings propagation without desktop access."""

from pathlib import Path
from typing import Any
import numpy as np
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner
from typer._click.utils import strip_ansi

from cli_fixtures import HeadlessCliTestCase

from webcam_mods import entry
from webcam_mods.utils.config import Config


class CliTests(HeadlessCliTestCase):
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
        self.assertIn("capture-backend", strip_ansi(result.output))
        self.assertIn("no-controls", strip_ansi(result.output))
        for panel in (
            "Input",
            "Output",
            "Effects",
            "Controls",
            "Camera",
            "Background",
            "Screen",
            "Utilities",
        ):
            self.assertIn(panel, result.output)

    def test_command_help_lists_shared_options_without_validating_environment(
        self,
    ) -> None:
        with patch.dict(os.environ, {"IN_WIDTH": "invalid"}):
            result = CliRunner().invoke(
                entry.app, ["bg-blur", "--help"], terminal_width=160
            )
        self.assertEqual(result.exit_code, 0, result.output)
        for option in ("--kernel-size", "--output", "--no-controls", "--input-width"):
            self.assertIn(option, strip_ansi(result.output))

    def test_shared_options_work_before_after_and_mixed_with_effect_options(
        self,
    ) -> None:
        options = [
            "--no-controls",
            "--output",
            "preview",
            "--input-width",
            "800",
            "--freeze-on-error",
        ]
        for args in (
            [*options, "brighten", "--level", "12"],
            ["brighten", "--level", "12", *options],
            [
                "--input-width",
                "800",
                "brighten",
                "--output=preview",
                "--level",
                "12",
                "--no-controls",
                "--freeze-on-error",
            ],
        ):
            with self.subTest(args=args), patch.object(entry, "_run") as run:
                result = CliRunner().invoke(entry.app, args)
                self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                common = run.call_args.args[0]
                self.assertFalse(common.controls)
                self.assertTrue(common.freeze_on_error)
                self.assertEqual(common.output, "preview")
                self.assertEqual(common.settings.in_width, 800)

    def test_command_side_overrides_root_without_defaults_erasing_root_values(
        self,
    ) -> None:
        with patch.object(entry, "_run") as run:
            result = CliRunner().invoke(
                entry.app,
                [
                    "--output",
                    "virtual-cam",
                    "--input-width",
                    "800",
                    "--no-controls",
                    "--freeze-on-error",
                    "crop-cam",
                    "--output",
                    "preview",
                    "--controls",
                ],
            )
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        common = run.call_args.args[0]
        self.assertEqual(common.output, "preview")
        self.assertEqual(common.settings.in_width, 800)
        self.assertTrue(common.controls)
        self.assertTrue(common.freeze_on_error)

    def test_post_command_cli_override_wins_over_invalid_environment(self) -> None:
        with (
            patch.dict(os.environ, {"IN_WIDTH": "invalid"}),
            patch.object(entry, "_run") as run,
        ):
            result = CliRunner().invoke(entry.app, ["crop-cam", "--input-width", "800"])
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        self.assertEqual(run.call_args.args[0].settings.in_width, 800)

    def test_freeze_environment_is_deferred_for_help_and_explicit_overrides(
        self,
    ) -> None:
        with patch.dict(os.environ, {"freeze_on_error": "invalid"}):
            for args in (
                ["crop-cam", "--help"],
                ["crop-cam", "--no-freeze-on-error"],
                ["--freeze-on-error", "crop-cam"],
            ):
                with self.subTest(args=args), patch.object(entry, "_run") as run:
                    result = CliRunner().invoke(entry.app, args)
                    self.assertEqual(
                        result.exit_code, 0, (result.output, result.exception)
                    )
                    if "--help" in args:
                        run.assert_not_called()
                    else:
                        self.assertEqual(
                            run.call_args.args[0].freeze_on_error,
                            "--freeze-on-error" in args,
                        )
            with patch.object(entry, "_run") as run:
                result = CliRunner().invoke(entry.app, ["crop-cam"])
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("freeze_on_error", result.output)
                run.assert_not_called()
        with (
            patch.dict(os.environ, {"freeze_on_error": "true"}),
            patch.object(entry, "_run") as run,
        ):
            result = CliRunner().invoke(entry.app, ["crop-cam"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(run.call_args.args[0].freeze_on_error)

    def test_post_command_invalid_common_options_fail_before_acquisition(self) -> None:
        for options in (
            ["--input-fps", "nan"],
            ["--output", "unknown"],
            ["--input-width", "0"],
            ["--input-width"],
        ):
            with self.subTest(options=options), patch.object(entry, "_run") as run:
                result = CliRunner().invoke(entry.app, ["crop-cam", *options])
                self.assertNotEqual(result.exit_code, 0)
                run.assert_not_called()

    def test_local_option_values_and_end_of_options_are_not_reinterpreted(self) -> None:
        with patch.object(entry.cv2, "imread", return_value=None) as read:
            result = CliRunner().invoke(
                entry.app, ["bg-swap", "--img-path", "--output"]
            )
            self.assertNotEqual(result.exit_code, 0)
            read.assert_called_once_with("--output")
        with patch.object(entry, "_run") as run:
            result = CliRunner().invoke(
                entry.app, ["crop-cam", "--", "--output", "preview"]
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("unexpected extra argument", result.output.lower())
            run.assert_not_called()

    def test_screen_region_uses_shared_settings_output_and_controls(self) -> None:
        with (
            patch.object(entry, "live_loop") as loop,
            patch("webcam_mods.session.Config", return_value=Config(path=None)),
            patch.object(entry, "ControlAdapters") as controls,
        ):
            result = CliRunner().invoke(
                entry.app,
                [
                    "share-screen",
                    "--left",
                    "-640",
                    "--top",
                    "-20",
                    "--width",
                    "320",
                    "--height",
                    "240",
                    "--input-fps",
                    "24",
                    "--output",
                    "preview",
                    "--output-width",
                    "800",
                    "--output-height",
                    "600",
                    "--no-controls",
                    "--freeze-on-error",
                ],
            )
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        kwargs = loop.call_args.kwargs
        screen = kwargs["fIn"]
        self.assertEqual(
            (screen.left, screen.top, screen.width, screen.height, screen.fps),
            (-640, -20, 320, 240, 24),
        )
        self.assertEqual(kwargs["output_backend"], "preview")
        self.assertEqual(
            (kwargs["settings"].out_width, kwargs["settings"].out_height), (800, 600)
        )
        self.assertTrue(kwargs["freeze_on_error"])
        controls.assert_not_called()

    def test_screen_border_tracks_crop_and_closes_on_pipeline_failure(self) -> None:
        from webcam_mods.input.screen import Screen
        from webcam_mods.session import Command

        screen = Screen(left=-100, top=20, width=32, height=24, fps=30)
        indicator = Mock()

        def loop(**kwargs: Any) -> None:
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            result = kwargs["mod"](frame)
            self.assertEqual(result.shape, frame.shape)
            session = kwargs["before_frame"].__self__
            session.submit(Command("resize", -8, -6))
            session.submit(Command("move", 4, 3))
            kwargs["before_frame"]()
            result = kwargs["mod"](frame)
            self.assertEqual(result.shape, (18, 24, 3))
            region = indicator.update.call_args.args[0]
            self.assertEqual(
                (region.l, region.t, region.w, region.h), (-96, 23, 24, 18)
            )
            raise RuntimeError("pipeline failed")

        with patch.object(entry, "live_loop", side_effect=loop):
            with self.assertRaisesRegex(RuntimeError, "pipeline failed"):
                entry._run(
                    entry.Common(controls=False), source=screen, border=indicator
                )
        indicator.start.assert_called_once()
        indicator.close.assert_called_once()

    def test_screen_picker_wires_selected_geometry(self) -> None:
        from webcam_mods.geometry import Rect

        with (
            patch.object(entry.sys, "platform", "darwin"),
            patch.object(
                entry,
                "select_screen_region",
                return_value=Rect(t=-20, l=-800, w=800, h=600),
            ) as picker,
            patch.object(entry, "_run") as run,
        ):
            result = CliRunner().invoke(
                entry.app, ["share-screen", "--select", "area", "--output", "preview"]
            )
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        picker.assert_called_once_with(entry.ScreenSelection.area, aspect=(640, 480))
        screen = run.call_args.kwargs["source"]
        self.assertEqual(
            (screen.left, screen.top, screen.width, screen.height),
            (-800, -20, 800, 600),
        )

    def test_screen_picker_conflicts_and_cancellation_never_start_capture(self) -> None:
        for options in (
            ["--left", "0"],
            ["--top", "0"],
            ["--width", "100"],
            ["--height", "100"],
            [],
        ):
            with (
                self.subTest(options=options),
                patch.object(
                    entry,
                    "select_screen_region",
                    side_effect=ValueError("selection cancelled"),
                ) as picker,
                patch.object(entry, "_run") as run,
            ):
                result = CliRunner().invoke(
                    entry.app, ["share-screen", "--select", "area", *options]
                )
                self.assertNotEqual(result.exit_code, 0)
                run.assert_not_called()
                if options:
                    picker.assert_not_called()

    def test_screen_default_region_and_legacy_gui_alias(self) -> None:
        with patch.object(entry, "_run") as run:
            result = CliRunner().invoke(
                entry.app,
                [
                    "share-screen",
                    "--input-width",
                    "800",
                    "--input-height",
                    "600",
                    "--output",
                    "gui",
                ],
            )
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        self.assertEqual(run.call_args.args[0].output, "preview")
        screen = run.call_args.kwargs["source"]
        self.assertEqual((screen.width, screen.height), (800, 600))

    def test_invalid_screen_options_fail_before_acquisition(self) -> None:
        for options in (
            ["--width", "0"],
            ["--height", "-1"],
            ["--capture-backend", "avfoundation"],
        ):
            with (
                self.subTest(options=options),
                patch.object(entry, "_run") as run,
                patch.object(entry.sys, "platform", "darwin"),
                patch.object(entry.importlib.util, "find_spec", return_value=Mock()),
            ):
                result = CliRunner().invoke(entry.app, ["share-screen", *options])
                self.assertNotEqual(result.exit_code, 0)
                run.assert_not_called()

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
                    "--mask-smoothing",
                    "bg-blur",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            effects.assert_called_once_with(
                backend="vision", processing="coreimage", quality="fast", smoothing=True
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


class CliPipelineTests(HeadlessCliTestCase):
    def test_screen_command_runs_shared_pipeline_and_output_factory(self) -> None:
        import cv2
        import numpy as np
        from test_pipeline import ImageWriter
        from webcam_mods.loopback import live_loop

        capture = Mock()
        capture.grab.return_value = np.full((24, 32, 4), 45, np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            sink = ImageWriter(Path(directory) / "screen")
            sink.width, sink.height, sink.fps = 64, 48, 20

            def bounded_loop(**kwargs):
                live_loop(**kwargs, max_frames=3, strict_errors=True, pace=False)

            with (
                patch("webcam_mods.input.screen.mss", return_value=capture),
                patch.object(entry, "live_loop", side_effect=bounded_loop),
                patch(
                    "webcam_mods.loopback.default_frame_output", return_value=sink
                ) as output,
                patch(
                    "webcam_mods.session.Config",
                    return_value=Config(path=None, width=32, height=24),
                ),
                patch.object(entry, "ControlAdapters") as controls,
            ):
                result = CliRunner().invoke(
                    entry.app,
                    [
                        "share-screen",
                        "--width",
                        "32",
                        "--height",
                        "24",
                        "--input-fps",
                        "24",
                        "--output-width",
                        "64",
                        "--output-height",
                        "48",
                        "--output-fps",
                        "20",
                        "--output",
                        "preview",
                        "--no-controls",
                    ],
                )
            self.assertEqual(result.exit_code, 0, (result.output, result.exception))
            self.assertEqual(len(sink.paths), 3)
            np.testing.assert_array_equal(
                cv2.imread(str(sink.paths[0])), np.full((48, 64, 3), 45, np.uint8)
            )
            self.assertEqual(output.call_args.args[0], 24)
            self.assertEqual(output.call_args.kwargs["backend"], "preview")
            self.assertEqual(output.call_args.kwargs["settings"].max_out_fps, 20)
            capture.close.assert_called_once()
            controls.assert_not_called()
            self.assertFalse(sink.is_setup())

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
