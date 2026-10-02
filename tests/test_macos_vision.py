"""Portable contract checks and optional real Apple Vision smoke tests."""

import importlib.util
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from webcam_mods.macos.vision import VisionSegmenter


class VisionContractTest(unittest.TestCase):
    def test_quality_rejected_before_native_initialization(self) -> None:
        with self.assertRaisesRegex(ValueError, "quality"):
            VisionSegmenter("invalid")

    def test_invalid_frames_rejected_before_native_initialization(self) -> None:
        segmenter = VisionSegmenter()
        for frame in (
            None,
            np.zeros((2, 2, 3), np.float32),
            np.zeros((2, 2), np.uint8),
            np.zeros((2, 2, 4), np.uint8),
            np.zeros((0, 2, 3), np.uint8),
        ):
            with self.subTest(shape=getattr(frame, "shape", None)):
                with self.assertRaisesRegex(ValueError, "BGR"):
                    segmenter.predict(frame)
        self.assertIsNone(segmenter._request)

    def test_non_macos_error_is_actionable(self) -> None:
        with patch("webcam_mods.macos.vision.sys.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "requires macOS"):
                VisionSegmenter().predict(np.zeros((2, 2, 3), np.uint8))

    def test_missing_bindings_error_is_actionable(self) -> None:
        with (
            patch("webcam_mods.macos.vision.sys.platform", "darwin"),
            patch.dict(sys.modules, {"Vision": None}),
        ):
            with self.assertRaisesRegex(RuntimeError, r"webcam-mods\[macos\]"):
                VisionSegmenter().predict(np.zeros((2, 2, 3), np.uint8))

    def test_native_inference_failure_propagates(self) -> None:
        segmenter = VisionSegmenter()
        segmenter._request = object()
        segmenter._objc = SimpleNamespace(autorelease_pool=nullcontext)
        handler = MagicMock()
        handler.performRequests_error_.return_value = (False, "native error")
        segmenter._vision = MagicMock()
        segmenter._vision.VNImageRequestHandler.alloc.return_value.initWithCVPixelBuffer_orientation_options_.return_value = (
            handler
        )
        with patch.object(segmenter, "_copy_input", return_value="buffer"):
            with self.assertRaisesRegex(RuntimeError, "native error"):
                segmenter.predict(np.zeros((2, 2, 3), np.uint8))

    def test_input_copy_preserves_bgr_and_padded_rows(self) -> None:
        memory = bytearray(32)
        q = SimpleNamespace(
            kCVPixelFormatType_32BGRA=123,
            CVPixelBufferCreate=lambda *args: (0, "buffer"),
            CVPixelBufferLockBaseAddress=lambda buffer, flags: 0,
            CVPixelBufferUnlockBaseAddress=MagicMock(),
            CVPixelBufferGetBytesPerRow=lambda buffer: 16,
            CVPixelBufferGetBaseAddress=lambda buffer: SimpleNamespace(
                as_buffer=lambda size: memoryview(memory)[:size]
            ),
        )
        segmenter = VisionSegmenter()
        segmenter._quartz = q
        frame = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)[:, ::-1]
        segmenter._copy_input(frame)
        pixels = np.ndarray((2, 3, 4), np.uint8, buffer=memory, strides=(16, 4, 1))
        np.testing.assert_array_equal(pixels[:, :, :3], frame)
        np.testing.assert_array_equal(pixels[:, :, 3], 255)
        self.assertEqual(memory[12:16], bytearray(4))
        q.CVPixelBufferUnlockBaseAddress.assert_called_once_with("buffer", 0)

    def test_close_releases_request_and_disallows_reuse(self) -> None:
        segmenter = VisionSegmenter()
        request = MagicMock()
        segmenter._request = request
        segmenter._buffer = object()
        segmenter.close()
        segmenter.close()
        request.cancel.assert_called_once()
        self.assertIsNone(segmenter._request)
        self.assertIsNone(segmenter._buffer)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            segmenter.predict(np.zeros((2, 2, 3), np.uint8))

    def test_mask_copy_respects_padding_and_owns_memory(self) -> None:
        memory = bytearray(32)
        original = np.ndarray((2, 3), np.float32, buffer=memory, strides=(16, 4))
        original[:] = [[0, 0.25, 0.5], [0.75, 1, 0.5]]
        q = SimpleNamespace(
            kCVPixelBufferLock_ReadOnly=1,
            kCVPixelFormatType_OneComponent32Float=123,
            CVPixelBufferLockBaseAddress=lambda buffer, flags: 0,
            CVPixelBufferUnlockBaseAddress=MagicMock(),
            CVPixelBufferGetPixelFormatType=lambda buffer: 123,
            CVPixelBufferGetHeight=lambda buffer: 2,
            CVPixelBufferGetWidth=lambda buffer: 3,
            CVPixelBufferGetBytesPerRow=lambda buffer: 16,
            CVPixelBufferGetBaseAddress=lambda buffer: SimpleNamespace(
                as_buffer=lambda size: memoryview(memory)[:size]
            ),
        )
        segmenter = VisionSegmenter()
        segmenter._quartz = q
        result = segmenter._copy_mask("buffer")
        np.testing.assert_array_equal(result, original)
        original[:] = 0
        self.assertEqual(result[1, 1], 1)
        q.CVPixelBufferUnlockBaseAddress.assert_called_once_with("buffer", 1)

    def test_mask_unlocks_when_format_invalid(self) -> None:
        q = SimpleNamespace(
            kCVPixelBufferLock_ReadOnly=1,
            kCVPixelFormatType_OneComponent32Float=123,
            CVPixelBufferLockBaseAddress=lambda buffer, flags: 0,
            CVPixelBufferUnlockBaseAddress=MagicMock(),
            CVPixelBufferGetPixelFormatType=lambda buffer: 456,
        )
        segmenter = VisionSegmenter()
        segmenter._quartz = q
        with self.assertRaisesRegex(RuntimeError, "pixel format"):
            segmenter._copy_mask("buffer")
        q.CVPixelBufferUnlockBaseAddress.assert_called_once_with("buffer", 1)


@unittest.skipUnless(
    sys.platform == "darwin" and importlib.util.find_spec("Vision") is not None,
    "requires macOS and optional PyObjC Vision bindings",
)
class NativeVisionTest(unittest.TestCase):
    def test_blank_and_astronaut_all_quality_levels(self) -> None:
        image = cv2.imread(str(Path(__file__).parent / "fixtures" / "astronaut.png"))
        self.assertIsNotNone(image)
        for quality in ("fast", "balanced", "accurate"):
            with self.subTest(quality=quality):
                segmenter = VisionSegmenter(quality)
                try:
                    blank = segmenter.predict(np.zeros((240, 321, 3), np.uint8))
                    self.assertEqual(blank.shape, (240, 321))
                    self.assertLess(float(blank.mean()), 0.02)
                    mask = segmenter.predict(image)
                    self.assertEqual(mask.shape, image.shape[:2])
                    self.assertEqual(mask.dtype, np.float32)
                    self.assertTrue(np.isfinite(mask).all())
                    self.assertGreater(float(mask.max()), 0.9)
                    self.assertGreater(float(mask[150:250, 200:280].mean()), 0.7)
                    self.assertLess(float(mask[:80, 400:].mean()), 0.1)
                    saved = mask.copy()
                    # odd dimensions and negative strides exercise input layout handling
                    segmenter.predict(image[::-2, ::-2])
                    np.testing.assert_array_equal(mask, saved)
                finally:
                    segmenter.close()


if __name__ == "__main__":
    unittest.main()
