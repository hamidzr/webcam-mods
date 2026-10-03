"""Virtual-camera ownership checks without an installed OBS backend."""

import unittest
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np

from webcam_mods.output.pyvirtcam import PyVirtualCam


class VirtualCameraStateTest(unittest.TestCase):
    def test_setup_state_tracks_owned_camera(self) -> None:
        output = PyVirtualCam(width=32, height=24, fps=30, device="unused")
        self.assertFalse(output.is_setup())
        handle = MagicMock(width=32, height=24, fps=30, device="OBS Virtual Camera")
        with patch(
            "webcam_mods.output.pyvirtcam.pyvirtualcam.Camera", return_value=handle
        ):
            output.setup()
        self.assertTrue(output.is_setup())
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        output.send(frame)
        self.assertIs(handle.send.call_args.args[0], frame)
        output.teardown()
        self.assertFalse(output.is_setup())
        handle.close.assert_called_once()

    def test_closed_camera_rejects_delivery_and_pacing(self) -> None:
        output = PyVirtualCam(width=32, height=24, fps=30, device="unused")
        with self.assertRaisesRegex(RuntimeError, "virtual camera is not open"):
            output.send(np.zeros((24, 32, 3), dtype=np.uint8))
        with self.assertRaisesRegex(RuntimeError, "virtual camera is not open"):
            output.wait_until_next_frame()


class LinuxCameraStateTest(unittest.TestCase):
    def test_setup_state_tracks_owned_device(self) -> None:
        monitor_module = types.ModuleType("webcam_mods.utils.file_monitor")
        monitor_module.MonitorFile = MagicMock()
        v4l2_module = types.ModuleType("v4l2")
        with patch.dict(
            sys.modules,
            {"webcam_mods.utils.file_monitor": monitor_module, "v4l2": v4l2_module},
        ):
            # execute an uncached module so mocked Linux dependencies stay local
            source = (
                Path(__file__).resolve().parents[1]
                / "src/webcam_mods/output/v4l2loopback.py"
            )
            spec = importlib.util.spec_from_file_location("_v4l2_output_test", source)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            output = module.V4l2Cam(width=32, height=24, fps=30, device="/dev/video10")
            output.on_demand.inotify = None
            self.assertFalse(output.is_setup())
            with self.assertRaisesRegex(RuntimeError, "V4L2 camera is not open"):
                output.send(np.zeros((24, 32, 3), dtype=np.uint8))
            handle = MagicMock()
            output.dev = handle
            self.assertTrue(output.is_setup())
            output.teardown()
            self.assertFalse(output.is_setup())
            handle.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
