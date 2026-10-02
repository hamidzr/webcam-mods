"""Camera mailbox and native buffer checks without camera permission prompts."""

import importlib.util
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.macos.capture import AVFoundationCamera, select_capture_format


class CameraMailboxTest(unittest.TestCase):
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
        camera = AVFoundationCamera(timeout=0.01)
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
        camera = AVFoundationCamera()
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

        camera = AVFoundationCamera(width=7, height=3, fps=30, timeout=0.2)
        device = Mock()
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
            for _ in range(2):
                metadata = camera.setup()
                self.assertEqual(metadata, {"width": 7, "height": 3, "fps": 30.0})
                self.assertTrue(camera.is_setup())
                self.assertTrue(lock_state["held"])
                self.assertEqual(camera.frame().shape, (3, 7, 3))
                camera.teardown()
                self.assertFalse(camera.is_setup())
                self.assertFalse(lock_state["held"])
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
            session.startRunning.side_effect = lambda: camera._publish(
                np.zeros((24, 32, 3), dtype=np.uint8), 0.0
            )
            with self.assertRaisesRegex(
                RuntimeError, "camera returned 32x24; requested 7x3"
            ):
                camera.setup()
            self.assertFalse(lock_state["held"])
            self.assertIsNone(camera._locked_device)
        self.assertEqual(session.stopRunning.call_count, 4)
        self.assertEqual(device.unlockForConfiguration.call_count, 5)
        session.canSetSessionPreset_.assert_not_called()
        session.setSessionPreset_.assert_not_called()
        self.assertEqual(session.beginConfiguration.call_count, 5)
        self.assertEqual(session.commitConfiguration.call_count, 5)


if __name__ == "__main__":
    unittest.main()
