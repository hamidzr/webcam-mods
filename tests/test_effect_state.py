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
        first.generate_crop(Rect(w=30, h=30, l=0, t=0), (1, 1))
        moved = first.generate_crop(Rect(w=30, h=30, l=90, t=0), (1, 1))
        independent = second.generate_crop(Rect(w=30, h=30, l=200, t=0), (1, 1))
        self.assertEqual(moved.l, 45)
        self.assertEqual(independent.l, 200)
        first.close()
        second.close()

    def test_interpolation_reaches_target(self) -> None:
        tracker = CropTracker(fps=2)
        tracker.generate_crop(Rect(w=30, h=30, l=0, t=0), (1, 1))
        target = Rect(w=30, h=30, l=90, t=60)
        tracker.generate_crop(target, (1, 1))
        last = tracker.generate_crop(target, (1, 1))
        self.assertEqual((last.l, last.t), (90, 60))
        tracker.generate_crop(target, (1, 1))
        self.assertIsNone(tracker.transition)

    def test_external_rectangle_mutation_does_not_mutate_state(self) -> None:
        tracker = CropTracker()
        prediction = Rect(w=30, h=30, l=10, t=20)
        tracker.generate_crop(prediction, (1, 1))
        prediction.left = 1000
        self.assertEqual(tracker.cur_crop.l, 10)
        self.assertEqual(tracker.last_pred.l, 10)

    def test_close_clears_state(self) -> None:
        tracker = CropTracker()
        tracker.generate_crop(Rect(w=30, h=30), None)
        tracker.close()
        self.assertIsNone(tracker.last_pred)
        self.assertIsNone(tracker.cur_crop)
        self.assertIsNone(tracker.transition)


if __name__ == "__main__":
    unittest.main()
