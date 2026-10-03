"""Screen capture contracts and headless production-loop coverage."""

from typing import Any
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.input.input import AdapterMetadata, FrameOutput
from webcam_mods.input.screen import Screen, ScreenSelection, select_screen_region
from webcam_mods.loopback import live_loop
from webcam_mods.utils.video import Frame


class RecordingOutput(FrameOutput):
    def __init__(self) -> None:
        super().__init__(width=32, height=24, fps=24, device="test")
        self.active = False
        self.frames: list[Frame] = []

    def setup(self) -> AdapterMetadata:
        self.active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def send(self, frame: Frame) -> None:
        self.frames.append(frame.copy())

    def wait_until_next_frame(self) -> None:
        raise AssertionError("unpaced loop must not wait")


class ScreenSelectionTest(unittest.TestCase):
    def test_picker_modes_use_global_points_not_retina_pixels(self) -> None:
        for mode, flags in (
            (ScreenSelection.area, []),
            (ScreenSelection.screen, ["--screen"]),
            (ScreenSelection.visible, ["--visible"]),
        ):
            with (
                self.subTest(mode=mode),
                patch("webcam_mods.input.screen.sys.platform", "darwin"),
                patch(
                    "webcam_mods.input.screen.shutil.which", return_value="/bin/picker"
                ),
                patch("webcam_mods.input.screen.subprocess.run") as run,
            ):
                run.return_value = Mock(returncode=0, stdout="-1440 -100 800 600\n")
                region = select_screen_region(mode)
                self.assertEqual(
                    (region.l, region.t, region.w, region.h), (-1440, -100, 800, 600)
                )
                self.assertEqual(
                    run.call_args.args[0], ["/bin/picker", *flags, "-f", "%X %Y %W %H"]
                )

    def test_cancel_and_invalid_output_are_rejected(self) -> None:
        for status, output in (
            (1, ""),
            (0, ""),
            (0, "0 0 0 100"),
            (0, "0 0 100 -1"),
            (0, "0 0 100 100 extra"),
        ):
            with (
                self.subTest(status=status, output=output),
                patch("webcam_mods.input.screen.sys.platform", "darwin"),
                patch(
                    "webcam_mods.input.screen.shutil.which", return_value="/bin/picker"
                ),
                patch(
                    "webcam_mods.input.screen.subprocess.run",
                    return_value=Mock(returncode=status, stdout=output),
                ),
            ):
                with self.assertRaises(ValueError):
                    select_screen_region(ScreenSelection.area)

    def test_unavailable_picker_never_launches(self) -> None:
        for platform, executable in (("linux", "/bin/picker"), ("darwin", None)):
            with (
                self.subTest(platform=platform),
                patch("webcam_mods.input.screen.sys.platform", platform),
                patch("webcam_mods.input.screen.shutil.which", return_value=executable),
                patch("webcam_mods.input.screen.subprocess.run") as run,
            ):
                with self.assertRaises(ValueError):
                    select_screen_region(ScreenSelection.area)
                run.assert_not_called()


class ScreenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.screen = Screen(-12, -20, 32, 24, fps=24, device="test")
        self.capture = Mock()
        self.pixels = np.zeros((24, 32, 4), dtype=np.uint8)
        self.pixels[:, :, :] = [10, 20, 30, 255]
        self.capture.grab.return_value = self.pixels

    def test_setup_reports_geometry_and_requested_cadence(self) -> None:
        with patch("webcam_mods.input.screen.mss", return_value=self.capture) as open_:
            self.assertEqual(
                self.screen.setup(), {"width": 32, "height": 24, "fps": 24}
            )
            self.screen.setup()
        open_.assert_called_once_with()
        self.assertTrue(self.screen.is_setup())
        self.screen.teardown()

    def test_capture_preserves_bgr_and_negative_monitor_coordinates(self) -> None:
        with patch("webcam_mods.input.screen.mss", return_value=self.capture):
            with self.screen:
                frame = self.screen.frame()
                self.assertIsNotNone(frame)
                assert frame is not None
                self.assertEqual(frame.shape, (24, 32, 3))
                self.assertEqual(frame.dtype, np.uint8)
                self.assertTrue(frame.flags.c_contiguous)
                np.testing.assert_array_equal(frame[0, 0], [10, 20, 30])
                self.capture.grab.assert_called_once_with(
                    {"top": -12, "left": -20, "width": 32, "height": 24}
                )
        self.capture.close.assert_called_once()

    def test_capture_before_setup_and_after_teardown_is_safe(self) -> None:
        self.assertIsNone(self.screen.frame())
        self.screen.teardown()
        with patch("webcam_mods.input.screen.mss", return_value=self.capture):
            self.screen.setup()
        self.screen.teardown()
        self.screen.teardown()
        self.assertFalse(self.screen.is_setup())
        self.assertIsNone(self.screen.frame())
        self.capture.close.assert_called_once()

    def test_invalid_geometry_and_cadence_never_open_capture(self) -> None:
        for name, value in (
            ("width", 0),
            ("height", -1),
            ("width", 2.5),
            ("height", True),
            ("fps", 0),
            ("fps", -1),
            ("fps", float("nan")),
            ("fps", float("inf")),
        ):
            with self.subTest(name=name, value=value):
                screen = Screen(width=32, height=24, fps=24, device="test")
                setattr(screen, name, value)
                with patch("webcam_mods.input.screen.mss") as open_:
                    with self.assertRaisesRegex(ValueError, f"screen {name}"):
                        screen.setup()
                open_.assert_not_called()
                self.assertFalse(screen.is_setup())

    def test_failed_setup_can_retry(self) -> None:
        with patch(
            "webcam_mods.input.screen.mss",
            side_effect=[RuntimeError("screen permission denied"), self.capture],
        ):
            with self.assertRaisesRegex(RuntimeError, "screen permission denied"):
                with self.screen:
                    self.fail("failed setup entered context")
            self.assertFalse(self.screen.is_setup())
            self.screen.setup()
        self.screen.teardown()
        self.capture.close.assert_called_once()

    def test_close_failure_still_detaches_capture(self) -> None:
        self.capture.close.side_effect = RuntimeError("close failed")
        with patch("webcam_mods.input.screen.mss", return_value=self.capture):
            self.screen.setup()
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            self.screen.teardown()
        self.screen.teardown()
        self.assertFalse(self.screen.is_setup())
        self.capture.close.assert_called_once()

    def test_production_loop_delivers_screen_pixels_and_cleans_up(self) -> None:
        output = RecordingOutput()
        with patch("webcam_mods.input.screen.mss", return_value=self.capture):
            live_loop(
                fIn=self.screen,
                fOut=output,
                interactive_listener=None,
                on_demand=False,
                max_frames=2,
                pace=False,
                strict_errors=True,
            )
        self.assertEqual(len(output.frames), 2)
        for frame in output.frames:
            np.testing.assert_array_equal(frame, self.pixels[:, :, :3])
        self.assertFalse(output.is_setup())
        self.assertFalse(self.screen.is_setup())
        self.capture.close.assert_called_once()

    def test_production_loop_capture_failure_cleans_up(self) -> None:
        output = RecordingOutput()
        self.capture.grab.side_effect = RuntimeError("capture failed")
        with patch("webcam_mods.input.screen.mss", return_value=self.capture):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                live_loop(
                    fIn=self.screen,
                    fOut=output,
                    interactive_listener=None,
                    on_demand=False,
                    max_frames=1,
                    pace=False,
                    strict_errors=True,
                )
        self.assertEqual(output.frames, [])
        self.assertFalse(output.is_setup())
        self.assertFalse(self.screen.is_setup())
        self.capture.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
