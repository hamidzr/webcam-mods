"""Real Core Image fixture checks, without camera or desktop access."""

import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

from webcam_mods.macos.core_image import CoreImageProcessor


@unittest.skipUnless(
    sys.platform == "darwin" and importlib.util.find_spec("Quartz") is not None,
    "optional macOS Quartz bindings unavailable",
)
class CoreImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.processor = CoreImageProcessor()
        self.frame = cv2.imread(str(Path(__file__).parent / "fixtures/astronaut.png"))

    def tearDown(self) -> None:
        self.processor.close()

    def test_foreground_keeps_colors_and_orientation(self) -> None:
        result = self.processor.process(
            self.frame,
            np.ones(self.frame.shape[:2], dtype=np.float32),
            color=(4, 30, 190),
        )
        np.testing.assert_allclose(result, self.frame, atol=1)

    def test_zero_mask_replaces_background(self) -> None:
        result = self.processor.process(
            self.frame,
            np.zeros(self.frame.shape[:2], dtype=np.float32),
            color=(4, 30, 190),
        )
        np.testing.assert_allclose(
            result, np.broadcast_to([4, 30, 190], result.shape), atol=1
        )

    def test_spatial_mask_and_swapped_background(self) -> None:
        frame = np.zeros((32, 48, 3), dtype=np.uint8)
        frame[:] = [10, 70, 150]
        background = np.zeros((16, 24, 3), dtype=np.uint8)
        background[:8] = [180, 40, 10]
        background[8:] = [20, 180, 60]
        mask = np.zeros((32, 48), dtype=np.float32)
        mask[:, :24] = 1
        result = self.processor.process(frame, mask, background=background)
        np.testing.assert_allclose(result[:, :20], frame[:, :20], atol=1)
        np.testing.assert_allclose(result[4, 35], background[2, 18], atol=1)
        np.testing.assert_allclose(result[28, 35], background[14, 18], atol=1)

    def test_gaussian_blur_reuses_context(self) -> None:
        mask = np.zeros(self.frame.shape[:2], dtype=np.float32)
        result = self.processor.process(self.frame, mask, blur_radius=6)
        context = self.processor._context
        self.assertEqual(result.shape, self.frame.shape)
        self.assertLess(
            cv2.Laplacian(result, cv2.CV_64F).var(),
            cv2.Laplacian(self.frame, cv2.CV_64F).var(),
        )
        self.processor.process(self.frame, mask, blur_radius=3)
        self.assertIs(self.processor._context, context)

    def test_each_frame_uses_autorelease_pool(self) -> None:
        import objc
        from unittest.mock import patch

        with patch.object(
            objc, "autorelease_pool", wraps=objc.autorelease_pool
        ) as pool:
            self.processor.process(
                self.frame, np.ones(self.frame.shape[:2]), color=(0, 0, 0)
            )
            self.processor.process(
                self.frame, np.ones(self.frame.shape[:2]), color=(0, 0, 0)
            )
            self.assertEqual(pool.call_count, 2)

    def test_fractional_mask_matches_numeric_bgr_blending(self) -> None:
        for foreground, background in ((255, 128), (128, 255), (128, 0)):
            frame = np.full((7, 9, 3), foreground, dtype=np.uint8)
            mask = np.full((7, 9), 0.5, dtype=np.float32)
            result = self.processor.process(frame, mask, color=(background,) * 3)
            np.testing.assert_allclose(result, (foreground + background) / 2, atol=1)

    def test_closed_processor_cannot_reopen(self) -> None:
        self.processor.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.processor.process(
                self.frame, np.ones(self.frame.shape[:2]), color=(0, 0, 0)
            )

    def test_invalid_mask_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.processor.process(self.frame, np.ones((3, 3)), color=(0, 0, 0))
        with self.assertRaises(ValueError):
            self.processor.process(
                self.frame, np.full(self.frame.shape[:2], np.nan), color=(0, 0, 0)
            )


if __name__ == "__main__":
    unittest.main()
