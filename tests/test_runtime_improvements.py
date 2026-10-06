"""Pixel equivalence, bounded I/O and failure-path lifecycle regressions."""

from contextlib import ExitStack
from io import BytesIO
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from webcam_mods import models
from webcam_mods.frame_producer import FrameProducer, WorkerShutdownTimeout
from webcam_mods.input.input import FrameInput
from webcam_mods.mods.person_segmentation import apply_alpha_mask
from webcam_mods.mods.video_mods import brighten
from webcam_mods.session import Command
from webcam_mods.timing import FramePacer
from webcam_mods.utils.cli_input import StdinControls


class RuntimeImprovementTests(unittest.TestCase):
    def test_brightness_matches_saturated_hsv_reference(self) -> None:
        rng = np.random.default_rng(3)
        frame = rng.integers(0, 256, (24, 31, 3), np.uint8)
        levels = np.arange(256, dtype=np.uint8)
        gray = np.repeat(levels[None, :, None], 3, axis=2)
        for source in (frame, gray, frame[:, ::2]):
            original = source.copy()
            for amount in (0, 1, 30, 254, 255):
                hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
                hsv[:, :, 2] = np.minimum(hsv[:, :, 2].astype(np.uint16) + amount, 255)
                expected = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
                np.testing.assert_array_equal(brighten(source, amount), expected)
                np.testing.assert_array_equal(source, original)

    def test_blend_matches_float32_reference_and_preserves_inputs(self) -> None:
        rng = np.random.default_rng(4)
        foreground = rng.integers(0, 256, (12, 17, 3), np.uint8)[:, ::2]
        mask = rng.random(foreground.shape[:2], dtype=np.float32)
        for background in (
            np.array([255, 0, 127], np.float32),
            np.zeros_like(foreground),
        ):
            original = foreground.copy(), background.copy(), mask.copy()
            expected = (
                background.astype(np.float32)
                + (foreground.astype(np.float32) - background.astype(np.float32))
                * mask[:, :, None]
            )
            expected = np.clip(expected, 0, 255).astype(np.uint8)
            np.testing.assert_array_equal(
                apply_alpha_mask(foreground, background, mask), expected
            )
            for actual, before in zip((foreground, background, mask), original):
                np.testing.assert_array_equal(actual, before)

    def test_invalid_intervals_fail_before_event_callbacks(self) -> None:
        callback = Mock(return_value=False)
        pacer = FramePacer(30)
        for interval in (0, -1, float("nan"), float("inf")):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                pacer.wait(interval=interval, process_events=callback)
        callback.assert_not_called()

    def test_cancellation_failure_still_joins_worker(self) -> None:
        source = Mock(spec=FrameInput)
        source.request_stop.side_effect = OSError("cancel failed")
        producer = FrameProducer(source, shutdown_timeout=0.01)
        producer._thread = Mock(ident=1)
        producer._thread.is_alive.return_value = False
        with self.assertRaisesRegex(OSError, "cancel failed"):
            producer.close()
        producer._thread.join.assert_called_once_with(0.01)

    def test_cancellation_failure_keeps_timeout_cleanup_deferred(self) -> None:
        source = Mock(spec=FrameInput)
        source.request_stop.side_effect = OSError("cancel failed")
        producer = FrameProducer(source, shutdown_timeout=0.01)
        producer._thread = Mock(ident=1)
        producer._thread.is_alive.return_value = True
        with self.assertRaises(WorkerShutdownTimeout) as caught:
            producer.close()
        self.assertIs(caught.exception.__cause__, source.request_stop.side_effect)
        producer._thread.join.assert_called_once_with(0.01)

    def test_interrupted_join_preserves_worker_cleanup_ownership(self) -> None:
        source = Mock(spec=FrameInput)
        producer = FrameProducer(source, shutdown_timeout=0.01)
        producer._thread = Mock(ident=1)
        producer._thread.is_alive.return_value = True
        producer._thread.join.side_effect = KeyboardInterrupt()
        with self.assertRaises(WorkerShutdownTimeout) as caught:
            producer.close()
        self.assertIsInstance(caught.exception.__cause__, KeyboardInterrupt)

    def test_stdin_handles_fragmented_commands_and_eof(self) -> None:
        submit = Mock(return_value=True)
        controls = StdinControls(submit)
        with (
            patch(
                "webcam_mods.utils.cli_input.select.select",
                return_value=([3], [], []),
            ),
            patch(
                "webcam_mods.utils.cli_input.os.read",
                side_effect=[b"rec", b"ord\r\nrep", b"lay", b""],
            ),
        ):
            controls._read(3)
        self.assertEqual(
            submit.call_args_list,
            [
                unittest.mock.call(Command("record")),
                unittest.mock.call(Command("replay")),
            ],
        )

    def test_stdin_discards_entire_oversized_line_and_recovers(self) -> None:
        submit = Mock(return_value=True)
        controls = StdinControls(submit)
        with (
            patch(
                "webcam_mods.utils.cli_input.select.select", return_value=([3], [], [])
            ),
            patch(
                "webcam_mods.utils.cli_input.os.read",
                side_effect=[b"x" * 4096, b"x" * 4096, b"record\nstop\n", b""],
            ),
        ):
            controls._read(3)
        self.assertEqual(submit.call_args_list, [unittest.mock.call(Command("stop"))])

    def test_stdin_start_is_idempotent(self) -> None:
        stream = Mock()
        stream.fileno.return_value = 3
        controls = StdinControls(Mock(), stream)
        with patch("webcam_mods.utils.cli_input.Thread") as thread:
            thread.return_value.is_alive.return_value = True
            controls.start()
            controls.start()
            thread.assert_called_once()
            controls.stop()

    def test_models_stream_download_and_cached_checksum(self) -> None:
        content = b"model-data" * 20000
        checksum = hashlib.sha256(content).hexdigest()
        response = BytesIO(content)
        original_read = response.read
        reads = []

        def read(size: int = -1) -> bytes:
            self.assertGreater(size, 0)
            reads.append(size)
            return original_read(size)

        response.read = read
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    models._MODELS,
                    {"test": ("https://example.invalid/test.tflite", checksum)},
                )
            )
            stack.enter_context(patch.dict("os.environ", {"XDG_CACHE_HOME": directory}))
            download = stack.enter_context(
                patch.object(models, "urlopen", return_value=response)
            )
            path = models.model_path("test")
            self.assertEqual(path.read_bytes(), content)
            self.assertGreater(len(reads), 1)
            with patch.object(
                Path, "read_bytes", side_effect=AssertionError("unbounded read")
            ):
                self.assertEqual(models.model_path("test"), path)
            download.assert_called_once()

    def test_bad_model_checksum_preserves_cache_and_removes_temporary_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            cache = Path(directory) / "webcam-mods/models"
            cache.mkdir(parents=True)
            path = cache / "test.tflite"
            path.write_bytes(b"old corrupted cache")
            stack.enter_context(
                patch.dict(
                    models._MODELS,
                    {
                        "test": (
                            "https://example.invalid/test.tflite",
                            hashlib.sha256(b"valid").hexdigest(),
                        )
                    },
                )
            )
            stack.enter_context(patch.dict("os.environ", {"XDG_CACHE_HOME": directory}))
            stack.enter_context(
                patch.object(models, "urlopen", return_value=BytesIO(b"wrong"))
            )
            with self.assertRaisesRegex(ValueError, "checksum"):
                models.model_path("test")
            self.assertEqual(path.read_bytes(), b"old corrupted cache")
            self.assertEqual(list(cache.iterdir()), [path])

    def test_interrupted_download_removes_partial_file(self) -> None:
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = [b"partial", OSError("download failed")]
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    models._MODELS,
                    {"test": ("https://example.invalid/test.tflite", "unused")},
                )
            )
            stack.enter_context(patch.dict("os.environ", {"XDG_CACHE_HOME": directory}))
            stack.enter_context(patch.object(models, "urlopen", return_value=response))
            with self.assertRaisesRegex(OSError, "download failed"):
                models.model_path("test")
            self.assertEqual(
                list((Path(directory) / "webcam-mods/models").iterdir()), []
            )
