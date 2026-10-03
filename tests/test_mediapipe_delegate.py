"""Delegate selection never lets a failing native probe take down the app."""

from io import BytesIO
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods import mediapipe_delegate as delegates


class DelegateSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        delegates._CACHE.clear()
        self.frame = np.zeros((8, 12, 3), dtype=np.uint8)
        self.system = patch.object(delegates.platform, "system", return_value="Darwin")
        self.machine = patch.object(delegates.platform, "machine", return_value="arm64")
        self.system.start()
        self.machine.start()
        self.addCleanup(self.system.stop)
        self.addCleanup(self.machine.stop)

    def test_gpu_requires_consistent_five_percent_gain(self) -> None:
        for measurements, expected in (
            ([10, 8, 8, 10, 10, 8], "gpu"),
            ([10, 9.5, 9.5, 10, 10, 9.5], "cpu"),
            ([10, 8, 11, 10, 10, 8], "cpu"),
        ):
            with self.subTest(expected=expected):
                delegates._CACHE.clear()
                with patch.object(
                    delegates, "_probe", side_effect=measurements
                ) as probe:
                    self.assertEqual(
                        delegates.select_delegate("face", self.frame), expected
                    )
                self.assertEqual(
                    [call.args[1] for call in probe.call_args_list],
                    ["cpu", "gpu", "gpu", "cpu", "cpu", "gpu"],
                )
                payloads = [call.args[2] for call in probe.call_args_list]
                self.assertTrue(all(payload == payloads[0] for payload in payloads))
                np.testing.assert_array_equal(
                    np.load(BytesIO(payloads[0]), allow_pickle=False), self.frame
                )

    def test_cache_is_per_task_and_shape(self) -> None:
        with patch.object(delegates, "_probe", return_value=1.0) as probe:
            delegates.select_delegate("face", self.frame)
            delegates.select_delegate("face", self.frame + 1)
            self.assertEqual(probe.call_count, 6)
            delegates.select_delegate("segmentation", self.frame)
            self.assertEqual(probe.call_count, 12)
            delegates.select_delegate("face", self.frame[:4])
            self.assertEqual(probe.call_count, 18)

    def test_other_platforms_skip_probes(self) -> None:
        with patch.object(delegates.platform, "system", return_value="Linux"):
            with patch.object(delegates, "_probe") as probe:
                self.assertEqual(delegates.select_delegate("face", self.frame), "cpu")
                probe.assert_not_called()
        with patch.object(delegates.platform, "machine", return_value="x86_64"):
            with patch.object(delegates, "_probe") as probe:
                self.assertEqual(delegates.select_delegate("face", self.frame), "cpu")
                probe.assert_not_called()

    def test_crash_timeout_and_bad_results_fall_back_and_cache(self) -> None:
        failures = (
            subprocess.CalledProcessError(-6, ["worker"]),
            subprocess.TimeoutExpired(["worker"], 15),
            ValueError("bad timing"),
            OSError("cannot start worker"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                delegates._CACHE.clear()
                with patch.object(delegates, "_probe", side_effect=failure) as probe:
                    self.assertEqual(
                        delegates.select_delegate("face", self.frame), "cpu"
                    )
                    self.assertEqual(
                        delegates.select_delegate("face", self.frame), "cpu"
                    )
                    self.assertEqual(probe.call_count, 1)

    def test_invalid_frames_rejected_before_calibration(self) -> None:
        for frame in (
            np.zeros((0, 2, 3), dtype=np.uint8),
            np.zeros((2, 0, 3), dtype=np.uint8),
            np.zeros((2, 2), dtype=np.uint8),
            np.zeros((2, 2, 4), dtype=np.uint8),
            np.zeros((2, 2, 3), dtype=np.float32),
        ):
            with self.subTest(shape=frame.shape):
                with self.assertRaises(ValueError):
                    delegates.select_delegate("face", frame)

    def test_worker_uses_timeout_and_validates_metrics(self) -> None:
        for output in (
            b'{"median_ms": 2.5}',
            b'{"median_ms": -1}',
            b'{"median_ms": NaN}',
            b'{"median_ms": true}',
            b'{"median_ms": "2.5"}',
            b"{}",
            b"not json",
        ):
            with self.subTest(output=output):
                result = subprocess.CompletedProcess(["worker"], 0, stdout=output)
                with patch.object(
                    delegates.subprocess, "run", return_value=result
                ) as run:
                    if output == b'{"median_ms": 2.5}':
                        self.assertEqual(delegates._probe("face", "gpu", b"input"), 2.5)
                    else:
                        with self.assertRaises((ValueError, KeyError)):
                            delegates._probe("face", "gpu", b"input")
                self.assertEqual(run.call_args.kwargs["timeout"], 15)
                self.assertTrue(run.call_args.kwargs["check"])
                self.assertEqual(run.call_args.kwargs["input"], b"input")


class WorkerMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = np.zeros((4, 5, 3), dtype=np.uint8)
        self.frame[:] = (10, 20, 30)
        self.images: list[np.ndarray] = []
        self.handle = Mock()
        self.mask = Mock()
        self.mask.numpy_view.return_value = np.ones((4, 5, 1), dtype=np.float32)
        self.handle.segment_for_video.return_value = SimpleNamespace(
            confidence_masks=[self.mask]
        )
        base = Mock()
        base.Delegate = SimpleNamespace(CPU="cpu", GPU="gpu")
        self.native = SimpleNamespace(
            Image=self.image,
            ImageFormat=SimpleNamespace(SRGBA="rgba"),
            tasks=SimpleNamespace(
                BaseOptions=base,
                vision=SimpleNamespace(
                    RunningMode=SimpleNamespace(VIDEO="video"),
                    FaceDetector=SimpleNamespace(
                        create_from_options=Mock(return_value=self.handle)
                    ),
                    FaceDetectorOptions=Mock(),
                    ImageSegmenter=SimpleNamespace(
                        create_from_options=Mock(return_value=self.handle)
                    ),
                    ImageSegmenterOptions=Mock(),
                ),
            ),
        )

    def image(self, *, image_format: str, data: np.ndarray) -> object:
        self.assertEqual(image_format, "rgba")
        self.assertTrue(data.flags.c_contiguous)
        self.images.append(data)
        return object()

    def measure(self, task: delegates.Task) -> float:
        with patch.dict(sys.modules, {"mediapipe": self.native}):
            with patch.object(delegates, "model_path", return_value="model.tflite"):
                with patch.object(delegates.time, "monotonic_ns", return_value=0):
                    return delegates._measure(task, "gpu", self.frame)

    def test_face_uses_rgba_monotonic_video_timestamps_and_closes(self) -> None:
        self.assertGreater(self.measure("face"), 0)
        calls = self.handle.detect_for_video.call_args_list
        self.assertEqual(len(calls), 40)
        self.assertEqual([call.args[1] for call in calls], list(range(1, 41)))
        np.testing.assert_array_equal(self.images[0][0, 0], [30, 20, 10, 255])
        self.handle.close.assert_called_once()

    def test_segmentation_reads_mask_on_every_sample_and_closes(self) -> None:
        self.assertGreater(self.measure("segmentation"), 0)
        self.assertEqual(self.mask.numpy_view.call_count, 40)
        self.handle.close.assert_called_once()

    def test_native_prediction_failure_still_closes(self) -> None:
        self.handle.detect_for_video.side_effect = RuntimeError("prediction failed")
        with self.assertRaisesRegex(RuntimeError, "prediction failed"):
            self.measure("face")
        self.handle.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
