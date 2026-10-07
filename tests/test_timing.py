"""Cadence is independent of output-specific waits and camera processing cost."""

import unittest
from unittest.mock import patch

import numpy as np

from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.loopback import live_loop
from webcam_mods.timing import FramePacer


class Clock:
    def __init__(self) -> None:
        self.now = 10.0
        self.sleeps: list[float] = []

    def read(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Source(FrameInput):
    def __init__(self, clock: Clock) -> None:
        super().__init__(width=4, height=4, fps=10)
        self.clock = clock
        self.active = False

    def setup(self):
        self.active = True
        return {"width": 4, "height": 4, "fps": 10}

    def is_setup(self):
        return self.active

    def teardown(self, *args):
        self.active = False

    def frame(self):
        self.clock.now += 0.08
        return np.zeros((4, 4, 3), np.uint8)


class Sink(FrameOutput):
    def __init__(self, clock: Clock, in_use: bool = True) -> None:
        super().__init__(width=4, height=4, fps=10)
        self.clock = clock
        self.in_use = in_use
        self.sent: list[float] = []
        self.events = 0

    def setup(self):
        return {"width": 4, "height": 4, "fps": 10}

    def teardown(self, *args):
        pass

    def send(self, frame):
        self.sent.append(self.clock.now)

    def wait_until_next_frame(self):
        raise AssertionError("loop must not invoke backend pacing")

    def process_events(self):
        self.events += 1

    def is_in_use(self):
        return self.in_use


class TimingTests(unittest.TestCase):
    def pacer(self, clock: Clock) -> FramePacer:
        return FramePacer(10, clock=clock.read, sleep=clock.sleep)

    def test_processing_counts_toward_period(self):
        clock = Clock()
        pacer = self.pacer(clock)
        clock.now += 0.08
        self.assertTrue(pacer.wait())
        self.assertAlmostEqual(sum(clock.sleeps), 0.02)
        self.assertAlmostEqual(clock.now, 10.1)

    def test_missed_deadline_does_not_catch_up(self):
        clock = Clock()
        pacer = self.pacer(clock)
        clock.now += 0.35
        pacer.wait()
        self.assertEqual(clock.sleeps, [])
        pacer.wait()
        self.assertAlmostEqual(clock.now, 10.45)
        self.assertAlmostEqual(sum(clock.sleeps), 0.1)

    def test_event_polling_stops_long_wait_promptly(self):
        clock = Clock()
        pacer = self.pacer(clock)
        polls = []

        def events():
            polls.append(clock.now)
            return len(polls) < 3

        self.assertFalse(pacer.wait(interval=0.5, process_events=events))
        self.assertAlmostEqual(clock.now, 10.04)
        self.assertLessEqual(max(clock.sleeps), 0.02)

    def test_event_cost_counts_toward_deadline_without_final_extra_poll(self):
        clock = Clock()
        pacer = FramePacer(30, clock=clock.read, sleep=clock.sleep)
        polls = []

        def events():
            polls.append(clock.now)
            clock.now += 0.012
            return True

        for _ in range(10):
            clock.now += 0.012
            pacer.wait(process_events=events)
        self.assertEqual(len(polls), 10)
        self.assertAlmostEqual(clock.now, 10 + 10 / 30)

    def test_small_sleep_overruns_do_not_accumulate_drift(self):
        clock = Clock()

        def oversleep(seconds):
            clock.sleep(seconds + 0.002)

        pacer = FramePacer(10, clock=clock.read, sleep=oversleep)
        for _ in range(10):
            pacer.wait()
        self.assertAlmostEqual(clock.now, 11.002)

    def test_invalid_fps_rejected(self):
        for fps in (0, -1, float("inf"), float("nan")):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                FramePacer(fps)

    def run_loop(self, *, paused=False, pace=True):
        clock = Clock()
        source = Source(clock)
        sink = Sink(clock, in_use=not paused)
        with (
            patch("webcam_mods.timing.time.monotonic", side_effect=clock.read),
            patch("webcam_mods.timing.time.sleep", side_effect=clock.sleep),
        ):
            live_loop(
                fIn=source,
                fOut=sink,
                interactive_listener=None,
                max_frames=3,
                on_demand=paused,
                pace=pace,
            )
        self.assertFalse(source.active)
        return clock, sink

    def test_loop_owns_cadence_and_counts_capture_time(self):
        clock, sink = self.run_loop()
        np.testing.assert_allclose(sink.sent, [10.08, 10.18, 10.28])
        self.assertAlmostEqual(sum(clock.sleeps), 0.06)
        self.assertGreaterEqual(sink.events, 3)

    def test_paused_loop_uses_single_half_second_interval(self):
        clock, sink = self.run_loop(paused=True)
        np.testing.assert_allclose(sink.sent, [10, 10.5, 11])
        self.assertAlmostEqual(clock.now, 11.5)
        self.assertAlmostEqual(sum(clock.sleeps), 1.5)

    def test_unpaced_runs_still_pump_events(self):
        clock, sink = self.run_loop(pace=False)
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(sink.events, 3)

    def test_unsupported_consumer_detection_has_actionable_error(self):
        with self.assertRaisesRegex(NotImplementedError, "consumer detection"):
            FrameOutput().is_in_use()

    def test_missing_input_remains_responsive(self):
        clock = Clock()
        source = Source(clock)
        source.frame = lambda: None
        sink = Sink(clock)
        sink.should_stop = lambda: sink.events >= 2
        with (
            patch("webcam_mods.timing.time.monotonic", side_effect=clock.read),
            patch("webcam_mods.timing.time.sleep", side_effect=clock.sleep),
        ):
            live_loop(fIn=source, fOut=sink, interactive_listener=None, on_demand=False)
        self.assertEqual(sink.sent, [10.0])
        self.assertFalse(source.active)
        self.assertAlmostEqual(clock.now, 10.02)
