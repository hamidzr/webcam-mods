"""Camera diagnostics must use capture indices without opening a device."""

import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from webcam_mods.entry import app
from webcam_mods.macos.capture import (
    CameraInfo,
    camera_inventory,
    select_capture_device,
)


class CameraInventoryTest(unittest.TestCase):
    def test_inventory_matches_filtered_capture_indices(self) -> None:
        rate = SimpleNamespace(minFrameRate=lambda: 15.0, maxFrameRate=lambda: 30.0)
        fmt = SimpleNamespace(
            formatDescription=lambda: None,
            videoSupportedFrameRateRanges=lambda: [rate, rate],
        )
        physical = Mock()
        physical.manufacturer.return_value = "Camera Vendor"
        physical.modelID.return_value = "USB Camera"
        physical.localizedName.return_value = "Physical Camera"
        physical.formats.return_value = [fmt]
        obs = Mock()
        obs.manufacturer.return_value = "OBS Project"
        obs.modelID.return_value = "OBS Camera Extension"
        obs.localizedName.return_value = "OBS Virtual Camera"
        obs.formats.return_value = [fmt]
        for devices in ([obs, physical], [physical, obs]):
            av = SimpleNamespace(
                AVCaptureDevice=SimpleNamespace(
                    devicesWithMediaType_=lambda _: devices
                ),
                AVMediaTypeVideo="video",
            )
            cm = SimpleNamespace(
                CMVideoFormatDescriptionGetDimensions=lambda _: SimpleNamespace(
                    width=640, height=480
                )
            )
            with patch.dict(sys.modules, {"AVFoundation": av, "CoreMedia": cm}):
                cameras = camera_inventory()
            eligible = [camera for camera in cameras if camera.input_index is not None]
            self.assertEqual(
                eligible, [CameraInfo(0, "Physical Camera", ("640x480 at 15-30 fps",))]
            )
            self.assertIs(
                select_capture_device(devices, eligible[0].input_index)[1], physical
            )
            self.assertEqual(
                next(
                    camera for camera in cameras if camera.input_index is None
                ).excluded_reason,
                "OBS output",
            )
            physical.lockForConfiguration_.assert_not_called()
            obs.lockForConfiguration_.assert_not_called()

    def test_cli_displays_indices_and_excluded_output(self) -> None:
        with (
            patch("webcam_mods.entry.sys.platform", "darwin"),
            patch(
                "webcam_mods.macos.capture.camera_inventory",
                return_value=[
                    CameraInfo(0, "Physical Camera", ("640x480 at 30-30 fps",)),
                    CameraInfo(None, "OBS", (), "OBS output"),
                ],
            ),
        ):
            result = CliRunner().invoke(app, ["list-cameras"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--input-device 0: Physical Camera", result.output)
        self.assertIn("excluded (OBS output): OBS", result.output)
        self.assertIn("640x480 at 30-30 fps", result.output)

    def test_missing_extra_is_actionable(self) -> None:
        with (
            patch("webcam_mods.entry.sys.platform", "darwin"),
            patch(
                "webcam_mods.macos.capture.camera_inventory", side_effect=ImportError
            ),
        ):
            result = CliRunner().invoke(app, ["list-cameras"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("uv sync --extra macos", result.output)

    def test_non_macos_rejected_before_enumeration(self) -> None:
        with (
            patch("webcam_mods.entry.sys.platform", "linux"),
            patch("webcam_mods.macos.capture.camera_inventory") as inventory,
        ):
            result = CliRunner().invoke(app, ["list-cameras"])
        self.assertNotEqual(result.exit_code, 0)
        inventory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
