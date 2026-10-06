"""Shutdown remains bounded without closing resources still used by a worker."""

import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.frame_producer import FrameProducer
from webcam_mods.frame_producer import WorkerShutdownTimeout
from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.loopback import live_loop
from webcam_mods.macos.capture import AVFoundationCamera
from webcam_mods.settings import StartupSettings


class BlockingSource(FrameInput):
    def __init__(self, cancellable: bool = True) -> None:
        super().__init__(width=4, height=4, fps=30, device="test")
        self.active = False
        self.opens = 0
        self.cancellable = cancellable
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()

    def setup(self):
        self.active = True
        self.opens += 1
        return {"width": 4, "height": 4, "fps": 30}

    def is_setup(self):
        return self.active

    def frame(self):
        self.entered.set()
        self.release.wait(2)
        return np.zeros((4, 4, 3), np.uint8)

    def request_stop(self) -> None:
        if self.cancellable:
            self.release.set()

    def teardown(self, *args):
        self.active = False
        self.closed.set()


class WorkerShutdownTests(unittest.TestCase):
    def test_cli_preserves_worker_cleanup_ownership_after_timeout(self) -> None:
        from webcam_mods import entry

        effect, session = Mock(), Mock()
        callbacks = []

        def timed_out(**kwargs):
            callbacks.append(kwargs["processing_cleanup"])
            raise WorkerShutdownTimeout("still stopping")

        with (
            patch.object(entry, "RunSession", return_value=session),
            patch.object(entry, "live_loop", side_effect=timed_out),
        ):
            with self.assertRaises(WorkerShutdownTimeout):
                entry._run(
                    entry.Common(controls=False), effect, source=BlockingSource()
                )
        effect.close.assert_not_called()
        session.close.assert_not_called()
        callbacks[0]()
        callbacks[0]()
        effect.close.assert_called_once()
        session.close.assert_called_once()

    def test_loop_timeout_closes_output_and_defers_processing_cleanup(self) -> None:
        source = BlockingSource()
        source.release.set()
        entered, release, cleaned = (threading.Event() for _ in range(3))
        output_closed = threading.Event()
        workers = []

        class Sink(FrameOutput):
            def setup(self):
                return {"width": 4, "height": 4, "fps": 30}

            def send(self, frame):
                pass

            def should_stop(self):
                return entered.is_set()

            def teardown(self, *args):
                output_closed.set()

        def effect(frame):
            entered.set()
            release.wait(2)
            self.assertFalse(cleaned.is_set())
            return frame

        def producer(*args, **kwargs):
            worker = FrameProducer(*args, **kwargs, shutdown_timeout=0.05)
            workers.append(worker)
            return worker

        try:
            with patch("webcam_mods.frame_producer.FrameProducer", producer):
                with self.assertRaisesRegex(TimeoutError, "cleanup deferred"):
                    live_loop(
                        mod=effect,
                        fIn=source,
                        fOut=Sink(width=4, height=4, fps=30, device="test"),
                        interactive_listener=None,
                        processing_cleanup=cleaned.set,
                        settings=StartupSettings(repeat_frames=True),
                    )
            self.assertTrue(output_closed.is_set())
            self.assertFalse(cleaned.is_set())
        finally:
            release.set()
            for worker in workers:
                worker._thread.join(2)
        self.assertTrue(cleaned.is_set())

    def test_startup_opens_once_and_cancels_pending_capture(self) -> None:
        source = BlockingSource()
        cleanup = Mock()
        producer = FrameProducer(source, cleanup=cleanup, shutdown_timeout=1)
        try:
            producer.setup()
            producer.configure(lambda frame: frame, 30)
            producer.enable(True)
            self.assertTrue(source.entered.wait(1))
            self.assertEqual(source.opens, 1)
            producer.close()
            self.assertFalse(producer._thread.is_alive())
            self.assertFalse(source.active)
            cleanup.assert_called_once()
            producer.latest()
        finally:
            source.release.set()
            producer._thread.join(2)
            producer.close()

    def test_timeout_defers_cleanup_until_capture_returns(self) -> None:
        source = BlockingSource(cancellable=False)
        cleanup = threading.Event()
        producer = FrameProducer(source, cleanup=cleanup.set, shutdown_timeout=0.05)
        try:
            producer.setup()
            producer.configure(lambda frame: frame, 30)
            producer.enable(True)
            self.assertTrue(source.entered.wait(1))
            with self.assertRaisesRegex(TimeoutError, "cleanup deferred"):
                producer.close()
            producer.close()
            self.assertFalse(cleanup.is_set())
            self.assertFalse(source.closed.is_set())
            self.assertTrue(producer._thread.daemon)
        finally:
            source.release.set()
            producer._thread.join(2)
        self.assertTrue(cleanup.is_set())
        self.assertFalse(producer._thread.is_alive())

    def test_stalled_effect_keeps_resources_until_return(self) -> None:
        source = BlockingSource()
        source.release.set()
        entered, release, cleaned = (threading.Event() for _ in range(3))

        def effect(frame):
            entered.set()
            release.wait(2)
            self.assertFalse(cleaned.is_set())
            return frame

        producer = FrameProducer(source, cleanup=cleaned.set, shutdown_timeout=0.05)
        try:
            producer.setup()
            producer.configure(effect, 30)
            producer.enable(True)
            self.assertTrue(entered.wait(1))
            with self.assertRaises(TimeoutError):
                producer.close()
            self.assertFalse(cleaned.is_set())
        finally:
            release.set()
            producer._thread.join(2)
            producer.close()
        self.assertTrue(cleaned.is_set())
        self.assertIsNone(producer.latest())

    def test_native_stop_wakes_pending_frame_without_teardown(self) -> None:
        camera = AVFoundationCamera(width=4, height=4)
        camera._running = True
        entered = threading.Event()
        original = camera._condition.wait_for

        def waiting(*args, **kwargs):
            entered.set()
            return original(*args, **kwargs)

        result = []
        with patch.object(camera._condition, "wait_for", waiting):
            reader = threading.Thread(target=lambda: result.append(camera.frame()))
            reader.start()
            self.assertTrue(entered.wait(1))
            camera.request_stop()
            reader.join(1)
        self.assertFalse(reader.is_alive())
        self.assertEqual(result, [None])
        self.assertTrue(camera._stop.is_set())
        camera.teardown()
