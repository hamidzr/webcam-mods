"""Verify capture requests and independent delivery settings without hardware."""

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from typer.testing import CliRunner

from cli_fixtures import HeadlessCliTestCase

from webcam_mods import entry
from webcam_mods.input.input import FrameOutput
from webcam_mods.input.video_dev import Webcam, open_video_capture
from webcam_mods.loopback import live_loop
from webcam_mods.settings import StartupSettings


def capture_mock(fps: float = 30) -> Mock:
    capture = Mock()
    capture.isOpened.return_value = True
    values = {
        cv2.CAP_PROP_FRAME_WIDTH: 32,
        cv2.CAP_PROP_FRAME_HEIGHT: 24,
        cv2.CAP_PROP_FPS: fps,
    }
    capture.get.side_effect = values.__getitem__
    capture.read.return_value = (True, np.full((24, 32, 3), 45, np.uint8))
    return capture


class CaptureSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = StartupSettings(in_width=32, in_height=24)
        self.capture = capture_mock()
        self.camera = Webcam(settings=self.settings)
        self.addCleanup(lambda: self.camera.teardown())

    def setup_camera(self):
        with patch(
            "webcam_mods.input.video_dev.cv2.VideoCapture", return_value=self.capture
        ):
            return self.camera.setup()

    def test_fps_is_requested_after_format_and_dimensions(self) -> None:
        # emulate a driver resetting FPS on each format/resolution change
        actual_fps = 30.0

        def configure(prop, value):
            nonlocal actual_fps
            actual_fps = value if prop == cv2.CAP_PROP_FPS else 30.0
            return True

        self.capture.set.side_effect = configure
        self.capture.get.side_effect = lambda prop: (
            actual_fps
            if prop == cv2.CAP_PROP_FPS
            else {cv2.CAP_PROP_FRAME_WIDTH: 32, cv2.CAP_PROP_FRAME_HEIGHT: 24}[prop]
        )
        with patch(
            "webcam_mods.input.video_dev.cv2.VideoCapture", return_value=self.capture
        ):
            result = open_video_capture(32, 24, fps=15, pixel_format="YUYV")
        self.assertEqual(result[3], 15)
        self.assertEqual(
            self.capture.set.call_args_list[-1],
            unittest.mock.call(cv2.CAP_PROP_FPS, 15),
        )

    def test_startup_validates_real_frame_and_preserves_it(self) -> None:
        first = np.full((24, 32, 3), 12, np.uint8)
        second = np.full((24, 32, 3), 23, np.uint8)
        self.capture.read.side_effect = [(True, first), (True, second)]
        self.assertEqual(self.setup_camera(), {"width": 32, "height": 24, "fps": 30})
        self.assertIs(self.camera.frame(), first)
        self.assertIs(self.camera.frame(), second)
        self.assertEqual(self.capture.read.call_count, 2)

    def test_actual_frame_overrides_unreliable_dimension_metadata(self) -> None:
        self.capture.read.return_value = (True, np.zeros((48, 64, 3), np.uint8))
        with self.assertRaisesRegex(ValueError, "returned 64x48; requested 32x24"):
            self.setup_camera()
        self.capture.release.assert_called_once()
        self.assertFalse(self.camera.is_setup())
        self.assertIsNone(self.camera.frame())

    def test_fps_is_checked_after_first_frame(self) -> None:
        def read():
            self.capture.get.side_effect = lambda prop: 60
            return True, np.zeros((24, 32, 3), np.uint8)

        self.capture.read.side_effect = read
        with self.assertRaisesRegex(ValueError, "returned 60 FPS; requested 30"):
            self.setup_camera()
        self.capture.release.assert_called_once()

    def test_nominal_fractional_fps_is_accepted(self) -> None:
        self.capture.get.side_effect = lambda prop: (
            29.97
            if prop == cv2.CAP_PROP_FPS
            else {cv2.CAP_PROP_FRAME_WIDTH: 32, cv2.CAP_PROP_FRAME_HEIGHT: 24}[prop]
        )
        self.assertEqual(self.setup_camera()["fps"], 29.97)

    def test_invalid_or_unsupported_fps_releases_camera(self) -> None:
        for fps in (0, float("nan"), float("inf"), 15, 60):
            with self.subTest(fps=fps):
                self.capture = capture_mock(fps)
                with self.assertRaisesRegex(ValueError, "FPS"):
                    self.setup_camera()
                self.capture.release.assert_called_once()
                self.assertFalse(self.camera.is_setup())

    def test_missing_first_frame_releases_camera(self) -> None:
        self.capture.read.return_value = (False, None)
        with self.assertRaisesRegex(RuntimeError, "no frame during startup"):
            self.setup_camera()
        self.capture.release.assert_called_once()

    def test_shape_changes_during_capture_fail(self) -> None:
        self.setup_camera()
        self.camera.frame()
        self.capture.read.return_value = (True, np.zeros((48, 64, 3), np.uint8))
        with self.assertRaisesRegex(RuntimeError, "changed resolution during capture"):
            self.camera.frame()

    def test_reported_user_drift_is_not_called_an_unsupported_mode(self) -> None:
        self.camera = Webcam(
            settings=StartupSettings(in_width=1280, in_height=720, in_fps=30)
        )
        self.capture.read.side_effect = [
            (True, np.zeros((720, 1280, 3), np.uint8)),
            (True, np.zeros((480, 864, 3), np.uint8)),
        ]
        self.setup_camera()
        self.assertEqual(self.camera.frame().shape, (720, 1280, 3))
        with self.assertRaisesRegex(RuntimeError, "1280x720 -> 864x480") as raised:
            self.camera.frame()
        self.assertNotIn("Choose supported", str(raised.exception))

    def test_constructor_fps_override_reaches_capture(self) -> None:
        self.camera = Webcam(settings=self.settings, fps=24)
        self.capture = capture_mock(24)
        self.setup_camera()
        self.assertIn(
            unittest.mock.call(cv2.CAP_PROP_FPS, 24), self.capture.set.call_args_list
        )

    def test_failed_setup_can_retry_with_same_requested_dimensions(self) -> None:
        self.capture.read.return_value = (True, np.zeros((48, 64, 3), np.uint8))
        with self.assertRaises(ValueError):
            self.setup_camera()
        self.capture = capture_mock()
        self.assertEqual(self.setup_camera()["width"], 32)
        self.assertEqual(self.camera.frame().shape, (24, 32, 3))


