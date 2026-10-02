"""Final-frame preview routing, pacing and window-close cleanup."""

from contextlib import ExitStack
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.input.input import FrameInput
from webcam_mods.loopback import default_frame_output, live_loop
from webcam_mods.mods.video_mods import resize_and_pad
from webcam_mods.output.gui import GUI


class Source(FrameInput):
    def __init__(self) -> None:
        super().__init__(width=8, height=6, fps=12)
        self.active = False
        self.reads = 0
        self.image = np.arange(144, dtype=np.uint8).reshape(6, 8, 3)

    def setup(self):
        self.active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args):
        self.active = False

    def is_setup(self):
        return self.active

    def frame(self):
        self.reads += 1
        return self.image.copy()


class PreviewTests(unittest.TestCase):
    def windows(self, visible=1):
        stack = ExitStack()
        self.addCleanup(stack.close)
        mocks = {}
        for name in (
            "namedWindow",
            "destroyWindow",
            "imshow",
            "waitKey",
            "getWindowProperty",
        ):
            mocks[name] = stack.enter_context(
                patch(f"webcam_mods.output.gui.cv2.{name}")
            )
        mocks["waitKey"].return_value = -1
        mocks["getWindowProperty"].return_value = visible
        return mocks

    def test_partial_window_setup_is_cleaned_up(self):
        windows = self.windows()
        windows["namedWindow"].side_effect = cv2.error("cannot create window")
        preview = GUI()
        with self.assertRaises(cv2.error):
            with preview:
                self.fail("failed setup must not enter context")
        windows["destroyWindow"].assert_called_once_with(preview.window_name)
        self.assertFalse(preview.is_setup())

    def test_selection_uses_negotiated_fps_and_configured_output_dimensions(self):
        with patch("webcam_mods.loopback.MAX_OUT_FPS", 30):
            preview = default_frame_output(12, backend="preview")
        self.assertIsInstance(preview, GUI)
        self.assertEqual(preview.fps, 12)
        from webcam_mods import config

        self.assertEqual(
            (preview.width, preview.height), (config.OUT_WIDTH, config.OUT_HEIGHT)
        )

    def test_preview_receives_exact_final_frame_and_close_stops_capture(self):
        windows = self.windows(visible=0)
        source = Source()
        preview = GUI(width=16, height=12, fps=12)
        transformed = source.image[:, ::-1].copy()
        live_loop(
            mod=lambda frame: frame[:, ::-1].copy(),
            fIn=source,
            fOut=preview,
            interactive_listener=None,
            on_demand=False,
            strict_errors=True,
        )
        self.assertEqual(source.reads, 1)
        np.testing.assert_array_equal(
            windows["imshow"].call_args.args[1], resize_and_pad(transformed, 16, 12)
        )
        self.assertFalse(source.active)
        self.assertFalse(preview.is_setup())
        windows["destroyWindow"].assert_called_once_with(preview.window_name)
        preview.teardown()
        windows["destroyWindow"].assert_called_once()

    def test_escape_stops_without_recreating_window(self):
        windows = self.windows()
        windows["waitKey"].return_value = 27
        preview = GUI()
        preview.setup()
        preview.wait_until_next_frame()
        self.assertTrue(preview.should_stop())
        preview.send(np.zeros((2, 2, 3), np.uint8))
        windows["imshow"].assert_not_called()
        preview.teardown()

    def test_destroyed_window_error_stops_normally(self):
        windows = self.windows()
        windows["getWindowProperty"].side_effect = cv2.error("window closed")
        preview = GUI()
        preview.setup()
        preview.wait_until_next_frame()
        self.assertTrue(preview.should_stop())
        windows["destroyWindow"].side_effect = cv2.error("already closed")
        preview.teardown()
        self.assertFalse(preview.is_setup())

    def test_processing_time_counts_toward_frame_period(self):
        self.windows()
        preview = GUI(fps=10)
        with patch("webcam_mods.output.gui.time.monotonic", return_value=10):
            preview.setup()
        clock = [10.08]

        def sleep(seconds):
            clock[0] += seconds

        with (
            patch(
                "webcam_mods.output.gui.time.monotonic", side_effect=lambda: clock[0]
            ),
            patch("webcam_mods.output.gui.time.sleep", side_effect=sleep) as wait,
        ):
            preview.wait_until_next_frame()
        self.assertAlmostEqual(sum(call.args[0] for call in wait.call_args_list), 0.02)
        self.assertAlmostEqual(clock[0], 10.1)
        preview.teardown()

    def test_preview_selection_bypasses_virtual_camera_backend(self):
        windows = self.windows(visible=0)
        source = Source()
        with patch("webcam_mods.output.pyvirtcam.pyvirtualcam.Camera") as virtual:
            live_loop(
                fIn=source,
                output_backend="preview",
                interactive_listener=None,
                on_demand=False,
                strict_errors=True,
            )
        virtual.assert_not_called()
        windows["imshow"].assert_called_once()
        self.assertFalse(source.active)
