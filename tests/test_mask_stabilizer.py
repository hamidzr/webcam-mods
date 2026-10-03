"""Jitter reduction, immediate motion response and run ownership regressions."""

import unittest
from unittest.mock import Mock

import numpy as np

from webcam_mods.mods.mask_stabilizer import MaskStabilizer
from webcam_mods.mods.person_segmentation import PersonEffects


class MaskStabilizerTests(unittest.TestCase):
    def test_static_noise_reduced_without_spatial_detail_loss(self) -> None:
        frame = np.zeros((32, 32, 3), np.uint8)
        base = np.zeros((32, 32), np.float32)
        base[:, 16:] = 0.8
        rng = np.random.default_rng(42)
        stabilizer = MaskStabilizer()
        raw, smooth = [], []
        for _ in range(100):
            mask = np.clip(base + rng.normal(0, 0.025, base.shape), 0, 1).astype(
                np.float32
            )
            raw.append(mask)
            smooth.append(stabilizer.apply(frame, mask))
        self.assertLess(
            np.std(smooth[10:], axis=0).mean(), np.std(raw[10:], axis=0).mean() * 0.6
        )
        self.assertGreater(np.mean(smooth[-1][:, 16]), 0.7)
        self.assertLess(np.mean(smooth[-1][:, 15]), 0.05)

    def test_binary_boundary_jitter_smooths_on_static_image(self) -> None:
        frame = np.zeros((32, 32, 3), np.uint8)
        stabilizer = MaskStabilizer()
        mask = np.zeros((32, 32), np.float32)
        mask[:, 16:] = 1
        stabilizer.apply(frame, mask)
        mask[:, 15] = 1
        result = stabilizer.apply(frame, mask)
        np.testing.assert_allclose(result[:, 15], 0.35)
        np.testing.assert_array_equal(result[:, 16:], mask[:, 16:])

    def test_departure_and_confidence_jump_take_effect_immediately(self) -> None:
        frame = np.zeros((8, 8, 3), np.uint8)
        stabilizer = MaskStabilizer()
        stabilizer.apply(frame, np.ones((8, 8), np.float32))
        empty = np.zeros((8, 8), np.float32)
        np.testing.assert_array_equal(stabilizer.apply(frame, empty), empty)

    def test_visible_motion_resets_even_small_confidence_changes(self) -> None:
        frame = np.zeros((32, 32, 3), np.uint8)
        stabilizer = MaskStabilizer()
        stabilizer.apply(frame, np.full((32, 32), 0.5, np.float32))
        frame[3:5, 3:5] = 255
        mask = np.full((32, 32), 0.6, np.float32)
        result = stabilizer.apply(frame, mask)
        np.testing.assert_array_equal(result[2:6, 2:6], mask[2:6, 2:6])
        self.assertAlmostEqual(float(result[0, 0]), 0.535)

    def test_hand_motion_keeps_stationary_boundary_stable(self) -> None:
        frame = np.zeros((100, 100, 3), np.uint8)
        mask = np.zeros((100, 100), np.float32)
        mask[:, 70:] = 1
        stabilizer = MaskStabilizer()
        stabilizer.apply(frame, mask)
        # moving hand covers more than 2% of image, away from static shoulder
        frame[20:40, 20:40] = 255
        mask[20:40, 20:40] = 1
        mask[:, 69] = 1
        result = stabilizer.apply(frame, mask)
        np.testing.assert_array_equal(result[20:40, 20:40], mask[20:40, 20:40])
        np.testing.assert_allclose(result[:, 69], 0.35)
        np.testing.assert_array_equal(result[:, 70:], mask[:, 70:])
        # departing hand must clear immediately without destabilizing shoulder
        frame[20:40, 20:40] = 0
        mask[20:40, 20:40] = 0
        mask[:, 69] = 0
        result = stabilizer.apply(frame, mask)
        np.testing.assert_array_equal(result[20:40, 20:40], mask[20:40, 20:40])
        np.testing.assert_allclose(result[:, 69], 0.2275)

    def test_widespread_motion_resets_changed_pixels(self) -> None:
        frame = np.zeros((32, 32, 3), np.uint8)
        stabilizer = MaskStabilizer()
        stabilizer.apply(frame, np.full((32, 32), 0.5, np.float32))
        frame[:] = 255
        mask = np.full((32, 32), 0.6, np.float32)
        np.testing.assert_array_equal(stabilizer.apply(frame, mask), mask)

    def test_shape_change_reset_and_input_ownership(self) -> None:
        stabilizer = MaskStabilizer()
        frame = np.zeros((8, 8, 3), np.uint8)
        mask = np.full((8, 8), 0.5, np.float32)
        result = stabilizer.apply(frame, mask)
        result[:] = 0
        mask[:] = 1
        self.assertAlmostEqual(
            float(stabilizer.apply(frame, np.full((8, 8), 0.5, np.float32))[0, 0]), 0.5
        )
        smaller = np.zeros((4, 4), np.float32)
        np.testing.assert_array_equal(stabilizer.apply(frame[:4, :4], smaller), smaller)
        stabilizer.reset()
        np.testing.assert_array_equal(stabilizer.apply(frame, mask), mask)
        with self.assertRaises(ValueError):
            stabilizer.apply(frame, smaller)

    def test_effect_opt_in_and_close_release_history(self) -> None:
        default = PersonEffects()
        self.assertIsNone(default.stabilizer)
        default.close()
        effects = PersonEffects(backend="vision", smoothing=True)
        effects.segmenter = Mock()
        effects.segmenter.predict.return_value = np.full((8, 8), 0.5, np.float32)
        image, mask = effects.mask(np.zeros((8, 8, 3), np.uint8))
        self.assertEqual(mask.shape, (8, 8, 1))
        self.assertIsNotNone(effects.stabilizer._mask)
        effects.close()
        self.assertIsNone(effects.stabilizer._mask)
        effects.segmenter.close.assert_called_once()
