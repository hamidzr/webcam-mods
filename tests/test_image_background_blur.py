"""Static image blur is prepared once, while foreground frames stay live."""

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from webcam_mods.mods.person_segmentation import PersonEffects


class ImageBackgroundBlurTests(unittest.TestCase):
    def test_blur_cache_reused_and_invalidated(self) -> None:
        background = np.random.default_rng(42).integers(
            0, 256, (8, 10, 3), dtype=np.uint8
        )
        source = background.copy()
        effects = PersonEffects()
        self.addCleanup(effects.close)
        effects.set_background(background, blur_kernel=3)
        background.fill(0)
        original_blur = cv2.blur
        with (
            patch.object(effects, "mask") as mask,
            patch(
                "webcam_mods.mods.person_segmentation.cv2.blur", wraps=cv2.blur
            ) as blur,
        ):
            for height, width in ((4, 6), (4, 6), (6, 4), (6, 4)):
                frame = np.full((height, width, 3), 213, np.uint8)
                alpha = np.zeros((height, width, 1), np.float32)
                alpha[:, :2] = 1
                mask.return_value = frame, alpha
                expected = original_blur(cv2.resize(source, (width, height)), (3, 3))
                result = effects.swap_bg(frame)
                np.testing.assert_array_equal(result[:, :2], frame[:, :2])
                np.testing.assert_array_equal(result[:, 2:], expected[:, 2:])
            self.assertEqual(blur.call_count, 2)
            cached = effects._background
            effects.swap_bg(frame)
            self.assertIs(effects._background, cached)
            self.assertEqual(blur.call_count, 2)

            effects.set_background(source, blur_kernel=5)
            effects.swap_bg(frame)
            self.assertEqual(blur.call_count, 3)
            self.assertEqual(blur.call_args.args[1], (5, 5))
            effects.set_background(np.full_like(source, 73), blur_kernel=5)
            result = effects.swap_bg(frame)
            np.testing.assert_array_equal(result[:, 2:], 73)
            self.assertEqual(blur.call_count, 4)

    def test_default_background_skips_blur(self) -> None:
        effects = PersonEffects()
        self.addCleanup(effects.close)
        frame = np.zeros((4, 6, 3), np.uint8)
        effects.set_background(np.full_like(frame, 42))
        with (
            patch.object(effects, "mask", return_value=(frame, np.zeros((4, 6, 1)))),
            patch("webcam_mods.mods.person_segmentation.cv2.blur") as blur,
        ):
            np.testing.assert_array_equal(effects.swap_bg(frame), 42)
            effects.swap_bg(frame)
            blur.assert_not_called()

    def test_coreimage_composites_cached_pixels_without_live_blur(self) -> None:
        effects = PersonEffects()
        self.addCleanup(effects.close)
        effects.processor = Mock()
        frame = np.zeros((4, 6, 3), np.uint8)
        effects.set_background(np.full_like(frame, 42), blur_kernel=3)
        with (
            patch.object(effects, "mask", return_value=(frame, np.zeros((4, 6, 1)))),
            patch(
                "webcam_mods.mods.person_segmentation.cv2.blur", wraps=cv2.blur
            ) as blur,
        ):
            effects.swap_bg(frame)
            effects.swap_bg(frame)
            blur.assert_called_once()
        first, second = effects.processor.process.call_args_list
        self.assertIs(first.kwargs["background"], second.kwargs["background"])
        self.assertNotIn("blur_radius", first.kwargs)

    def test_invalid_kernel_preserves_cached_background(self) -> None:
        effects = PersonEffects()
        self.addCleanup(effects.close)
        background = np.full((4, 6, 3), 42, np.uint8)
        effects.set_background(background, blur_kernel=3)
        for kernel in (0, -1, 2, True, 3.0):
            with self.subTest(kernel=kernel), self.assertRaises(ValueError):
                effects.set_background(np.zeros_like(background), blur_kernel=kernel)
            np.testing.assert_array_equal(effects._background_source, background)
            self.assertEqual(effects._background_blur_kernel, 3)


if __name__ == "__main__":
    unittest.main()
