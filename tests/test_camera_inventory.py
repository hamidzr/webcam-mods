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
    def test_auto_excludes_muxed_only_inputs_only_when_using_native_capture(
        self,
    ) -> None:
        video, muxed = Mock(), Mock()
        for device, identity in ((video, "b"), (muxed, "a")):
            device.uniqueID.return_value = identity
            device.manufacturer.return_value = "vendor"
            device.modelID.return_value = "camera"
            device.localizedName.return_value = identity
            device.formats.return_value = []
        av = SimpleNamespace(
            AVCaptureDevice=SimpleNamespace(
                devicesWithMediaType_=lambda media: (
                    [video] if media == "video" else [muxed]
                )
            ),
            AVMediaTypeVideo="video",
            AVMediaTypeMuxed="muxed",
        )
        for resolved in ("avfoundation", "opencv"):
            with (
                self.subTest(resolved=resolved),
                patch.dict(sys.modules, {"AVFoundation": av, "CoreMedia": Mock()}),
                patch("webcam_mods.capture.resolve_backend", return_value=resolved),
            ):
                cameras = camera_inventory("auto")
            self.assertEqual(cameras[1].input_index, 1)
            if resolved == "avfoundation":
                self.assertIsNone(cameras[0].input_index)
                self.assertIn("not a native video input", cameras[0].excluded_reason)
            else:
                self.assertEqual(cameras[0].input_index, 0)
                self.assertIsNone(cameras[0].excluded_reason)

    def test_lid_filter_preserves_indices_and_native_selection(self) -> None:
        from webcam_mods.macos.availability import BUILT_IN_TRANSPORT
        from webcam_mods.macos.capture import select_capture_device_by_id

        builtin, usb = Mock(), Mock()
        for device, name, transport in (
            (builtin, "MacBook camera", BUILT_IN_TRANSPORT),
            (usb, "USB camera", int.from_bytes(b"usb ", "big")),
        ):
            device.localizedName.return_value = name
            device.transportType.return_value = transport
            device.isConnected.return_value = True
            device.isSuspended.return_value = False
            device.formats.return_value = []
        av = SimpleNamespace(
            AVCaptureDevice=SimpleNamespace(
                devicesWithMediaType_=lambda _: [builtin, usb]
            ),
            AVMediaTypeVideo="video",
        )
        with (
            patch.dict(sys.modules, {"AVFoundation": av, "CoreMedia": Mock()}),
            patch("webcam_mods.macos.capture.lid_closed", return_value=True),
        ):
            cameras = camera_inventory()
            self.assertEqual([camera.input_index for camera in cameras], [0, 1])
            self.assertIn("lid closed", cameras[0].excluded_reason or "")
            self.assertIsNone(cameras[1].excluded_reason)
            with self.assertRaisesRegex(ValueError, "lid closed"):
                select_capture_device([builtin, usb], 0)
            self.assertIs(select_capture_device([builtin, usb], 1)[1], usb)
            builtin.uniqueID.return_value = "builtin"
            usb.uniqueID.return_value = "usb"
            with self.assertRaisesRegex(ValueError, "lid closed"):
                select_capture_device_by_id([builtin, usb], "builtin")
            self.assertIs(select_capture_device_by_id([builtin, usb], "usb")[1], usb)

    def test_opencv_indices_follow_unique_ids_and_include_muxed_devices(self) -> None:
        def device(name: str, unique_id: str, manufacturer: str) -> Mock:
            result = Mock()
            result.localizedName.return_value = name
            result.uniqueID.return_value = unique_id
            result.manufacturer.return_value = manufacturer
            result.modelID.return_value = "camera"
            result.formats.return_value = []
            return result

        usb = device("USB camera", "c", "vendor")
        obs = device("OBS", "b", "OBS Project")
        muxed = device("Muxed camera", "a", "vendor")
        enumerate_devices = Mock(side_effect=[[usb, obs], [muxed]])
        av = SimpleNamespace(
            AVCaptureDevice=SimpleNamespace(devicesWithMediaType_=enumerate_devices),
            AVMediaTypeVideo="video",
            AVMediaTypeMuxed="muxed",
        )
        with patch.dict(sys.modules, {"AVFoundation": av, "CoreMedia": Mock()}):
            cameras = camera_inventory("opencv")
        self.assertEqual(
            cameras,
            [
                CameraInfo(0, "Muxed camera", (), device_id="a"),
                CameraInfo(None, "OBS", (), "OBS output", "b"),
                CameraInfo(2, "USB camera", (), device_id="c"),
            ],
        )
        self.assertEqual(
            [call.args for call in enumerate_devices.call_args_list],
            [("video",), ("muxed",)],
        )
        for camera in (usb, obs, muxed):
            camera.lockForConfiguration_.assert_not_called()

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
        physical.uniqueID.return_value = "physical"
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
                eligible,
                [
                    CameraInfo(
                        0,
                        "Physical Camera",
                        ("640x480 at 15-30 fps",),
                        device_id="physical",
                    )
                ],
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
                    CameraInfo(None, "OBS", (), "OBS output", "b"),
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
