"""Capture ownership, validation and control lifecycle regressions."""

from types import SimpleNamespace
from threading import Event, Thread
import sys
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from webcam_mods.input.input import FrameInput
from webcam_mods.input.video_dev import Webcam
from webcam_mods.mods.mp_face import FaceDetector
from webcam_mods.mods.person_segmentation import MediaPipeSegmenter, PersonEffects
from webcam_mods.session import Command, RunSession
from webcam_mods.settings import StartupSettings
from webcam_mods.uses.interactive_controls import KeyboardControls
from webcam_mods.utils.config import Config


def capture() -> Mock:
    handle = Mock()
    handle.isOpened.return_value = True
    handle.read.return_value = True, np.full((4, 6, 3), 42, np.uint8)
    handle.get.side_effect = {
        cv2.CAP_PROP_FRAME_WIDTH: 6,
        cv2.CAP_PROP_FRAME_HEIGHT: 4,
        cv2.CAP_PROP_FPS: 30,
    }.__getitem__
    return handle


class AdditionalImprovementTests(unittest.TestCase):
    def camera(self) -> Webcam:
        return Webcam(settings=StartupSettings(in_width=6, in_height=4))

    def test_camera_setup_reuses_handle_and_preserves_first_frame(self) -> None:
        camera, handle = self.camera(), capture()
        with patch(
            "webcam_mods.input.video_dev.cv2.VideoCapture", return_value=handle
        ) as create:
            try:
                first = camera.setup()
                self.assertEqual(camera.setup(), first)
                create.assert_called_once()
                handle.read.assert_called_once()
                np.testing.assert_array_equal(camera.frame(), 42)
            finally:
                camera.teardown()
        handle.release.assert_called_once()

    def test_release_failure_does_not_retain_camera_handle(self) -> None:
        camera, handle = self.camera(), capture()
        camera.cap = handle
        handle.release.side_effect = OSError("release failed")
        with self.assertRaisesRegex(OSError, "release failed"):
            camera.teardown()
        self.assertIsNone(camera.cap)
        camera.teardown()
        handle.release.assert_called_once()
        self.assertIsNone(camera.frame())

    def test_failed_camera_attempts_wait_only_between_retries(self) -> None:
        camera = self.camera()
        with (
            patch(
                "webcam_mods.input.video_dev.open_video_capture", return_value=None
            ) as open_capture,
            patch.object(camera._stop, "wait", return_value=False) as wait,
        ):
            with self.assertRaises(FileNotFoundError):
                camera.setup()
        self.assertEqual(open_capture.call_count, 5)
        self.assertEqual(wait.call_count, 4)

    def test_camera_retry_wait_is_cancellable_and_can_restart(self) -> None:
        camera = self.camera()
        attempted = Event()
        errors = []

        def fail(**kwargs):
            attempted.set()
            return None

        def setup():
            try:
                camera.setup()
            except RuntimeError as error:
                errors.append(error)

        with patch("webcam_mods.input.video_dev.open_video_capture", fail):
            thread = Thread(target=setup, daemon=True)
            thread.start()
            try:
                self.assertTrue(attempted.wait(1))
                camera.request_stop()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIn("cancelled", str(errors[0]))
            finally:
                camera.request_stop()
                thread.join(3)
        handle = capture()
        with patch("webcam_mods.input.video_dev.cv2.VideoCapture", return_value=handle):
            camera.setup()
        camera.teardown()
        handle.release.assert_called_once()

    def test_disconnected_camera_handle_is_released_before_reopen(self) -> None:
        camera, old, replacement = self.camera(), capture(), capture()
        old.isOpened.return_value = False
        camera.cap = old
        with patch(
            "webcam_mods.input.video_dev.cv2.VideoCapture", return_value=replacement
        ):
            camera.setup()
        old.release.assert_called_once()
        self.assertIs(camera.cap, replacement)
        camera.teardown()

    def test_camera_rejects_wrong_dtype_during_startup(self) -> None:
        camera, handle = self.camera(), capture()
        handle.read.return_value = True, np.zeros((4, 6, 3), np.float32)
        with patch("webcam_mods.input.video_dev.cv2.VideoCapture", return_value=handle):
            try:
                with self.assertRaisesRegex(ValueError, "uint8"):
                    camera.setup()
                self.assertIsNone(camera.cap)
            finally:
                camera.teardown()
        handle.release.assert_called_once()

    def test_invalid_inference_frames_rejected_before_initialization(self) -> None:
        invalid = (
            None,
            np.zeros((3, 4, 3), np.float32),
            np.zeros((3, 4), np.uint8),
            np.zeros((0, 4, 3), np.uint8),
        )
        for instance in (FaceDetector(), MediaPipeSegmenter(), PersonEffects()):
            method = (
                instance.mask
                if isinstance(instance, PersonEffects)
                else instance.predict
            )
            with (
                patch(
                    "webcam_mods.mods.mp_face.select_delegate",
                    side_effect=AssertionError("initialized"),
                ),
                patch(
                    "webcam_mods.mods.person_segmentation.select_delegate",
                    side_effect=AssertionError("initialized"),
                ),
            ):
                for frame in invalid:
                    with self.subTest(
                        instance=type(instance).__name__,
                        shape=getattr(frame, "shape", None),
                    ):
                        with self.assertRaisesRegex(ValueError, "BGR"):
                            method(frame)
            instance.close()

    def test_invalid_colors_rejected_before_inference(self) -> None:
        effects = PersonEffects()
        with patch.object(effects, "mask", side_effect=AssertionError("inference ran")):
            for color in ((0, 1), (0, 1, 2, 3), float("nan"), (0, 0, 256), -1):
                with self.subTest(color=color), self.assertRaises(ValueError):
                    effects.color_bg(np.zeros((4, 6, 3), np.uint8), color)
        effects.close()

    def test_invalid_background_preserves_previous_snapshot(self) -> None:
        effects = PersonEffects()
        effects.set_background(np.full((4, 6, 3), 42, np.uint8))
        for background in (
            np.zeros((4, 6), np.uint8),
            np.zeros((4, 6, 3), np.float32),
            np.zeros((0, 6, 3), np.uint8),
        ):
            with self.assertRaisesRegex(ValueError, "BGR"):
                effects.set_background(background)
            np.testing.assert_array_equal(effects._background_source, 42)
        effects.close()

    def test_config_rejects_invalid_dimensions_without_reading_disk(self) -> None:
        with patch.object(Config, "load", side_effect=AssertionError("read disk")):
            for width, height in ((0, 4), (6, -1), (True, 4), (6, 2.5)):
                with (
                    self.subTest(width=width, height=height),
                    self.assertRaises(ValueError),
                ):
                    Config(width=width, height=height)

    def test_closed_session_rejects_processing_and_commands(self) -> None:
        session = RunSession(Config(path=None, width=6, height=4))
        session.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            session.prepare(np.zeros((4, 6, 3), np.uint8))
        self.assertFalse(session.submit(Command("record")))
        self.assertEqual(session.apply_commands(), [])
        self.assertEqual(session.recorder.frames, [])

    def test_keyboard_start_is_idempotent(self) -> None:
        controls = KeyboardControls(RunSession(Config(path=None)))
        listener = Mock(ident=1)
        keys = SimpleNamespace(right="right", left="left", up="up", down="down")
        factory = Mock(return_value=listener)
        with patch.dict(
            sys.modules,
            {"pynput.keyboard": SimpleNamespace(Key=keys, Listener=factory)},
        ):
            controls.start()
            controls.start()
            factory.assert_called_once()
            controls.stop()
        listener.stop.assert_called_once()

    def test_keyboard_stop_failure_clears_state(self) -> None:
        controls = KeyboardControls(RunSession(Config(path=None)))
        listener = Mock(ident=1)
        listener.stop.side_effect = OSError("stop failed")
        controls.listener = listener
        controls.keys.add("ctrl")
        with self.assertRaisesRegex(OSError, "stop failed"):
            controls.stop()
        self.assertIsNone(controls.listener)
        self.assertEqual(controls.keys, set())
        listener.join.assert_called_once_with(timeout=1)
        controls.stop()

    def test_keyboard_start_failure_can_retry(self) -> None:
        controls = KeyboardControls(RunSession(Config(path=None)))
        failed, replacement = Mock(ident=None), Mock(ident=1)
        failed.start.side_effect = OSError("keyboard failed")
        factory = Mock(side_effect=[failed, replacement])
        with patch.dict(
            sys.modules,
            {"pynput.keyboard": SimpleNamespace(Key=object(), Listener=factory)},
        ):
            with self.assertRaisesRegex(OSError, "keyboard failed"):
                controls.start()
            self.assertIsNone(controls.listener)
            controls.start()
            self.assertIs(controls.listener, replacement)
            controls.stop()
        failed.stop.assert_called_once()
        failed.join.assert_not_called()

    def test_demo_setup_failure_still_releases_capture(self) -> None:
        source = Mock(spec=FrameInput)
        source.setup.side_effect = OSError("setup failed")
        with patch("webcam_mods.input.input.cv2.destroyWindow"):
            with self.assertRaisesRegex(OSError, "setup failed"):
                FrameInput.demo(source)
        source.teardown.assert_called_once()

    def test_demo_failure_releases_capture_and_window(self) -> None:
        source = Mock(spec=FrameInput)
        source.frames.return_value = iter([np.zeros((4, 6, 3), np.uint8)])
        with (
            patch(
                "webcam_mods.input.input.cv2.imshow",
                side_effect=OSError("window failed"),
            ),
            patch("webcam_mods.input.input.cv2.destroyWindow") as destroy,
        ):
            with self.assertRaisesRegex(OSError, "window failed"):
                FrameInput.demo(source)
        source.teardown.assert_called_once()
        destroy.assert_called_once_with("screen")
