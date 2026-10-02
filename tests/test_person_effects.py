"""Portable blending, backend isolation and native integration regressions."""

import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

from webcam_mods.mods.person_segmentation import PersonEffects, apply_alpha_mask


class BlendTests(unittest.TestCase):
    def test_single_channel_blend_matches_reference_and_does_not_mutate(self) -> None:
        rng = np.random.default_rng(10)
        foreground = rng.integers(0, 256, (12, 17, 3), dtype=np.uint8)
        background = rng.integers(0, 256, foreground.shape, dtype=np.uint8)
        mask = rng.random((12, 17, 1), dtype=np.float32)
        original = foreground.copy()
        reference = (
            foreground * mask.astype(float) + background * (1 - mask.astype(float))
        ).astype(np.uint8)
        actual = apply_alpha_mask(foreground, background, mask)
        self.assertLessEqual(
            np.abs(actual.astype(int) - reference.astype(int)).max(), 1
        )
        np.testing.assert_array_equal(original, foreground)

    def test_native_close_failure_releases_segmenter_reference(self) -> None:
        from unittest.mock import Mock

        effects = PersonEffects()
        handle = Mock()
        handle.close.side_effect = RuntimeError("native close failed")
        effects.segmenter._segmenter = handle
        with self.assertRaisesRegex(RuntimeError, "native close failed"):
            effects.close()
        self.assertIsNone(effects.segmenter._segmenter)
        effects.close()
        handle.close.assert_called_once()

    def test_instance_close_prevents_reuse(self) -> None:
        first, second = PersonEffects(), PersonEffects()
        self.assertIsNot(first.segmenter, second.segmenter)
        first.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            first.mask(np.zeros((2, 2, 3), np.uint8))
        second.close()


@unittest.skipUnless(
    sys.platform == "darwin" and importlib.util.find_spec("Vision") is not None,
    "optional macOS Vision bindings unavailable",
)
class NativeEffectIntegrationTests(unittest.TestCase):
    def test_native_backends_mirror_once_and_preserve_person(self) -> None:
        frame = cv2.imread(str(Path(__file__).parent / "fixtures/astronaut.png"))
        for processing in ("opencv", "coreimage"):
            with self.subTest(processing=processing):
                effects = PersonEffects(backend="vision", processing=processing)
                try:
                    result = effects.color_bg(frame, (0, 255, 0))
                    mirrored = cv2.flip(frame, 1)
                    face = np.s_[85:125, 270:300]
                    self.assertLess(
                        np.abs(result[face].astype(float) - mirrored[face]).mean(), 5
                    )
                    background = np.s_[10:40, 10:40]
                    self.assertLess(
                        np.abs(result[background].astype(float) - (0, 255, 0)).mean(),
                        10,
                    )
                    swapped = effects.swap_bg(
                        frame, np.full((16, 32, 3), (80, 10, 220), np.uint8)
                    )
                    self.assertEqual(swapped.shape, frame.shape)
                finally:
                    effects.close()
