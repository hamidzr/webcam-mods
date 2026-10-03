"""Auto capture preserves camera identity and explicit backend choices."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from webcam_mods.capture import (
    NATIVE_MODULES,
    create_camera,
    opencv_device_id,
    resolve_backend,
)
from webcam_mods.settings import StartupSettings


def camera(identity: str, *, obs: bool = False) -> Mock:
    device = Mock()
    device.uniqueID.return_value = identity
    device.manufacturer.return_value = "OBS Project" if obs else "Camera Vendor"
    device.modelID.return_value = "OBS Camera Extension" if obs else "USB Camera"
    return device


def foundation(videos: list[Mock], muxed: list[Mock]) -> SimpleNamespace:
    return SimpleNamespace(
        AVMediaTypeVideo="video",
        AVMediaTypeMuxed="muxed",
        AVCaptureDevice=SimpleNamespace(
            devicesWithMediaType_=lambda media: videos if media == "video" else muxed
        ),
    )


class BackendResolutionTests(unittest.TestCase):
    def test_auto_prefers_native_on_mac_with_complete_bindings(self) -> None:
        with (
            patch("webcam_mods.capture.sys.platform", "darwin"),
            patch(
                "webcam_mods.capture.importlib.util.find_spec", return_value=object()
            ) as spec,
        ):
            self.assertEqual(resolve_backend(), "avfoundation")
        self.assertEqual(
            {call.args[0] for call in spec.call_args_list}, set(NATIVE_MODULES)
        )

    def test_auto_uses_opencv_on_other_platforms_without_probing_bindings(self) -> None:
        for platform in ("linux", "win32"):
            with (
                self.subTest(platform=platform),
                patch("webcam_mods.capture.sys.platform", platform),
                patch("webcam_mods.capture.importlib.util.find_spec") as spec,
            ):
                self.assertEqual(resolve_backend(), "opencv")
                spec.assert_not_called()

    def test_each_missing_binding_causes_auto_fallback_with_warning(self) -> None:
        for missing in NATIVE_MODULES:
            with (
                self.subTest(missing=missing),
                patch("webcam_mods.capture.sys.platform", "darwin"),
                patch(
                    "webcam_mods.capture.importlib.util.find_spec",
                    side_effect=lambda name: None if name == missing else object(),
                ),
                patch("webcam_mods.capture.logger.warning") as warning,
            ):
                self.assertEqual(resolve_backend(), "opencv")
                warning.assert_called_once()

    def test_explicit_opencv_is_preserved_without_dependency_probe(self) -> None:
        with (
            patch("webcam_mods.capture.sys.platform", "darwin"),
            patch("webcam_mods.capture.importlib.util.find_spec") as spec,
            patch("webcam_mods.capture.logger.warning") as warning,
        ):
            self.assertEqual(resolve_backend("opencv"), "opencv")
            spec.assert_not_called()
            warning.assert_not_called()

    def test_explicit_native_never_falls_back(self) -> None:
        with patch("webcam_mods.capture.sys.platform", "linux"):
            with self.assertRaisesRegex(ValueError, "requires macOS"):
                resolve_backend("avfoundation")
        with (
            patch("webcam_mods.capture.sys.platform", "darwin"),
            patch("webcam_mods.capture.importlib.util.find_spec", return_value=None),
            patch("webcam_mods.capture.logger.warning") as warning,
        ):
            with self.assertRaisesRegex(ValueError, "extra macos"):
                resolve_backend("avfoundation")
            warning.assert_not_called()


class CameraIdentityTests(unittest.TestCase):
    def test_opencv_order_includes_obs_and_muxed_then_sorts_ids(self) -> None:
        first, second = camera("b"), camera("d")
        obs, muxed = camera("a", obs=True), camera("c")
        for videos in ([second, obs, first], [first, second, obs]):
            with (
                self.subTest(order=videos),
                patch.dict(
                    "sys.modules", {"AVFoundation": foundation(videos, [muxed])}
                ),
            ):
                self.assertEqual(opencv_device_id(1), "b")
                self.assertEqual(opencv_device_id(3), "d")
                with self.assertRaisesRegex(ValueError, "OBS output"):
                    opencv_device_id(0)
                with self.assertRaisesRegex(ValueError, "not a native video input"):
                    opencv_device_id(2)
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    opencv_device_id(4)

    def test_auto_native_passes_mapped_identity_and_requested_settings(self) -> None:
        settings = StartupSettings(video_in=1, in_width=1280, in_height=720, in_fps=15)
        with (
            patch("webcam_mods.capture.resolve_backend", return_value="avfoundation"),
            patch(
                "webcam_mods.capture.opencv_device_id", return_value="selected"
            ) as identity,
            patch("webcam_mods.macos.capture.AVFoundationCamera") as native,
            patch("webcam_mods.input.video_dev.Webcam") as opencv,
        ):
            self.assertIs(create_camera(settings), native.return_value)
            identity.assert_called_once_with(1)
            native.assert_called_once_with(
                device_index=1,
                device_id="selected",
                width=1280,
                height=720,
                fps=15,
                device=settings.video_out,
            )
            opencv.assert_not_called()

    def test_explicit_native_uses_its_filtered_index_without_mapping(self) -> None:
        settings = StartupSettings(video_in=2)
        with (
            patch("webcam_mods.capture.resolve_backend", return_value="avfoundation"),
            patch("webcam_mods.capture.opencv_device_id") as identity,
            patch("webcam_mods.macos.capture.AVFoundationCamera") as native,
        ):
            create_camera(settings, "avfoundation")
            identity.assert_not_called()
            native.assert_called_once_with(
                device_index=2, width=640, height=480, fps=30, device=settings.video_out
            )

    def test_opencv_receives_original_settings(self) -> None:
        settings = StartupSettings(video_in=2)
        with (
            patch("webcam_mods.capture.resolve_backend", return_value="opencv"),
            patch("webcam_mods.input.video_dev.Webcam") as opencv,
            patch("webcam_mods.capture.opencv_device_id") as identity,
        ):
            self.assertIs(create_camera(settings, "opencv"), opencv.return_value)
            opencv.assert_called_once_with(settings=settings)
            identity.assert_not_called()

    def test_missing_target_propagates_without_substitution(self) -> None:
        with (
            patch("webcam_mods.capture.resolve_backend", return_value="avfoundation"),
            patch(
                "webcam_mods.capture.opencv_device_id",
                side_effect=ValueError("unavailable"),
            ),
            patch("webcam_mods.macos.capture.AVFoundationCamera") as native,
            patch("webcam_mods.input.video_dev.Webcam") as opencv,
        ):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                create_camera(StartupSettings())
            native.assert_not_called()
            opencv.assert_not_called()

    def test_native_constructor_failure_does_not_fall_back(self) -> None:
        with (
            patch("webcam_mods.capture.resolve_backend", return_value="avfoundation"),
            patch("webcam_mods.capture.opencv_device_id", return_value="selected"),
            patch(
                "webcam_mods.macos.capture.AVFoundationCamera",
                side_effect=RuntimeError("native failure"),
            ),
            patch("webcam_mods.input.video_dev.Webcam") as opencv,
        ):
            with self.assertRaisesRegex(RuntimeError, "native failure"):
                create_camera(StartupSettings())
            opencv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
