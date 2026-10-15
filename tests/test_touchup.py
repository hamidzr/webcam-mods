"""Skin smoothing strength, skin restriction and edge preservation."""

import unittest

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.touchup import smooth_skin
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings

SKIN = (130, 165, 200)
BLUE = (200, 60, 40)


def noisy_patch(color: tuple[int, int, int], seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = np.empty((96, 96, 3), np.float32)
    base[:] = color
    return np.clip(base + rng.normal(0, 12, base.shape), 0, 255).astype(np.uint8)


def core(frame: np.ndarray) -> np.ndarray:
    return frame[16:80, 16:80].astype(np.float32)


def noise_std(frame: np.ndarray) -> float:
    # per-channel spread, so the channel offsets of a flat color do not count
    return float(core(frame).reshape(-1, 3).std(axis=0).mean())


class SmoothSkinTests(unittest.TestCase):
    def test_strength_zero_returns_unchanged_copy(self) -> None:
        frame = noisy_patch(SKIN)
        result = smooth_skin(frame, 0)
        np.testing.assert_array_equal(result, frame)
        self.assertIsNot(result, frame)

    def test_noisy_skin_variance_drops(self) -> None:
        frame = noisy_patch(SKIN)
        result = smooth_skin(frame, 60)
        self.assertLess(noise_std(result), 0.5 * noise_std(frame))
        self.assertAlmostEqual(
            float(core(result).mean()), float(core(frame).mean()), delta=3.0
        )

    def test_strength_orders_smoothing(self) -> None:
        frame = noisy_patch(SKIN)
        stds = [noise_std(smooth_skin(frame, s)) for s in (10, 50, 100)]
        self.assertGreater(stds[0], stds[1])
        self.assertGreater(stds[1], stds[2])
        self.assertLess(stds[0], noise_std(frame))

    def test_non_skin_patch_is_untouched(self) -> None:
        frame = noisy_patch(BLUE)
        result = smooth_skin(frame, 100)
        self.assertLess(float(np.abs(core(result) - core(frame)).max()), 2.0)
        self.assertAlmostEqual(noise_std(result), noise_std(frame), delta=0.5)

    def test_skin_non_skin_edge_preserved(self) -> None:
        frame = np.empty((64, 96, 3), np.uint8)
        frame[:, :48] = SKIN
        frame[:, 48:] = BLUE
        rng = np.random.default_rng(1)
        frame = np.clip(frame + rng.normal(0, 8, frame.shape), 0, 255).astype(np.uint8)
        result = smooth_skin(frame, 100).astype(np.float32)
        source = frame.astype(np.float32)
        rows = slice(12, 52)
        before = np.abs(source[rows, 52:60].mean() - source[rows, 36:44].mean())
        after = np.abs(result[rows, 52:60].mean() - result[rows, 36:44].mean())
        self.assertGreater(after, 0.95 * before)
        # the transition stays sharp: columns beside the edge stay near their side
        left = result[rows, 44:47].mean(axis=(0, 1))
        right = result[rows, 49:52].mean(axis=(0, 1))
        self.assertLess(float(np.abs(left - np.array(SKIN)).max()), 12.0)
        self.assertLess(float(np.abs(right - np.array(BLUE)).max()), 12.0)

    def test_features_inside_skin_stay_sharp(self) -> None:
        # a brow-like line: too faint for the bilateral filter to keep on its own
        frame = noisy_patch(SKIN, seed=4)
        frame[44:50, 16:80] = (95, 125, 165)
        result = smooth_skin(frame, 100).astype(np.float32)
        source = frame.astype(np.float32)

        def contrast(image: np.ndarray) -> float:
            return float(image[36:42, 24:72].mean() - image[45:49, 24:72].mean())

        self.assertGreater(contrast(result), 0.9 * contrast(source))

    def test_non_skin_pixels_beside_skin_barely_change(self) -> None:
        frame = np.empty((64, 96, 3), np.uint8)
        frame[:] = BLUE
        frame[:, :32] = SKIN
        result = smooth_skin(frame, 100)
        np.testing.assert_array_equal(result[:, 48:], frame[:, 48:])

    def test_shape_dtype_and_input_ownership(self) -> None:
        frame = noisy_patch(SKIN)
        original = frame.copy()
        result = smooth_skin(frame, 70)
        self.assertEqual(result.shape, frame.shape)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(frame, original)
        result[:] = 0
        np.testing.assert_array_equal(frame, original)

    def test_odd_and_tiny_sizes(self) -> None:
        for shape in ((33, 47, 3), (3, 5, 3), (1, 1, 3), (2, 7, 3)):
            with self.subTest(shape=shape):
                frame = np.empty(shape, np.uint8)
                frame[:] = SKIN
                result = smooth_skin(frame, 80)
                self.assertEqual(result.shape, shape)
                self.assertLess(float(np.abs(result.astype(int) - frame).max()), 3.0)

    def test_validates_arguments(self) -> None:
        frame = noisy_patch(SKIN)
        for bad in (-1, 101, 50.0, True, "50"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                smooth_skin(frame, bad)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            smooth_skin(np.zeros((8, 8, 3), np.float32), 50)
        with self.assertRaises(ValueError):
            smooth_skin(np.zeros((8, 8), np.uint8), 50)


class ProfileTouchupTests(unittest.TestCase):
    def test_field_is_validated_and_live(self) -> None:
        self.assertEqual(Profile.parse({"touchup": 40}).touchup, 40)
        for bad in (-1, 101, 2.5, True, "40"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "touchup"):
                Profile.parse({"touchup": bad})
        self.assertNotIn("touchup", RESTART_FIELDS)

    def test_effect_smooths_the_camera_picture_live(self) -> None:
        frame = noisy_patch(SKIN)
        effect = ProfileEffect(Profile(), StartupSettings(out_width=96, out_height=96))
        self.addCleanup(effect.close)
        plain = effect(frame)
        assert plain is not None
        np.testing.assert_array_equal(plain, frame)
        effect.update(Profile(touchup=80))
        smoothed = effect(frame)
        assert smoothed is not None
        self.assertLess(noise_std(smoothed), 0.6 * noise_std(frame))


if __name__ == "__main__":
    unittest.main()
