"""Headless regression checks for adapter acquisition and loop boundaries."""

from typing import Any
import unittest
from unittest.mock import Mock, patch
import importlib
import sys
import types

import numpy as np

from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.loopback import live_loop
from webcam_mods.input.video_dev import (
    Webcam,
    available_camera_indices,
    open_video_capture,
)
from webcam_mods.output.pyvirtcam import PyVirtualCam


class Source(FrameInput):
    def __init__(self) -> None:
        super().__init__(width=32, height=24, fps=29.97)
        self.active = False
        self.setup_count = 0
        self.teardown_count = 0
        self.fail_setup = False
        self.events: list[str] = []

    def setup(self) -> dict[str, Any]:
        self.setup_count += 1
        self.active = True
        if self.fail_setup:
            raise RuntimeError("partial input setup")
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.teardown_count += 1
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def frame(self) -> np.ndarray:
        self.events.append("capture")
        return np.zeros((24, 32, 3), dtype=np.uint8)


class Sink(FrameOutput):
    def __init__(self) -> None:
        super().__init__(width=32, height=24, fps=30)
        self.active = False
        self.fail_setup = False
        self.sent = 0
        self.waits = 0
        self.teardown_count = 0

    def setup(self) -> dict[str, Any]:
        self.active = True
        if self.fail_setup:
            raise RuntimeError("partial output setup")
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.teardown_count += 1
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def send(self, frame: np.ndarray) -> None:
        self.sent += 1

    def wait_until_next_frame(self) -> None:
        self.waits += 1


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Source()
        self.sink = Sink()

    def run_loop(self, **kwargs: Any) -> None:
        live_loop(
            pace=False,
            fIn=self.source,
            fOut=kwargs.pop("fOut", self.sink),
            interactive_listener=kwargs.pop("interactive_listener", None),
            max_frames=2,
            on_demand=False,
            strict_errors=True,
            **kwargs,
        )

    def test_default_output_uses_single_negotiated_input_setup(self) -> None:
        with patch(
            "webcam_mods.loopback.default_frame_output", return_value=self.sink
        ) as factory:
            self.run_loop(fOut=None)
        self.assertEqual(factory.call_args.args, (29.97,))
        self.assertEqual(factory.call_args.kwargs["backend"], "virtual-cam")
        self.assertEqual(self.source.setup_count, 1)
        self.assertEqual(self.sink.sent, 2)
        self.assertFalse(self.source.active)
        self.assertFalse(self.sink.active)

    def test_partial_input_setup_cleanup(self) -> None:
        self.source.fail_setup = True
        listener = Mock()
        with self.assertRaisesRegex(RuntimeError, "partial input setup"):
            self.run_loop(interactive_listener=listener)
        self.assertFalse(self.source.active)
        self.assertEqual(self.source.teardown_count, 1)
        listener.stop.assert_called_once()
        self.assertEqual(self.sink.teardown_count, 0)

    def test_partial_output_setup_cleanup(self) -> None:
        self.sink.fail_setup = True
        with self.assertRaisesRegex(RuntimeError, "partial output setup"):
            self.run_loop()
        self.assertFalse(self.source.active)
        self.assertFalse(self.sink.active)
        self.assertEqual(self.sink.teardown_count, 1)

    def test_context_manager_cleans_partial_input_setup(self) -> None:
        self.source.fail_setup = True
        with self.assertRaisesRegex(RuntimeError, "partial input setup"):
            with self.source:
                self.fail("failed setup entered context")
        self.assertFalse(self.source.active)

    def test_invalid_metadata_cleanup(self) -> None:
        for name, invalid in [
            ("width", 0),
            ("height", -1),
            ("fps", float("nan")),
            ("fps", float("inf")),
        ]:
            with self.subTest(name=name, invalid=invalid):
                self.source = Source()
                setattr(self.source, name, invalid)
                with self.assertRaisesRegex(ValueError, f"invalid input {name}"):
                    self.run_loop()
                self.assertFalse(self.source.active)

    def test_controls_drain_before_capture_and_output_paces_once(self) -> None:
        self.run_loop(before_frame=lambda: self.source.events.append("control"))
        self.assertEqual(
            self.source.events, ["control", "capture", "control", "capture"]
        )
        self.assertEqual(self.sink.waits, 0)

    def test_control_failure_cleanup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "control failure"):
            self.run_loop(
                before_frame=Mock(side_effect=RuntimeError("control failure"))
            )
        self.assertFalse(self.source.active)
        self.assertFalse(self.sink.active)


class AdapterCleanupTest(unittest.TestCase):
    def test_failed_camera_open_releases_handle(self) -> None:
        capture = Mock()
        capture.isOpened.return_value = False
        with patch(
            "webcam_mods.input.video_dev.cv2.VideoCapture", return_value=capture
        ):
            self.assertIsNone(open_video_capture())
        capture.release.assert_called_once()

    def test_camera_honors_configured_fps(self) -> None:
        capture = Mock()
        capture.get.return_value = 30
        with (
            patch("webcam_mods.input.video_dev.cv2.VideoCapture", return_value=capture),
            patch("webcam_mods.input.video_dev.config.IN_FPS", 24),
        ):
            open_video_capture()
        import cv2

        self.assertIn(
            unittest.mock.call(cv2.CAP_PROP_FPS, 24), capture.set.call_args_list
        )

    def test_camera_enumeration_releases_all_handles(self) -> None:
        captures = [Mock(), Mock()]
        captures[0].read.return_value = (False, None)
        captures[1].read.return_value = (True, None)
        with patch(
            "webcam_mods.input.video_dev.cv2.VideoCapture", side_effect=captures
        ):
            self.assertEqual(list(available_camera_indices(2)), [1])
        for capture in captures:
            capture.release.assert_called_once()

    def test_camera_teardown_is_idempotent(self) -> None:
        camera = Webcam()
        capture = Mock()
        camera.cap = capture
        camera.teardown()
        camera.teardown()
        capture.release.assert_called_once()
        self.assertFalse(camera.is_setup())

    def test_virtual_camera_constructor_failure_preserves_error(self) -> None:
        camera = PyVirtualCam()
        with patch(
            "webcam_mods.output.pyvirtcam.pyvirtualcam.Camera",
            side_effect=RuntimeError("missing OBS"),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing OBS"):
                with camera:
                    self.fail("failed setup entered context")
        camera.teardown()

    def test_virtual_camera_teardown_is_idempotent(self) -> None:
        camera = PyVirtualCam()
        handle = Mock()
        camera.cam = handle
        camera.teardown()
        camera.teardown()
        handle.close.assert_called_once()

    def test_linux_partial_setup_closes_device(self) -> None:
        monitor_module = types.ModuleType("webcam_mods.utils.file_monitor")
        monitor_module.MonitorFile = Mock()
        v4l2_module = types.ModuleType("v4l2")
        with patch.dict(
            sys.modules,
            {"webcam_mods.utils.file_monitor": monitor_module, "v4l2": v4l2_module},
        ):
            module = importlib.import_module("webcam_mods.output.v4l2loopback")
            camera = module.V4l2Cam()
            camera.on_demand.inotify = None
            handle = Mock()
            with (
                patch.object(module.os.path, "exists", return_value=True),
                patch("builtins.open", return_value=handle),
                patch.object(
                    module,
                    "prep_v4l2_descriptor",
                    side_effect=RuntimeError("format failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "format failure"):
                    with camera:
                        self.fail("failed setup entered context")
            handle.close.assert_called_once()
            camera.teardown()
            handle.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
