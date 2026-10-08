"""Loading frames reach every output while setup and first inference are blocked."""

import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np
from typer.testing import CliRunner

from cli_fixtures import HeadlessCliTestCase

from webcam_mods import entry
from webcam_mods.effects import ProfileEffect
from webcam_mods.frame_producer import FrameProducer
from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.loopback import live_loop
from webcam_mods.profiles import Profile
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.signals import SignalFrames


class StartupSource(FrameInput):
    def __init__(self) -> None:
        super().__init__(width=96, height=64, fps=30, device="test")
        self.entered = threading.Event()
        self.release = threading.Event()
        self.active = False
        self.reads = 0
        self.opens = 0

    def setup(self):
        self.opens += 1
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError("test did not release camera setup")
        self.active = True
        return {"width": 96, "height": 64, "fps": 30}

    def is_setup(self):
        return self.active

    def teardown(self, *args):
        self.active = False

    def request_stop(self):
        self.release.set()

    def frame(self):
        self.reads += 1
        return np.full((64, 96, 3), 201, dtype=np.uint8)


class StartupSink(FrameOutput):
    def __init__(self, send) -> None:
        super().__init__(width=96, height=64, fps=30, device="test")
        self.active = False
        self.stop = False
        self.frames = []
        self.callback = send

    def setup(self):
        self.active = True
        return {"width": 96, "height": 64, "fps": 30}

    def teardown(self, *args):
        self.active = False

    def send(self, frame):
        self.frames.append(frame.copy())
        self.callback(frame)

    def should_stop(self):
        return self.stop


class StartupFrameTests(unittest.TestCase):
    def test_setup_and_first_inference_keep_delivering_identical_preview_frames(self):
        for repeat in (False, True):
            for pattern in ("color-bars", "noise"):
                with self.subTest(repeat=repeat, pattern=pattern):
                    source = StartupSource()
                    effect_entered, effect_release = (
                        threading.Event(),
                        threading.Event(),
                    )
                    preview = []
                    ready, cleanup = Mock(), Mock()
                    opening, preparing, live = [], [], []

                    def effect(frame):
                        effect_entered.set()
                        if not effect_release.wait(2):
                            raise RuntimeError("test did not release inference")
                        return frame

                    def send(frame):
                        if np.all(frame == 201):
                            live.append(frame)
                            sink.stop = len(live) == 3
                        elif not source.release.is_set():
                            opening.append(frame)
                            if len(opening) == 3:
                                self.assertTrue(source.entered.is_set())
                                self.assertTrue(sink.active)
                                ready.assert_not_called()
                                source.release.set()
                        elif effect_entered.is_set():
                            preparing.append(frame)
                            if len(preparing) == 3:
                                ready.assert_not_called()
                                effect_release.set()
                        if len(sink.frames) > 60:
                            raise AssertionError("startup did not finish")

                    sink = StartupSink(send)
                    try:
                        live_loop(
                            fIn=source,
                            fOut=sink,
                            mod=effect,
                            interactive_listener=None,
                            strict_errors=True,
                            settings=StartupSettings(
                                repeat_frames=repeat, signal_pattern=pattern
                            ),
                            on_frame=lambda frame: preview.append(frame.copy()),
                            on_ready=ready,
                            processing_cleanup=cleanup,
                        )
                    finally:
                        source.release.set()
                        effect_release.set()
                    self.assertEqual(len(opening), 3)
                    self.assertEqual(len(preparing), 3)
                    self.assertEqual(source.opens, 1)
                    self.assertEqual(len(preview), len(sink.frames))
                    for actual, mirrored in zip(sink.frames, preview):
                        np.testing.assert_array_equal(actual, mirrored)
                    if not repeat:
                        self.assertEqual(source.reads, 3)
                    ready.assert_called_once()
                    cleanup.assert_called_once()
                    self.assertFalse(source.active)
                    self.assertFalse(sink.active)

    def test_close_during_setup_cancels_capture_without_reporting_running(self):
        source = StartupSource()
        cleanup, ready = Mock(), Mock()
        sink = StartupSink(lambda frame: setattr(sink, "stop", len(sink.frames) == 3))
        live_loop(
            fIn=source,
            fOut=sink,
            interactive_listener=None,
            settings=StartupSettings(repeat_frames=True),
            processing_cleanup=cleanup,
            on_ready=ready,
        )
        self.assertEqual(source.reads, 0)
        ready.assert_not_called()
        cleanup.assert_called_once()
        self.assertFalse(source.active)
        self.assertFalse(sink.active)

    def test_effect_construction_waits_until_worker_processes_first_frame(self):
        background = Mock(side_effect=lambda frame: frame)
        with patch(
            "webcam_mods.entry.BackgroundEffect", return_value=background
        ) as factory:
            effect = ProfileEffect(Profile(effect="blur"), StartupSettings())
            factory.assert_not_called()
            effect(np.zeros((64, 96, 3), dtype=np.uint8))
            effect(np.zeros((64, 96, 3), dtype=np.uint8))
            factory.assert_called_once()
            effect.close()
            effect.close()
            background.close.assert_called_once()

    def test_direct_worker_does_not_process_without_a_request(self):
        source = StartupSource()
        source.release.set()
        processed = threading.Event()
        producer = FrameProducer(source)
        try:
            producer.setup()
            producer.configure(
                lambda frame: processed.set() or frame, 30, continuous=False
            )
            producer.enable(True)
            self.assertFalse(processed.wait(0.05))
            producer.request_frame()
            self.assertIsNotNone(producer.take(timeout=1))
            processed.clear()
            self.assertFalse(processed.wait(0.05))
            self.assertEqual(source.reads, 1)
        finally:
            producer.close()


class SignalFrameTests(HeadlessCliTestCase):
    def test_bars_cached_and_noise_refresh_is_limited_without_mutating_old_frames(self):
        for pattern in ("color-bars", "noise"):
            with self.subTest(pattern=pattern):
                signals = SignalFrames(320, 240, pattern)
                first = signals.frame("Preparing effects...", now=0)
                owned = first.copy()
                self.assertIs(signals.frame("Preparing effects...", now=0.1), first)
                later = signals.frame("Preparing effects...", now=0.126)
                self.assertEqual(later.dtype, np.uint8)
                self.assertEqual(later.shape, (240, 320, 3))
                np.testing.assert_array_equal(first, owned)
                if pattern == "color-bars":
                    self.assertIs(later, first)
                else:
                    self.assertFalse(np.array_equal(later, first))
                changed = signals.frame("Camera paused", now=0.127)
                self.assertIsNot(changed, later)

    def test_profile_env_and_cli_choose_same_pattern(self):
        self.assertEqual(Profile.parse({}).signal_pattern, "color-bars")
        self.assertEqual(
            Profile.parse({"signal_pattern": "noise"}).signal_pattern, "noise"
        )
        self.assertEqual(
            load_settings({"SIGNAL_PATTERN": "noise"}).signal_pattern, "noise"
        )
        with self.assertRaises(ValueError):
            Profile.parse({"signal_pattern": "bad"})
        for arguments in (
            ["--signal-pattern", "noise", "test-loop"],
            ["test-loop", "--signal-pattern", "noise"],
        ):
            with patch.object(entry, "live_loop") as loop:
                result = CliRunner().invoke(entry.app, ["--no-controls", *arguments])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(loop.call_args.kwargs["settings"].signal_pattern, "noise")
