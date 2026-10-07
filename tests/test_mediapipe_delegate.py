"""Delegate selection never lets a failing native probe take down the app."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import time
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods import mediapipe_delegate as delegates


class DelegateSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        delegates._CACHE.clear()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache_path = Path(temporary.name) / "delegate.json"
        cache_path = patch.object(
            delegates, "_cache_path", return_value=self.cache_path
        )
        identity = patch.object(delegates, "_cache_identity", return_value="identity")
        cache_path.start()
        identity.start()
        self.addCleanup(cache_path.stop)
        self.addCleanup(identity.stop)
        self.frame = np.zeros((8, 12, 3), dtype=np.uint8)
        self.system = patch.object(delegates.platform, "system", return_value="Darwin")
        self.machine = patch.object(delegates.platform, "machine", return_value="arm64")
        self.system.start()
        self.machine.start()
        self.addCleanup(self.system.stop)
        self.addCleanup(self.machine.stop)

    def test_gpu_requires_consistent_five_percent_gain(self) -> None:
        for cpu, gpu, expected in (
            ([10, 10, 10], [8, 8, 8], "gpu"),
            ([10, 10, 10], [9.5, 9.5, 9.5], "cpu"),
            ([10, 10, 10], [8, 11, 8], "cpu"),
        ):
            with self.subTest(expected=expected):
                delegates._CACHE.clear()
                self.cache_path.unlink(missing_ok=True)
                with patch.object(
                    delegates, "_calibrate", return_value=(cpu, gpu)
                ) as calibrate:
                    self.assertEqual(
                        delegates.select_delegate("face", self.frame), expected
                    )
                calibrate.assert_called_once()
                self.assertEqual(calibrate.call_args.args[0], "face")
                np.testing.assert_array_equal(calibrate.call_args.args[1], self.frame)

    def test_cache_is_per_task_and_shape(self) -> None:
        with patch.object(
            delegates, "_calibrate", return_value=([1.0] * 3, [1.0] * 3)
        ) as probe:
            delegates.select_delegate("face", self.frame)
            delegates.select_delegate("face", self.frame + 1)
            self.assertEqual(probe.call_count, 1)
            delegates.select_delegate("segmentation", self.frame)
            self.assertEqual(probe.call_count, 2)
            delegates.select_delegate("face", self.frame[:4])
            self.assertEqual(probe.call_count, 3)

    def test_persistent_cache_skips_probes_after_memory_cache_reset(self) -> None:
        with patch.object(delegates, "_calibrate", return_value=([10] * 3, [8] * 3)):
            self.assertEqual(delegates.select_delegate("face", self.frame), "gpu")
        delegates._CACHE.clear()
        with patch.object(delegates, "_calibrate") as probe:
            self.assertEqual(delegates.select_delegate("face", self.frame), "gpu")
            probe.assert_not_called()

    def test_identity_and_expired_entries_require_new_calibration(self) -> None:
        for identity, timestamp in (("old-runtime", time.time()), ("identity", 0)):
            with self.subTest(identity=identity):
                delegates._CACHE.clear()
                self.cache_path.write_text(
                    json.dumps(
                        {
                            "identity": identity,
                            "entries": {
                                "face:8,12,3": {
                                    "delegate": "gpu",
                                    "timestamp": timestamp,
                                }
                            },
                        }
                    )
                )
                with patch.object(
                    delegates, "_calibrate", return_value=([1.0] * 3, [1.0] * 3)
                ) as probe:
                    self.assertEqual(
                        delegates.select_delegate("face", self.frame), "cpu"
                    )
                    self.assertEqual(probe.call_count, 1)

    def test_corrupt_or_oversized_cache_does_not_break_calibration(self) -> None:
        for payload in ("broken", "[]", "x" * (delegates._CACHE_MAX_BYTES + 1)):
            with self.subTest(size=len(payload)):
                delegates._CACHE.clear()
                self.cache_path.write_text(payload)
                with patch.object(
                    delegates, "_calibrate", return_value=([1.0] * 3, [1.0] * 3)
                ) as probe:
                    self.assertEqual(
                        delegates.select_delegate("face", self.frame), "cpu"
                    )
                    self.assertEqual(probe.call_count, 1)

    def test_unwritable_cache_does_not_break_calibration(self) -> None:
        with patch.object(delegates.os, "replace", side_effect=OSError("read only")):
            with patch.object(
                delegates, "_calibrate", return_value=([1.0] * 3, [1.0] * 3)
            ):
                self.assertEqual(delegates.select_delegate("face", self.frame), "cpu")
        self.assertFalse(self.cache_path.exists())
        self.assertEqual(list(self.cache_path.parent.iterdir()), [])

    def test_cache_evicts_oldest_entries(self) -> None:
        with patch.object(delegates, "_CACHE_LIMIT", 2):
            for index in range(3):
                delegates._write_cache("identity", f"face:{index},12,3", "cpu")
                delegates._remember(("face", (index, 12, 3)), "cpu")
            self.assertEqual(len(delegates._CACHE), 2)
            entries = delegates._read_cache("identity")
            self.assertEqual(set(entries), {"face:1,12,3", "face:2,12,3"})

    def test_failed_probe_is_not_persisted(self) -> None:
        with patch.object(delegates, "_calibrate", side_effect=OSError("failed")):
            self.assertEqual(delegates.select_delegate("face", self.frame), "cpu")
        self.assertFalse(self.cache_path.exists())

    def test_other_platforms_skip_probes(self) -> None:
        with patch.object(delegates.platform, "system", return_value="Linux"):
            with patch.object(delegates, "_calibrate") as probe:
                self.assertEqual(delegates.select_delegate("face", self.frame), "cpu")
                probe.assert_not_called()
        with patch.object(delegates.platform, "machine", return_value="x86_64"):
            with patch.object(delegates, "_calibrate") as probe:
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
                self.cache_path.unlink(missing_ok=True)
                with patch.object(
                    delegates, "_calibrate", side_effect=failure
                ) as probe:
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


class CacheIdentityTests(unittest.TestCase):
    def test_runtime_namespaces_coexist_and_preserve_legacy_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"XDG_CACHE_HOME": directory}):
                legacy = delegates._cache_path()
                legacy.parent.mkdir(parents=True)
                legacy.write_text(
                    json.dumps(
                        {
                            "identity": "runtime-one",
                            "entries": {
                                "face:8,12,3": {
                                    "delegate": "gpu",
                                    "timestamp": time.time(),
                                }
                            },
                        }
                    )
                )
                self.assertEqual(
                    delegates._read_cache("runtime-one")["face:8,12,3"]["delegate"],
                    "gpu",
                )
                delegates._write_cache("runtime-one", "segmentation:8,12,3", "cpu")
                delegates._write_cache("runtime-two", "face:8,12,3", "cpu")
                self.assertEqual(len(delegates._read_cache("runtime-one")), 2)
                self.assertEqual(
                    delegates._read_cache("runtime-two")["face:8,12,3"]["delegate"],
                    "cpu",
                )
                self.assertTrue(delegates._cache_path("runtime-one").is_file())
                self.assertTrue(delegates._cache_path("runtime-two").is_file())
                self.assertEqual(
                    json.loads(legacy.read_text())["identity"], "runtime-one"
                )

    def test_patched_wheel_and_os_changes_invalidate_identity(self) -> None:
        delegates._cache_identity.cache_clear()
        self.addCleanup(delegates._cache_identity.cache_clear)
        distribution = Mock(version="1.0")
        distribution.read_text.return_value = "native-library-original-hash"
        with patch.object(
            delegates.metadata, "distribution", return_value=distribution
        ):
            with patch.object(
                delegates.subprocess,
                "run",
                return_value=SimpleNamespace(stdout=b"Mac-model\nCPU"),
            ):
                with patch.object(
                    delegates.platform, "version", return_value="OS-build-one"
                ):
                    first = delegates._cache_identity()
                    distribution.read_text.return_value = "native-library-patched-hash"
                    # identity is constant within a running installation
                    self.assertEqual(delegates._cache_identity(), first)
                    delegates._cache_identity.cache_clear()
                    second = delegates._cache_identity()
                    self.assertNotEqual(first, second)
                delegates._cache_identity.cache_clear()
                with patch.object(
                    delegates.platform, "version", return_value="OS-build-two"
                ):
                    self.assertNotEqual(second, delegates._cache_identity())


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

    def test_rounds_alternate_delegates_on_identical_frames(self) -> None:
        with patch.object(
            delegates, "_measure", side_effect=[10, 8, 9, 11, 12, 7]
        ) as measure:
            self.assertEqual(
                delegates._measure_rounds("face", self.frame),
                {"cpu": [10, 11, 12], "gpu": [8, 9, 7]},
            )
        self.assertEqual(
            [call.args[1] for call in measure.call_args_list],
            ["cpu", "gpu", "gpu", "cpu", "cpu", "gpu"],
        )
        self.assertTrue(
            all(call.args[2] is self.frame for call in measure.call_args_list)
        )

    def test_calibration_uses_one_bounded_worker_and_validates_all_rounds(self) -> None:
        valid = {"cpu": [10, 11, 12], "gpu": [8, 9, 7]}
        documents: tuple[object, ...] = (
            valid,
            [],
            {},
            {"cpu": [1, 2], "gpu": [1, 2, 3]},
            {"cpu": [1, 2, 3], "gpu": [1, 2, 3, 4]},
            {"cpu": [1, 2, 3], "gpu": [1, True, 3]},
            {"cpu": [1, 2, 3], "gpu": [1, float("nan"), 3]},
            {"cpu": [1, 2, 3], "gpu": [1, 0, 3]},
            {"cpu": [1, 2, 3], "gpu": [1, -1, 3]},
            {"cpu": [1, 2, 3], "gpu": [1, "2", 3]},
        )
        for document in documents:
            with self.subTest(document=document):
                result = subprocess.CompletedProcess(
                    ["worker"], 0, stdout=json.dumps(document).encode()
                )
                with patch.object(
                    delegates.subprocess, "run", return_value=result
                ) as run:
                    if document == valid:
                        self.assertEqual(
                            delegates._calibrate("face", self.frame),
                            ([10, 11, 12], [8, 9, 7]),
                        )
                    else:
                        with self.assertRaises(ValueError):
                            delegates._calibrate("face", self.frame)
                run.assert_called_once()
                self.assertEqual(run.call_args.kwargs["timeout"], 90)
                self.assertTrue(run.call_args.kwargs["check"])
                self.assertEqual(run.call_args.args[0][-2:], ["face", "calibrate"])
                np.testing.assert_array_equal(
                    np.load(BytesIO(run.call_args.kwargs["input"]), allow_pickle=False),
                    self.frame,
                )


if __name__ == "__main__":
    unittest.main()
