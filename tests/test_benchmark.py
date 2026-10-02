"""Benchmark artifact and failure cleanup checks without native/model dependencies."""

from pathlib import Path
import tempfile
from typing import Any
import unittest

import cv2
import numpy as np

from scripts.benchmark_processing import BenchmarkOptions, run_benchmark


class FakeEffects:
    def __init__(self, fail: bool = False) -> None:
        self.frames: list[np.ndarray] = []
        self.closed = False
        self.fail = fail

    def blur_bg(self, frame: np.ndarray, kernel_size: int) -> np.ndarray:
        if self.fail:
            raise RuntimeError("effect failure")
        self.frames.append(frame.copy())
        return frame

    def close(self) -> None:
        self.closed = True


class BenchmarkTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "metrics.json"

    def test_motion_and_reviewable_artifacts(self) -> None:
        effects = FakeEffects()
        report = run_benchmark(
            BenchmarkOptions(frames=3, warmup=1, width=32, height=24),
            self.output,
            factory=lambda _: effects,
        )
        self.assertTrue(effects.closed)
        self.assertEqual(len(effects.frames), 4)
        self.assertFalse(np.array_equal(effects.frames[0], effects.frames[1]))
        self.assertEqual(len(report["samples_ms"]), 3)
        self.assertGreater(report["median_ms"], 0)
        self.assertEqual(report["output_shape"], [24, 32, 3])
        self.assertTrue(self.output.exists())
        decoded = cv2.imread(str(self.output.with_suffix(".png")))
        np.testing.assert_array_equal(decoded, effects.frames[-1])
        self.assertEqual(report["workload"]["blur_kernel"], "box")

    def test_failed_effect_closes_resources_and_writes_no_report(self) -> None:
        effects = FakeEffects(fail=True)
        with self.assertRaisesRegex(RuntimeError, "effect failure"):
            run_benchmark(
                BenchmarkOptions(frames=1, warmup=0),
                self.output,
                factory=lambda _: effects,
            )
        self.assertTrue(effects.closed)
        self.assertFalse(self.output.exists())

    def test_invalid_workload_does_not_initialize_effects(self) -> None:
        def unexpected(_: Any) -> Any:
            self.fail("invalid workload initialized effects")

        with self.assertRaises(ValueError):
            run_benchmark(BenchmarkOptions(frames=0), self.output, factory=unexpected)


if __name__ == "__main__":
    unittest.main()
