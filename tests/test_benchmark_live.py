"""Live benchmark exercises production lifecycle, cadence and final-frame delivery."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from scripts.benchmark_live import main, run_benchmark, run_cycles, write_report
from webcam_mods.settings import StartupSettings
from test_timing import Clock, Source, Sink


class LifecycleSink(Sink):
    def setup(self):
        self.active = True
        return super().setup()

    def teardown(self, *args):
        self.active = False

    def is_setup(self):
        return self.active


class LiveBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.source = Source(self.clock)
        self.sink = LifecycleSink(self.clock)
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

    def test_cli_device_override_reaches_capture_before_setup(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "sys.argv",
                [
                    "benchmark_live",
                    "--input-device",
                    "1",
                    "--report",
                    str(Path(directory) / "report.json"),
                ],
            ),
            patch("webcam_mods.macos.capture.AVFoundationCamera") as camera,
            patch("scripts.benchmark_live.PersonEffects"),
            patch(
                "scripts.benchmark_live.run_benchmark",
                return_value={
                    "processing": {},
                    "capture_to_send": {},
                    "delivered_fps": 30,
                    "process_peak_rss_bytes": 0,
                },
            ) as benchmark,
            patch("builtins.print"),
        ):
            main()
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(report["delivered_fps"], 30)
            self.assertNotIn("runs", report)
        self.assertEqual(camera.call_args.kwargs["device_index"], 1)
        self.assertEqual(benchmark.call_args.args[3].video_in, 1)

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
        self.assertFalse(self.sink.active)
        self.assertTrue(report["cleanup_verified"])
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

    def test_open_adapter_after_teardown_rejects_results(self):
        self.sink.teardown = Mock()
        with self.assertRaisesRegex(RuntimeError, "remain open"):
            self.run_benchmark()
        self.assertFalse(self.source.active)

    def test_cycles_preserve_evidence_and_stop_after_failure(self):
        checkpoints = []
        run = Mock(side_effect=[{"frames": 3}, RuntimeError("capture failed")])
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            run_cycles(
                run,
                3,
                lambda report: checkpoints.append(json.loads(json.dumps(report))),
            )
        self.assertEqual(run.call_count, 2)
        self.assertEqual(checkpoints[-1]["status"], "failed")
        self.assertEqual(checkpoints[-1]["failed_cycle"], 2)
        self.assertEqual(checkpoints[-1]["cycles_completed"], 1)
        self.assertEqual(checkpoints[-1]["runs"], [{"frames": 3}])
        self.assertEqual(checkpoints[0]["status"], "running")

    def test_interruption_keeps_progress_and_propagates(self):
        checkpoint = Mock()
        with self.assertRaises(KeyboardInterrupt):
            run_cycles(Mock(side_effect=KeyboardInterrupt), 3, checkpoint)
        self.assertEqual(checkpoint.call_args.args[0]["status"], "interrupted")

    def test_invalid_cycles_do_not_run_or_publish(self):
        run, checkpoint = Mock(), Mock()
        with self.assertRaises(ValueError):
            run_cycles(run, 0, checkpoint)
        run.assert_not_called()
        checkpoint.assert_not_called()

    def test_checkpoint_failure_does_not_hide_original_error(self):
        original = RuntimeError("capture failed")
        with self.assertRaisesRegex(RuntimeError, "capture failed") as caught:
            run_cycles(
                Mock(side_effect=original),
                3,
                Mock(side_effect=[None, OSError("disk full")]),
            )
        self.assertIs(caught.exception, original)
        self.assertIn("disk full", original.__notes__[0])

    def test_failed_atomic_checkpoint_preserves_previous_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            previous = {"status": "running", "cycles_completed": 1}
            write_report(target, previous)
            with patch("scripts.benchmark_live.os.replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    write_report(target, {"status": "passed"})
            self.assertEqual(json.loads(target.read_text()), previous)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_cli_teardown_failure_saves_progress_and_stops_restarts(self):
        first_effect, second_effect = Mock(), Mock()
        second_effect.close.side_effect = RuntimeError("teardown failed")
        result = {
            "processing": {},
            "capture_to_send": {},
            "delivered_fps": 30,
            "process_peak_rss_bytes": 0,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "sys.argv",
                [
                    "benchmark_live",
                    "--cycles",
                    "3",
                    "--report",
                    str(Path(directory) / "report.json"),
                ],
            ),
            patch("webcam_mods.macos.capture.AVFoundationCamera") as camera,
            patch(
                "scripts.benchmark_live.PersonEffects",
                side_effect=[first_effect, second_effect],
            ) as effects,
            patch(
                "scripts.benchmark_live.run_benchmark",
                side_effect=[dict(result), dict(result)],
            ) as benchmark,
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "teardown failed"):
                main()
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failed_cycle"], 2)
            self.assertEqual(report["cycles_completed"], 1)
            self.assertEqual(len(report["runs"]), 1)
            self.assertEqual(report["workload"]["capture"], "avfoundation")
        self.assertEqual(camera.call_count, 2)
        self.assertEqual(effects.call_count, 2)
        self.assertEqual(benchmark.call_count, 2)
        first_effect.close.assert_called_once()
        second_effect.close.assert_called_once()

    def test_cli_cycles_release_resources_before_next_acquisition(self):
        events = []
        sources, sinks, effects = [], [], []

        def source_factory(**kwargs):
            if sources:
                self.assertFalse(sources[-1].active)
                self.assertFalse(sinks[-1].active)
                effects[-1].close.assert_called_once()
            source = Source(self.clock)
            sources.append(source)
            events.append("acquire")
            return source

        def output_factory(*args, **kwargs):
            sink = LifecycleSink(self.clock)
            sinks.append(sink)
            return sink

        def effect_factory(**kwargs):
            effect = Mock()
            effect.blur_bg.side_effect = lambda frame, kernel: frame
            effect.close.side_effect = lambda: events.append("close")
            effects.append(effect)
            return effect

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("time.perf_counter", side_effect=self.clock.read),
            patch("time.monotonic", side_effect=self.clock.read),
            patch("time.sleep", side_effect=self.clock.sleep),
            patch("webcam_mods.macos.capture.AVFoundationCamera", source_factory),
            patch("scripts.benchmark_live.default_frame_output", output_factory),
            patch("scripts.benchmark_live.PersonEffects", effect_factory),
            patch("builtins.print"),
        ):
            report_path = Path(directory) / "report.json"
            frame_path = Path(directory) / "frame.png"
            with patch(
                "sys.argv",
                [
                    "benchmark_live",
                    "--cycles",
                    "3",
                    "--frames",
                    "3",
                    "--warmup",
                    "1",
                    "--report",
                    str(report_path),
                    "--save-frame",
                    str(frame_path),
                ],
            ):
                main()
            report = json.loads(report_path.read_text())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["cycles_completed"], 3)
            self.assertTrue(all(run["cleanup_verified"] for run in report["runs"]))
            for cycle in range(1, 4):
                self.assertTrue((Path(directory) / f"frame-cycle-{cycle}.png").exists())
        self.assertEqual(events, ["acquire", "close"] * 3)
        self.assertFalse(sources[-1].active)
        self.assertFalse(sinks[-1].active)
