"""Camera mailbox and native buffer checks without camera permission prompts."""

import importlib.util
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.macos.capture import (
    AVFoundationCamera,
    select_capture_format,
    select_capture_device,
    select_capture_device_by_id,
    capture_frame_duration,
)


class CameraMailboxTest(unittest.TestCase):
    def test_native_rate_rounding_accepts_nominal_fps(self) -> None:
        rate = Mock()
        rate.minFrameRate.return_value = 30.00003000003
        rate.maxFrameRate.return_value = 30.00003000003
        fmt = Mock()
        fmt.videoSupportedFrameRateRanges.return_value = [rate]
        device = Mock()
        device.formats.return_value = [fmt]
        cm = SimpleNamespace(
            CMVideoFormatDescriptionGetDimensions=lambda _: SimpleNamespace(
                width=640, height=480
            )
        )
        self.assertIs(select_capture_format(device, cm, 640, 480, 30, 0), fmt)
        self.assertIs(select_capture_format(device, cm, 640, 480, 29.97, 0), fmt)
        self.assertIs(capture_frame_duration(fmt, cm, 29.97), rate.maxFrameDuration())
        rate.minFrameRate.return_value = rate.maxFrameRate.return_value = 29.97
        self.assertIs(select_capture_format(device, cm, 640, 480, 30, 0), fmt)
        self.assertIs(capture_frame_duration(fmt, cm, 30), rate.minFrameDuration())
        with self.assertRaises(ValueError):
            select_capture_format(device, cm, 640, 480, 15, 0)
        exact = Mock()
        exact_rate = Mock()
        exact_rate.minFrameRate.return_value = exact_rate.maxFrameRate.return_value = 30
        exact.videoSupportedFrameRateRanges.return_value = [exact_rate]
        device.formats.return_value = [fmt, exact]
        self.assertIs(select_capture_format(device, cm, 640, 480, 30, 0), exact)
        cm.CMTimeMake = Mock(return_value="requested duration")
        self.assertEqual(capture_frame_duration(exact, cm, 30), "requested duration")
        cm.CMTimeMake.assert_called_once_with(1000, 30000)

    def test_selected_identity_survives_reordered_devices(self) -> None:
        first, second = Mock(), Mock()
        first.uniqueID.return_value = "first"
        second.uniqueID.return_value = "second"
        first.manufacturer.return_value = second.manufacturer.return_value = "Vendor"
        first.modelID.return_value = second.modelID.return_value = "Camera"
        self.assertIs(select_capture_device_by_id([first, second], "second")[1], second)
        self.assertIs(select_capture_device_by_id([second, first], "second")[1], second)
        with self.assertRaisesRegex(ValueError, "no longer available"):
            select_capture_device_by_id([first], "second")

    def test_native_midstream_size_change_is_rejected(self) -> None:
        camera = AVFoundationCamera(width=1280, height=720)
        camera._running = True
        camera._publish(np.zeros((480, 864, 3), np.uint8), 0)
        with self.assertRaisesRegex(RuntimeError, "1280x720 -> 864x480"):
            camera.frame()
        camera.teardown()

    def test_output_exclusion_survives_reordered_devices(self) -> None:
        physical = Mock()
        physical.manufacturer.return_value = "Camera Vendor"
        physical.modelID.return_value = "USB Camera"
        virtual = Mock()
        virtual.manufacturer.return_value = "OBS Project"
        virtual.modelID.return_value = "OBS Camera Extension"
        for devices, expected in (([physical, virtual], 0), ([virtual, physical], 1)):
            index, selected = select_capture_device(devices, 0)
            self.assertEqual(index, expected)
            self.assertIs(selected, physical)
        with self.assertRaisesRegex(
            ValueError, "no input cameras available after excluding OBS"
        ):
            select_capture_device([virtual], 0)

    def test_other_inputs_are_preserved_and_display_name_is_not_identity(self) -> None:
        first = Mock()
        first.manufacturer.return_value = "Other Camera Vendor"
        first.modelID.return_value = "USB Camera"
        first.localizedName.return_value = "OBS Virtual Camera"
        other_virtual = Mock()
        other_virtual.manufacturer.return_value = "Other Virtual Vendor"
        other_virtual.modelID.return_value = "Other Virtual Model"
        self.assertIs(select_capture_device([first, other_virtual], 0)[1], first)
        self.assertIs(
            select_capture_device([first, other_virtual], 1)[1], other_virtual
        )
        legacy_obs = Mock()
        legacy_obs.manufacturer.return_value = ""
        legacy_obs.modelID.return_value = "OBS Virtual Camera"
        self.assertIs(select_capture_device([legacy_obs, first], 0)[1], first)

    def test_virtual_camera_format_mismatch_is_actionable(self) -> None:
        rate = Mock()
        rate.minFrameRate.return_value = 60.0
        rate.maxFrameRate.return_value = 60.0
        fmt = Mock()
        fmt.videoSupportedFrameRateRanges.return_value = [rate]
        device = Mock()
        device.formats.return_value = [fmt]
        device.localizedName.return_value = "OBS Virtual Camera"
        cm = SimpleNamespace(
            CMVideoFormatDescriptionGetDimensions=lambda _: SimpleNamespace(
                width=1920, height=1080
            )
        )
        with self.assertRaises(ValueError) as error:
            select_capture_format(device, cm, 640, 480, 30, 0)
        message = str(error.exception)
        for fragment in (
            "OBS Virtual Camera",
            "1920x1080",
            "60-60 fps",
            "--input-device",
            "VIDEO_IN",
        ):
            self.assertIn(fragment, message)
        self.assertIs(select_capture_format(device, cm, 1920, 1080, 60, 0), fmt)

    def test_newest_frame_replaces_older_frame(self) -> None:
        camera = AVFoundationCamera(width=3, height=2, timeout=0.01)
        camera._running = True
        older = np.zeros((2, 3, 3), dtype=np.uint8)
        newer = np.ones((2, 3, 3), dtype=np.uint8)
        camera._publish(older, 1.0)
        camera._publish(newer, 2.0)
        self.assertIs(camera.frame(), newer)
        self.assertEqual(camera.timestamp, 2.0)
        with self.assertRaises(TimeoutError):
            camera.frame()
        camera.teardown()
        self.assertIsNone(camera.frame())

    def test_callback_failure_reaches_reader(self) -> None:
        camera = AVFoundationCamera(timeout=0.01)
        camera._running = True
        camera._fail(ValueError("invalid sample"))
        with self.assertRaisesRegex(RuntimeError, "frame capture failed"):
            camera.frame()

    def test_partial_setup_output_is_detached(self) -> None:
        camera = AVFoundationCamera()
        output = Mock()
        camera._output = output
        camera.teardown()
        output.setSampleBufferDelegate_queue_.assert_called_once_with(None, None)
        self.assertIsNone(camera._output)

    def test_owned_device_lock_is_released_once_on_teardown(self) -> None:
        camera = AVFoundationCamera()
        device = Mock()
        camera._locked_device = device
        camera.teardown()
        camera.teardown()
        device.unlockForConfiguration.assert_called_once()
        self.assertIsNone(camera._locked_device)

    def test_stopping_timeout_keeps_device_lock_until_worker_finishes(self) -> None:
        camera = AVFoundationCamera(timeout=0.01)
        device = Mock()
        worker = Mock()
        camera._locked_device = device
        camera._worker = worker
        worker.is_alive.return_value = True
        with self.assertRaises(TimeoutError):
            camera.teardown()
        device.unlockForConfiguration.assert_not_called()
        worker.is_alive.return_value = False
        camera.teardown()
        device.unlockForConfiguration.assert_called_once()

    @unittest.skipUnless(
        sys.platform == "darwin" and importlib.util.find_spec("Quartz") is not None,
        "optional macOS Quartz bindings unavailable",
    )
    def test_native_padded_bgra_buffer_is_copied(self) -> None:
        import Quartz as q

        width, height = 7, 3
        status, pixel = q.CVPixelBufferCreate(
            None, width, height, q.kCVPixelFormatType_32BGRA, None, None
        )
        self.assertEqual(status, 0)
        q.CVPixelBufferLockBaseAddress(pixel, 0)
        try:
            stride = q.CVPixelBufferGetBytesPerRow(pixel)
            memory = q.CVPixelBufferGetBaseAddress(pixel).as_buffer(height * stride)
            rows = np.frombuffer(memory, dtype=np.uint8).reshape(height, stride)
            rows[:] = 222
            rows[:, : width * 4].reshape(height, width, 4)[:] = [10, 50, 200, 255]
        finally:
            q.CVPixelBufferUnlockBaseAddress(pixel, 0)
        camera = AVFoundationCamera(width=width, height=height)
        camera._running = True
        cm = SimpleNamespace(
            CMSampleBufferGetImageBuffer=lambda _: pixel,
            CMSampleBufferGetPresentationTimeStamp=lambda _: 4.5,
            CMTimeGetSeconds=lambda value: value,
        )
        camera._receive(object(), cm, q)
        frame = camera.frame()
        self.assertEqual(frame.shape, (height, width, 3))
        self.assertEqual(camera.timestamp, 4.5)
        q.CVPixelBufferLockBaseAddress(pixel, 0)
        try:
            rows[:] = 0
        finally:
            q.CVPixelBufferUnlockBaseAddress(pixel, 0)
        np.testing.assert_array_equal(
            frame, np.broadcast_to([10, 50, 200], frame.shape)
        )

    @unittest.skipUnless(
        sys.platform == "darwin"
        and importlib.util.find_spec("AVFoundation") is not None,
        "optional macOS AVFoundation bindings unavailable",
    )
    def test_mocked_device_setup_can_repeat_without_camera_access(self) -> None:
        import AVFoundation as av
        import CoreMedia as cm

        camera = AVFoundationCamera(
            width=7, height=3, fps=30, timeout=0.2, device_id="target"
        )
        device = Mock()
        device.uniqueID.return_value = "target"
        fmt = Mock()
        rate = Mock()
        rate.minFrameRate.return_value = 1
        rate.maxFrameRate.return_value = 60
        fmt.videoSupportedFrameRateRanges.return_value = [rate]
        device.formats.return_value = [fmt]
        lock_state = {"held": False}

        def lock_device(_):
            lock_state["held"] = True
            return True, None

        def unlock_device():
            self.assertTrue(lock_state["held"])
            lock_state["held"] = False

        device.lockForConfiguration_.side_effect = lock_device
        device.unlockForConfiguration.side_effect = unlock_device
        device.activeVideoMinFrameDuration.return_value = cm.CMTimeMake(1, 30)
        session = Mock()
        # macOS rejects inputPriority even though the binding exposes it
        session.canSetSessionPreset_.return_value = False

        def configure_format(selected):
            self.assertTrue(
                session.addInput_.called, "attach camera before format selection"
            )
            self.assertTrue(
                session.addOutput_.called, "attach output before format selection"
            )
            self.assertIs(selected, fmt)

        device.setActiveFormat_.side_effect = configure_format

        def commit_configuration():
            self.assertTrue(
                lock_state["held"], "macOS format must stay locked through commit"
            )

        def start_running():
            self.assertTrue(
                lock_state["held"], "macOS format must stay locked through start"
            )
            camera._publish(np.zeros((3, 7, 3), dtype=np.uint8), 0.0)

        session.stopRunning.side_effect = lambda: self.assertTrue(lock_state["held"])
        session.commitConfiguration.side_effect = commit_configuration
        session.startRunning.side_effect = start_running
        session.canAddInput_.return_value = True
        session.canAddOutput_.return_value = True
        sessions = Mock()
        sessions.alloc.return_value.init.return_value = session
        outputs = Mock()
        output = Mock()
        outputs.alloc.return_value.init.return_value = output
        devices = Mock()
        devices.authorizationStatusForMediaType_.return_value = (
            av.AVAuthorizationStatusAuthorized
        )
        devices.devicesWithMediaType_.return_value = [device]
        inputs = Mock()
        inputs.deviceInputWithDevice_error_.return_value = (Mock(), None)
        with (
            patch.object(av, "AVCaptureDevice", devices),
            patch.object(av, "AVCaptureSession", sessions),
            patch.object(av, "AVCaptureVideoDataOutput", outputs),
            patch.object(av, "AVCaptureDeviceInput", inputs),
            patch.object(
                cm,
                "CMVideoFormatDescriptionGetDimensions",
                return_value=SimpleNamespace(width=7, height=3),
            ),
        ):
            obs = Mock()
            obs.manufacturer.return_value = "OBS Project"
            obs.uniqueID.return_value = "obs"
            other = Mock()
            other.uniqueID.return_value = "other"
            for i in range(2):
                negotiated_fps = 30.0 if i == 0 else 29.97
                device.activeVideoMinFrameDuration.return_value = cm.CMTimeMake(
                    1000, round(negotiated_fps * 1000)
                )
                devices.devicesWithMediaType_.return_value = (
                    [device, obs, other] if i == 0 else [other, obs, device]
                )
                metadata = camera.setup()
                self.assertEqual((metadata["width"], metadata["height"]), (7, 3))
                self.assertAlmostEqual(metadata["fps"], negotiated_fps)
                self.assertTrue(camera.is_setup())
                self.assertTrue(lock_state["held"])
                self.assertEqual(camera.frame().shape, (3, 7, 3))
                camera.teardown()
                self.assertFalse(camera.is_setup())
                self.assertFalse(lock_state["held"])
            camera.fps = 30
            session.startRunning.side_effect = RuntimeError("native startup failure")
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                camera.setup()
            self.assertIsNone(camera._session)
            self.assertFalse(camera.is_setup())
            device.setActiveFormat_.side_effect = RuntimeError("format rejected")
            with self.assertRaisesRegex(RuntimeError, "format rejected"):
                camera.setup()
            self.assertIsNone(camera._session)
            self.assertIsNone(camera._output)
            self.assertFalse(camera.is_setup())
            device.setActiveFormat_.side_effect = configure_format
            session.startRunning.side_effect = start_running
            device.activeVideoMinFrameDuration.return_value = cm.CMTimeMake(1, 15)
            with self.assertRaisesRegex(RuntimeError, "returned 15 FPS; requested 30"):
                camera.setup()
            self.assertIsNone(camera._locked_device)
            device.activeVideoMinFrameDuration.return_value = cm.CMTimeMake(1, 30)
            session.startRunning.side_effect = lambda: camera._publish(
                np.zeros((24, 32, 3), dtype=np.uint8), 0.0
            )
            with self.assertRaisesRegex(
                RuntimeError, "camera returned 32x24; requested 7x3"
            ):
                camera.setup()
            self.assertFalse(lock_state["held"])
            self.assertIsNone(camera._locked_device)
        self.assertEqual(session.stopRunning.call_count, 5)
        self.assertEqual(device.unlockForConfiguration.call_count, 6)
        session.canSetSessionPreset_.assert_not_called()
        session.setSessionPreset_.assert_not_called()
        self.assertEqual(session.beginConfiguration.call_count, 6)
        self.assertEqual(session.commitConfiguration.call_count, 6)


if __name__ == "__main__":
    unittest.main()
