"""Live benchmark exercises production lifecycle, cadence and final-frame delivery."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from scripts.benchmark_live import run_benchmark
from webcam_mods.settings import StartupSettings
from test_timing import Clock, Source, Sink


class LiveBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.source = Source(self.clock)
        self.sink = Sink(self.clock)
        self.factory = Mock(return_value=self.sink)
        self.settings = StartupSettings()

    def effect(self, frame):
        self.clock.now += 0.01
        return frame + np.uint8(7)

    def run_benchmark(self, **kwargs):
        with (
            patch("time.perf_counter", side_effect=self.clock.read),
            patch("time.monotonic", side_effect=self.clock.read),
            patch("time.sleep", side_effect=self.clock.sleep),
        ):
            return run_benchmark(
                self.source,
                self.effect,
                self.factory,
                self.settings,
                frames=3,
                warmup=1,
                **kwargs,
            )

    def test_metrics_exclude_warmup_and_match_production_cadence(self):
        report = self.run_benchmark()
        self.assertEqual(report["frames"], 3)
        self.factory.assert_called_once_with(10)
        self.assertAlmostEqual(report["capture_wait"]["median_ms"], 80)
        self.assertAlmostEqual(report["processing"]["median_ms"], 10)
        self.assertAlmostEqual(report["capture_to_send"]["median_ms"], 90)
        self.assertAlmostEqual(report["delivered_fps"], 10)
        self.assertEqual(report["input"]["width"], 4)
        self.assertFalse(self.source.active)
        self.assertGreater(report["process_peak_rss_bytes"], 0)

    def test_saved_image_is_exact_final_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "frame.png"
            self.run_benchmark(save_frame=target)
            np.testing.assert_array_equal(
                cv2.imread(str(target)), np.full((4, 4, 3), 7, np.uint8)
            )

    def test_partial_output_setup_is_cleaned_up(self):
        self.sink.setup = Mock(side_effect=RuntimeError("partial setup"))
        self.sink.teardown = Mock()
        with self.assertRaisesRegex(RuntimeError, "partial setup"):
            self.run_benchmark()
        self.sink.teardown.assert_called_once()
        self.assertFalse(self.source.active)

    def test_early_close_does_not_publish_incomplete_results(self):
        self.sink.should_stop = lambda: len(self.sink.sent) >= 2
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "frame.png"
            with self.assertRaisesRegex(RuntimeError, "before benchmark completed"):
                self.run_benchmark(save_frame=target)
            self.assertFalse(target.exists())
        self.assertFalse(self.source.active)

    def test_invalid_workload_does_not_acquire_camera(self):
        self.source.setup = Mock()
        with self.assertRaises(ValueError):
            run_benchmark(
                self.source, self.effect, self.factory, self.settings, frames=1
            )
        self.source.setup.assert_not_called()
        self.factory.assert_not_called()
