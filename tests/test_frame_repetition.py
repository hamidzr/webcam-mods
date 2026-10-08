"""Independent delivery survives stalled effects without queued or mutable frames."""

from pathlib import Path
import threading

import cv2
import unittest
from unittest.mock import patch

import numpy as np
from typer.testing import CliRunner

from cli_fixtures import HeadlessCliTestCase

from webcam_mods import entry
from webcam_mods.frame_producer import FrameProducer
from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.loopback import default_frame_output, live_loop
from webcam_mods.settings import StartupSettings, load_settings


class Source(FrameInput):
    def __init__(self):
        super().__init__(width=4, height=4, fps=30, device="test")
        self.active = False
        self.calls = 0
        self.threads = []
        self.buffer = np.zeros((4, 4, 3), dtype=np.uint8)

    def setup(self):
        self.threads.append(threading.get_ident())
        self.active = True
        return {"width": 4, "height": 4, "fps": 30}

    def is_setup(self):
        return self.active

    def teardown(self, *args):
        self.threads.append(threading.get_ident())
        self.active = False

    def frame(self):
        self.threads.append(threading.get_ident())
        self.calls += 1
        self.buffer.fill(self.calls)
        return self.buffer


class Sink(FrameOutput):
    def __init__(self, send=None):
        super().__init__(width=4, height=4, fps=60, device="test")
        self.frames = []
        self.active = False
        self.on_send = send
        self.threads = []
        self.in_use = True
        self.stop = False

    def setup(self):
        self.active = True
        return {"width": 4, "height": 4, "fps": 60}

    def is_setup(self):
        return self.active

    def teardown(self, *args):
        self.active = False

    def send(self, frame):
        self.threads.append(threading.get_ident())
        self.frames.append(frame.copy())
        if self.on_send:
            self.on_send(frame)

    def process_events(self):
        self.threads.append(threading.get_ident())

    def should_stop(self):
        return self.stop

    def is_in_use(self):
        return self.in_use

    def wait_until_next_frame(self):
        raise AssertionError("backend must not own cadence")


