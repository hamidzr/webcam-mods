"""Native preview follows delivered frames, demand, and session ownership."""

import base64
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from webcam_mods.control import Controller, run_profile
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.loopback import default_frame_output, live_loop
from webcam_mods.mods.video_mods import resize_and_pad
from webcam_mods.output.native_preview import NativePreview, NativePreviewOutput
from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.settings import StartupSettings
from webcam_mods.utils.video import Frame


def decode(result):
    return cv2.imdecode(
        np.frombuffer(base64.b64decode(result["jpeg"]), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )


class Source(FrameInput):
    def __init__(self) -> None:
        super().__init__(width=16, height=8, fps=30, device="test")
        self.active = False
        self.original = np.full((8, 16, 3), (10, 40, 90), dtype=np.uint8)

    def setup(self) -> AdapterMetadata:
        self.active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args, **kwargs) -> None:
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def frame(self) -> Frame:
        return self.original.copy()


class RecordingOutput(NativePreviewOutput):
    def __init__(self) -> None:
        super().__init__(width=96, height=64, fps=60)
        self.frames = []

    def send(self, frame: Frame) -> None:
        self.frames.append(frame.copy())


class NativePreviewTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.preview = NativePreview(lambda: self.now)
        self.frame = np.full((720, 1280, 3), (20, 80, 170), dtype=np.uint8)

    def test_no_encode_before_demand_and_expired_demand_drops_stale_frame(self):
        with patch(
            "webcam_mods.output.native_preview.cv2.imencode", wraps=cv2.imencode
        ) as encode:
            self.preview.publish(self.frame)
            encode.assert_not_called()
            self.assertIsNone(self.preview.get())
            self.preview.publish(self.frame)
            self.assertEqual(encode.call_count, 1)
            self.assertIsNotNone(self.preview.get())
            self.now = 1.1
            self.preview.publish(self.frame)
            self.assertEqual(encode.call_count, 1)
            self.assertIsNone(self.preview.get())
            self.preview.publish(self.frame)
            self.assertEqual(encode.call_count, 2)

    def test_rate_limit_latest_only_and_aspect_preserved(self):
        self.preview.get()
        self.preview.publish(self.frame)
        first = self.preview.get()
        self.assertEqual((first["width"], first["height"]), (640, 360))
        self.assertLessEqual(len(base64.b64decode(first["jpeg"])), 512 * 1024)
        self.frame.fill(99)
        self.now = 0.05
        self.preview.publish(self.frame)
        self.assertEqual(self.preview.get(), first)
        self.now = 0.11
        self.preview.publish(self.frame)
        second = self.preview.get()
        self.assertNotEqual(second, first)
        self.assertEqual(decode(second).shape, (360, 640, 3))
        self.assertTrue(np.all(decode(second) == 99))

    def test_portrait_small_and_noisy_bounds(self):
        random = np.random.default_rng(1)
        for shape, expected in (
            ((1280, 720, 3), (270, 480)),
            ((32, 48, 3), (48, 32)),
            ((960, 1280, 3), (640, 480)),
        ):
            with self.subTest(shape=shape):
                preview = NativePreview()
                preview.get()
                preview.publish(random.integers(0, 256, shape, dtype=np.uint8))
                result = preview.get()
                self.assertEqual((result["width"], result["height"]), expected)
                self.assertLessEqual(len(base64.b64decode(result["jpeg"])), 512 * 1024)

    def test_encoding_failures_and_oversized_payload_do_not_replace_frame(self):
        self.preview.get()
        self.preview.publish(self.frame)
        previous = self.preview.get()
        for outcome in (
            (False, None),
            (True, np.zeros(512 * 1024 + 1, dtype=np.uint8)),
            cv2.error("encode failed"),
        ):
            self.now += 0.2
            kwargs = (
                {"side_effect": outcome}
                if isinstance(outcome, Exception)
                else {"return_value": outcome}
            )
            with patch("webcam_mods.output.native_preview.cv2.imencode", **kwargs):
                self.preview.publish(self.frame)
            self.assertEqual(self.preview.get(), previous)

    def test_close_during_encode_rejects_late_frame(self):
        self.preview.get()
        entered, release = threading.Event(), threading.Event()
        original = cv2.imencode

        def blocked(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(*args)

        with patch(
            "webcam_mods.output.native_preview.cv2.imencode", side_effect=blocked
        ):
            thread = threading.Thread(target=self.preview.publish, args=(self.frame,))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.preview.close()
            finally:
                release.set()
                thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(self.preview.get())
        self.preview.publish(self.frame)
        self.assertIsNone(self.preview.get())


class PreviewPipelineTests(unittest.TestCase):
    def test_real_direct_and_repeated_frames_match_delivered_resized_output(self):
        for repeat in (False, True):
            with self.subTest(repeat=repeat):
                source, sink = Source(), RecordingOutput()
                preview = NativePreview()
                expected = resize_and_pad(source.original + 20, 96, 64)
                delivered = []

                def on_frame(frame):
                    np.testing.assert_array_equal(frame, sink.frames[-1])
                    delivered.append(frame.copy())
                    # request immediately before each candidate to exercise live encoding
                    preview.get()
                    preview.publish(frame)

                live_loop(
                    mod=lambda frame: frame + 20,
                    fIn=source,
                    fOut=sink,
                    interactive_listener=None,
                    strict_errors=True,
                    max_frames=12 if repeat else 2,
                    pace=repeat,
                    settings=StartupSettings(repeat_frames=repeat),
                    on_frame=on_frame,
                )
                self.assertEqual(len(delivered), len(sink.frames))
                np.testing.assert_array_equal(delivered[-1], expected)
                result = preview.get()
                encoded = cv2.imencode(
                    ".jpg", delivered[-1], [cv2.IMWRITE_JPEG_QUALITY, 75]
                )[1]
                self.assertEqual(base64.b64decode(result["jpeg"]), encoded.tobytes())
                self.assertEqual(decode(result).shape, (64, 96, 3))
                self.assertFalse(source.active)
                self.assertFalse(sink.is_setup())

    def test_headless_output_uses_negotiated_fps_and_never_opens_gui(self):
        with patch("cv2.namedWindow") as window, patch("cv2.imshow") as show:
            for repeat, fps in ((False, 15), (True, 60)):
                sink = default_frame_output(
                    15,
                    backend="native-preview",
                    settings=StartupSettings(max_out_fps=60, repeat_frames=repeat),
                )
                self.assertIsInstance(sink, NativePreviewOutput)
                self.assertEqual(sink.fps, fps)
                with sink:
                    self.assertTrue(sink.is_in_use())
                    sink.send(np.zeros((480, 640, 3), dtype=np.uint8))
                self.assertFalse(sink.is_setup())
            window.assert_not_called()
            show.assert_not_called()

    def test_run_profile_wires_preview_sink_and_final_frame_callback(self):
        callback = Mock()
        for output, backend in (
            ("preview", "native-preview"),
            ("virtualcam", "virtual-cam"),
        ):
            with (
                self.subTest(output=output),
                patch("webcam_mods.effects.ProfileEffect", return_value=Mock()),
                patch("webcam_mods.capture.create_camera", return_value=Source()),
                patch("webcam_mods.loopback.live_loop") as loop,
            ):
                run_profile(
                    Profile(),
                    threading.Event(),
                    lambda: None,
                    lambda source: None,
                    output=output,
                    on_frame=callback,
                )
                self.assertEqual(loop.call_args.kwargs["output_backend"], backend)
                self.assertIs(loop.call_args.kwargs["on_frame"], callback)


class PreviewControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ProfileStore(Path(temporary.name) / "profiles.db")

    def test_protocol_validation_and_idle_preview(self):
        controller = Controller(self.store, lambda event: None)
        self.assertIsNone(controller.dispatch("preview.get", {}))
        for params in ([], None, {"extra": True}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                controller.dispatch("preview.get", params)
        for output in (None, [], {}, True, "gui", "virtual-cam"):
            with (
                self.subTest(output=output),
                self.assertRaisesRegex(ValueError, "output"),
            ):
                controller.dispatch("start", {"output": output})
        self.assertEqual(controller.status(), {"state": "idle"})

    def test_stop_restart_and_error_clear_frames_and_reject_old_session_callback(self):
        callbacks, modes = [], []
        started, release = threading.Event(), threading.Event()
        fail = False

        def runner(profile, stop, ready, source_ready, *, output, on_frame):
            callbacks.append(on_frame)
            modes.append(output)
            ready()
            started.set()
            while not stop.wait(0.01) and not release.is_set():
                pass
            if fail:
                raise RuntimeError("synthetic failure")

        with patch("webcam_mods.control.run_profile", runner):
            controller = Controller(self.store, lambda event: None)
        frame = np.full((32, 48, 3), 77, dtype=np.uint8)
        for output in ("preview", "virtualcam"):
            started.clear()
            controller.dispatch("start", {"output": output})
            self.assertTrue(started.wait(1))
            self.assertIsNone(controller.dispatch("preview.get", {}))
            if len(callbacks) > 1:
                callbacks[0](frame)
                self.assertIsNone(controller.dispatch("preview.get", {}))
            callbacks[-1](frame)
            self.assertIsNotNone(controller.dispatch("preview.get", {}))
            controller.stop()
            self.assertIsNone(controller.dispatch("preview.get", {}))
            callbacks[-1](frame)
            self.assertIsNone(controller.dispatch("preview.get", {}))
        self.assertEqual(modes, ["preview", "virtualcam"])
        started.clear()
        controller.start(Profile())
        self.assertTrue(started.wait(1))
        controller.dispatch("preview.get", {})
        callbacks[-1](frame)
        self.assertIsNotNone(controller.dispatch("preview.get", {}))
        fail = True
        release.set()
        controller.thread.join(1)
        self.assertEqual(controller.status()["state"], "error")
        self.assertIsNone(controller.dispatch("preview.get", {}))

    def test_legacy_injected_runner_keeps_four_argument_contract(self):
        ready_event = threading.Event()

        def runner(profile, stop, ready, source_ready):
            ready()
            ready_event.set()
            stop.wait(1)

        controller = Controller(self.store, lambda event: None, runner)
        controller.dispatch("start", {"output": "preview"})
        self.assertTrue(ready_event.wait(1))
        self.assertEqual(controller.status()["state"], "running")
        controller.stop()


if __name__ == "__main__":
    unittest.main()