class DeliverySettingsTests(HeadlessCliTestCase):
    def test_cli_capture_and_delivery_are_independent(self) -> None:
        for input_fps, output_cap, effective_fps in ((60, 15, 15), (15, 60, 15)):
            for position in ("before", "after"):
                with self.subTest(input_fps=input_fps, position=position):
                    now = 10.0
                    sent = []
                    capture = capture_mock(input_fps)
                    output_options = {}

                    def sleep(seconds):
                        nonlocal now
                        now += seconds

                    class Sink(FrameOutput):
                        def __init__(self, **kwargs):
                            super().__init__(**kwargs)
                            output_options.update(kwargs)
                            self.active = False

                        def setup(self):
                            self.active = True
                            return {
                                "width": self.width,
                                "height": self.height,
                                "fps": self.fps,
                            }

                        def teardown(self, *args):
                            self.active = False

                        def is_setup(self):
                            return self.active

                        def send(self, frame):
                            sent.append((now, frame.copy()))

                        def wait_until_next_frame(self):
                            raise AssertionError("loop owns pacing")

                    def bounded_loop(**kwargs):
                        live_loop(**kwargs, max_frames=3, strict_errors=True)

                    options = [
                        "--no-controls",
                        "--capture-backend",
                        "opencv",
                        "--input-width",
                        "32",
                        "--input-height",
                        "24",
                        "--input-fps",
                        str(input_fps),
                        "--output-width",
                        "64",
                        "--output-height",
                        "36",
                        "--output-fps",
                        str(output_cap),
                        "--output",
                        "preview",
                    ]
                    args = (
                        [*options, "test-loop"]
                        if position == "before"
                        else ["test-loop", *options]
                    )
                    with (
                        patch.object(entry, "live_loop", side_effect=bounded_loop),
                        patch(
                            "webcam_mods.input.video_dev.cv2.VideoCapture",
                            return_value=capture,
                        ),
                        patch("webcam_mods.output.gui.GUI", Sink),
                        patch("webcam_mods.timing.time.monotonic", lambda: now),
                        patch("webcam_mods.timing.time.sleep", side_effect=sleep),
                    ):
                        result = CliRunner().invoke(entry.app, args)
                    self.assertEqual(result.exit_code, 0, result.exception)
                    self.assertEqual(output_options["fps"], effective_fps)
                    self.assertEqual(output_options["width"], 64)
                    self.assertEqual(output_options["height"], 36)
                    self.assertEqual(capture.read.call_count, 3)
                    capture.release.assert_called_once()
                    self.assertIn(
                        unittest.mock.call(cv2.CAP_PROP_FPS, input_fps),
                        capture.set.call_args_list,
                    )
                    np.testing.assert_allclose(
                        [item[0] for item in sent],
                        [10, 10 + 1 / effective_fps, 10 + 2 / effective_fps],
                    )
                    for _, frame in sent:
                        self.assertEqual(frame.shape, (36, 64, 3))
                        np.testing.assert_array_equal(frame[:, :8], 0)
                        np.testing.assert_array_equal(frame[:, 8:56], 45)
                        np.testing.assert_array_equal(frame[:, 56:], 0)


if __name__ == "__main__":
    unittest.main()
