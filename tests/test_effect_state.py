"""Per-run face detection and crop interpolation state regression checks."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from webcam_mods.geometry import Rect
from webcam_mods.mods.camera_motion import CropTracker
from webcam_mods.mods.mp_face import FaceDetector


class FaceDetectorStateTest(unittest.TestCase):
    def test_creation_is_lazy(self) -> None:
        with patch("webcam_mods.mods.mp_face.model_path") as lookup:
            detector = FaceDetector()
            lookup.assert_not_called()
            detector.close()
            lookup.assert_not_called()

    def test_instances_own_monotonic_timestamps(self) -> None:
        first, second = FaceDetector(), FaceDetector()
        for instance in (first, second):
            instance._detector = MagicMock()
            instance._detector.detect_for_video.return_value = SimpleNamespace(
                detections=[]
            )
        frame = np.zeros((2, 2, 3), np.uint8)
        with patch(
            "webcam_mods.mods.mp_face.time.monotonic_ns", return_value=1_000_000
        ):
            first.predict(frame)
            first.predict(frame)
            second.predict(frame)
        self.assertEqual(first._last_timestamp_ms, 2)
        self.assertEqual(second._last_timestamp_ms, 1)
        first.close()
        second.close()

    def test_auto_delegate_uses_rgba_and_reselects_on_size_change(self) -> None:
        detector = FaceDetector()
        native = MagicMock()
        native.detect_for_video.return_value = SimpleNamespace(detections=[])
        with (
            patch(
                "webcam_mods.mods.mp_face.select_delegate", return_value="gpu"
            ) as select,
            patch("webcam_mods.mods.mp_face.model_path", return_value="model.tflite"),
            patch(
                "webcam_mods.mods.mp_face.MediaPipeFaceDetector.create_from_options",
                return_value=native,
            ) as create,
        ):
            detector.predict(np.zeros((4, 5, 3), np.uint8))
            detector.predict(np.zeros((4, 5, 3), np.uint8))
            self.assertEqual(select.call_count, 1)
            self.assertEqual(
                native.detect_for_video.call_args.args[0].numpy_view().shape, (4, 5, 4)
            )
            self.assertEqual(create.call_args.args[0].base_options.delegate.name, "GPU")
            detector.predict(np.zeros((6, 7, 3), np.uint8))
            self.assertEqual(select.call_count, 2)
            native.close.assert_called_once()
            detector.close()

    def test_explicit_init_still_calibrates_first_prediction(self) -> None:
        detector = FaceDetector()
        native = MagicMock()
        native.detect_for_video.return_value = SimpleNamespace(detections=[])
        with (
            patch(
                "webcam_mods.mods.mp_face.select_delegate", return_value="gpu"
            ) as select,
            patch("webcam_mods.mods.mp_face.model_path", return_value="model.tflite"),
            patch(
                "webcam_mods.mods.mp_face.MediaPipeFaceDetector.create_from_options",
                return_value=native,
            ),
        ):
            detector.init()
            select.assert_not_called()
            detector.predict(np.zeros((4, 5, 3), np.uint8))
            select.assert_called_once()
            self.assertEqual(detector._delegate, "gpu")
            native.close.assert_called_once()
            detector.close()

    def test_failed_gpu_initialization_retries_cpu(self) -> None:
        detector = FaceDetector()
        native = MagicMock()
        native.detect_for_video.return_value = SimpleNamespace(detections=[])
        with (
            patch("webcam_mods.mods.mp_face.select_delegate", return_value="gpu"),
            patch("webcam_mods.mods.mp_face.model_path", return_value="model.tflite"),
            patch(
                "webcam_mods.mods.mp_face.MediaPipeFaceDetector.create_from_options",
                side_effect=[RuntimeError("GPU unavailable"), native],
            ) as create,
        ):
            detector.predict(np.zeros((4, 5, 3), np.uint8))
            self.assertEqual(create.call_count, 2)
            self.assertEqual(create.call_args.args[0].base_options.delegate.name, "CPU")
            self.assertEqual(detector._delegate, "cpu")
            detector.close()

    def test_close_is_idempotent_and_prevents_reopen(self) -> None:
        detector = FaceDetector()
        native = MagicMock()
        detector._detector = native
        detector.close()
        detector.close()
        native.close.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            detector.predict(np.zeros((2, 2, 3), np.uint8))

    def test_close_failure_drops_reference(self) -> None:
        detector = FaceDetector()
        native = MagicMock()
        native.close.side_effect = RuntimeError("native close failed")
        detector._detector = native
        with self.assertRaisesRegex(RuntimeError, "native close failed"):
            detector.close()
        self.assertIsNone(detector._detector)
        detector.close()


class CropTrackerStateTest(unittest.TestCase):
    def test_instances_do_not_share_crop(self) -> None:
        first, second = CropTracker(fps=2), CropTracker(fps=2)
        first.generate_crop(
            Rect(w=100, h=100, l=100, t=100), frame_size=(640, 480), now=0
        )
        moved = first.generate_crop(
            Rect(w=100, h=100, l=200, t=100), frame_size=(640, 480), now=1
        )
        self.assertGreater(moved.l, 0)
        self.assertIsNone(second.cur_crop)
        first.close()
        second.close()

    def test_external_rectangle_mutation_does_not_mutate_state(self) -> None:
        tracker = CropTracker()
        prediction = Rect(w=100, h=100, l=200, t=100)
        initial = tracker.generate_crop(prediction, frame_size=(640, 480), now=0)
        prediction.left = 1000
        initial.left = 1000
        self.assertNotEqual(tracker.cur_crop.l, 1000)
        self.assertEqual(tracker._focus, (250, 150))

    def test_close_clears_state(self) -> None:
        tracker = CropTracker()
        tracker.generate_crop(Rect(w=30, h=30), frame_size=(640, 480), now=0)
        tracker.close()
        self.assertIsNone(tracker.cur_crop)
        self.assertIsNone(tracker._focus)
        self.assertIsNone(tracker._seen_at)