class RepetitionTests(HeadlessCliTestCase):
    def run_loop(self, source, sink, **kwargs):
        live_loop(
            fIn=source,
            fOut=sink,
            interactive_listener=None,
            settings=StartupSettings(repeat_frames=True, processing_fps=30),
            **kwargs,
        )

    def test_slow_effect_repeats_owned_frame_and_then_updates(self):
        source = Source()
        release = threading.Event()
        stalled = threading.Event()
        repeats = []
        callback_threads = []

        def effect(frame):
            callback_threads.append(threading.get_ident())
            if source.calls == 2:
                stalled.set()
                if not release.wait(2):
                    raise RuntimeError("test effect timed out")
            return frame

        def delivered(frame):
            if stalled.is_set() and not release.is_set() and np.all(frame == 1):
                repeats.append(frame.copy())
                if len(repeats) == 4:
                    release.set()
            if release.is_set() and np.all(frame >= 2):
                sink.stop = True
            if len(sink.frames) >= 120:
                release.set()
                raise AssertionError("new frame never arrived")

        sink = Sink(delivered)
        try:
            self.run_loop(source, sink, mod=effect, strict_errors=True)
        finally:
            release.set()
        self.assertEqual(len(repeats), 4)
        self.assertTrue(np.all(sink.frames[-1] >= 2))
        self.assertLess(source.calls, len(sink.frames))
        self.assertFalse(source.active)
        self.assertFalse(sink.active)
        main = threading.get_ident()
        self.assertTrue(all(t == main for t in sink.threads))
        self.assertEqual(len(set(source.threads + callback_threads)), 1)
        self.assertNotEqual(source.threads[0], main)

    def test_capture_failure_propagates_and_cleans_up(self):
        source, sink = Source(), Sink()
        with patch.object(source, "frame", side_effect=OSError("capture failed")):
            with self.assertRaisesRegex(OSError, "capture failed"):
                self.run_loop(source, sink)
        self.assertFalse(source.active)
        self.assertFalse(sink.active)

    def test_empty_input_keeps_delivery_alive(self):
        source = Source()
        sink = Sink()
        with patch.object(source, "frame", return_value=None):
            # preview closure ends an unbounded run without requiring fresh input
            sink.on_send = lambda frame: setattr(sink, "stop", len(sink.frames) == 4)
            self.run_loop(source, sink)
        self.assertEqual(len(sink.frames), 4)
        for frame in sink.frames:
            np.testing.assert_array_equal(frame, sink.frames[0])

    def test_output_failure_joins_worker_before_cleanup(self):
        source, sink = Source(), Sink()
        with patch.object(sink, "send", side_effect=OSError("output failed")):
            with self.assertRaisesRegex(OSError, "output failed"):
                self.run_loop(source, sink)
        self.assertFalse(source.active)
        self.assertFalse(sink.active)
        self.assertFalse(
            any(t.name == "webcam-frame-producer" for t in threading.enumerate())
        )

    def test_setup_failure_propagates_and_closes_source(self):
        source, sink = Source(), Sink()
        with patch.object(source, "setup", side_effect=OSError("setup failed")):
            with self.assertRaisesRegex(OSError, "setup failed"):
                self.run_loop(source, sink)
        self.assertFalse(source.active)
        self.assertFalse(sink.active)

    def test_processing_cap_controls_worker_wait(self):
        source = Source()
        producer = FrameProducer(source)
        published = threading.Event()
        periods = []

        def wait(pacer, **kwargs):
            periods.append(pacer.period)
            published.set()
            producer._stop.wait(1)
            return False

        try:
            producer.setup()
            producer.configure(lambda frame: frame, 15)
            with patch("webcam_mods.frame_producer.FramePacer.wait", wait):
                producer.enable(True)
                self.assertTrue(published.wait(1))
                producer.close()
            self.assertEqual(periods, [1 / 15])
            self.assertEqual(source.calls, 1)
        finally:
            producer.close()

    def test_real_segmentation_on_worker(self):
        from webcam_mods.mods.person_segmentation import PersonEffects

        fixture = cv2.imread(str(Path(__file__).parent / "fixtures" / "astronaut.png"))
        self.assertIsNotNone(fixture)
        source = Source()
        producer = FrameProducer(source)
        effects = PersonEffects()
        published = threading.Event()

        def wait(pacer, **kwargs):
            published.set()
            producer._stop.wait(5)
            return False

        try:
            producer.setup()
            producer.configure(lambda frame: effects.blur_bg(fixture, 15), 15)
            with patch("webcam_mods.frame_producer.FramePacer.wait", wait):
                producer.enable(True)
                self.assertTrue(published.wait(30), "native worker did not finish")
                producer.close()
            frame = producer.latest()
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, fixture.shape)
            self.assertGreater(np.std(frame), 0)
        finally:
            producer.close()
            effects.close()

    def test_on_demand_pause_closes_capture_but_keeps_delivery(self):
        source, sink = Source(), Sink()
        sink.in_use = False
        self.run_loop(source, sink, on_demand=True, max_frames=4)
        self.assertEqual(source.calls, 0)
        self.assertEqual(len(sink.frames), 4)
        self.assertFalse(source.active)

    def test_pause_then_resume_reopens_capture_and_delivers_fresh_frames(self):
        source = Source()
        paused = False
        resumed = False
        paused_deliveries = 0

        def delivered(frame):
            nonlocal paused, resumed, paused_deliveries
            if not paused and np.all(frame == 1):
                paused = True
                sink.in_use = False
            elif paused and not resumed:
                paused_deliveries += 1
                if not source.active and paused_deliveries >= 2:
                    resumed = True
                    sink.in_use = True
            elif resumed and np.all(frame >= 2):
                sink.stop = True
            if len(sink.frames) >= 120:
                raise AssertionError("capture did not resume")

        sink = Sink(delivered)
        self.run_loop(source, sink, on_demand=True)
        self.assertTrue(resumed)
        self.assertFalse(source.active)
        self.assertGreaterEqual(paused_deliveries, 2)

    def test_effect_failure_freezes_only_when_requested(self):
        for freeze in (False, True):
            with self.subTest(freeze=freeze):
                source = Source()
                failed = threading.Event()

                def effect(frame):
                    if source.calls >= 2:
                        failed.set()
                        raise ValueError("effect failed")
                    return frame

                def delivered(frame):
                    if failed.is_set() and (
                        np.all(frame == 1) if freeze else not np.all(frame == 1)
                    ):
                        sink.stop = True
                    if len(sink.frames) >= 120:
                        raise AssertionError("effect fallback did not arrive")

                sink = Sink(delivered)
                self.run_loop(source, sink, mod=effect, freeze_on_error=freeze)
                self.assertTrue(failed.is_set())
                self.assertEqual(bool(np.all(sink.frames[-1] == 1)), freeze)

    def test_direct_failure_freezes_snapshot_of_reused_input(self) -> None:
        for raises in (False, True):
            with self.subTest(raises=raises):
                source, sink = Source(), Sink()

                def effect(frame: np.ndarray) -> np.ndarray | None:
                    if source.calls == 2:
                        if raises:
                            raise ValueError("synthetic effect failure")
                        return None
                    return frame

                live_loop(
                    fIn=source,
                    fOut=sink,
                    mod=effect,
                    interactive_listener=None,
                    on_demand=False,
                    freeze_on_error=True,
                    max_frames=2,
                    pace=False,
                    settings=StartupSettings(repeat_frames=False),
                )
                self.assertEqual(source.calls, 2)
                self.assertEqual(len(sink.frames), 2)
                np.testing.assert_array_equal(sink.frames[0], 1)
                np.testing.assert_array_equal(sink.frames[1], sink.frames[0])
                np.testing.assert_array_equal(source.buffer, 2)
                self.assertFalse(source.active)
                self.assertFalse(sink.active)

    def test_strict_empty_input_is_an_error(self):
        source, sink = Source(), Sink()
        with patch.object(source, "frame", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "input returned no frame"):
                self.run_loop(source, sink, strict_errors=True)
        self.assertFalse(source.active)
        self.assertFalse(sink.active)

    def test_output_rate_independent_only_when_enabled(self):
        for repeat, expected in ((False, 15), (True, 30)):
            sink = default_frame_output(
                15, backend="preview", settings=StartupSettings(repeat_frames=repeat)
            )
            self.assertEqual(sink.fps, expected)

    def test_settings_and_cli_options(self):
        settings = load_settings({"REPEAT_FRAMES": "true", "PROCESSING_FPS": "15"})
        self.assertTrue(settings.repeat_frames)
        self.assertEqual(settings.processing_fps, 15)
        for value in ("0", "nan", "inf"):
            with self.assertRaisesRegex(ValueError, "PROCESSING_FPS"):
                load_settings({"PROCESSING_FPS": value})
        for args in (
            ["--repeat-frames", "--processing-fps", "15", "test-loop"],
            ["test-loop", "--repeat-frames", "--processing-fps", "15"],
        ):
            with patch.object(entry, "live_loop") as loop:
                result = CliRunner().invoke(entry.app, ["--no-controls", *args])
            self.assertEqual(result.exit_code, 0, result.output)
            settings = loop.call_args.kwargs["settings"]
            self.assertTrue(settings.repeat_frames)
            self.assertEqual(settings.processing_fps, 15)


if __name__ == "__main__":
    unittest.main()
