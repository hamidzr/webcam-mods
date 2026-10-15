"""Noise reduction on static scenes, motion passthrough and state ownership."""

import unittest

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.denoise import TemporalDenoiser
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings

SHAPE = (48, 64, 3)


def noisy(
    scene: np.ndarray, rng: np.random.Generator, sigma: float = 10.0
) -> np.ndarray:
    return np.clip(scene + rng.normal(0, sigma, scene.shape), 0, 255).astype(np.uint8)


def gradient_scene() -> np.ndarray:
    ramp = np.linspace(80, 170, SHAPE[1], dtype=np.float32)
    return np.broadcast_to(ramp[None, :, None], SHAPE).copy()


def mean_abs_error(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean())


class TemporalDenoiserTests(unittest.TestCase):
    def test_static_noise_is_reduced(self) -> None:
        rng = np.random.default_rng(1)
        scene = gradient_scene()
        denoiser = TemporalDenoiser()
        raw, out = [], []
        for _ in range(20):
            frame = noisy(scene, rng)
            raw.append(frame.astype(np.float32) - scene)
            out.append(denoiser(frame).astype(np.float32) - scene)
        self.assertLess(np.std(out[-5:]), 0.6 * np.std(raw[-5:]))

    def test_strength_orders_noise_reduction(self) -> None:
        scene = gradient_scene()

        def residual(strength: int) -> float:
            rng = np.random.default_rng(2)
            denoiser = TemporalDenoiser(strength)
            out = [
                denoiser(noisy(scene, rng)).astype(np.float32) - scene
                for _ in range(30)
            ]
            return float(np.std(out[-5:]))

        self.assertLess(residual(100), residual(50))
        self.assertLess(residual(50), residual(20))

    def test_scene_change_follows_new_frame_immediately(self) -> None:
        rng = np.random.default_rng(3)
        old = np.full(SHAPE, 60, np.float32)
        new = np.full(SHAPE, 180, np.float32)
        denoiser = TemporalDenoiser(100)
        for _ in range(15):
            denoiser(noisy(old, rng))
        for _ in range(2):
            frame = noisy(new, rng)
            result = denoiser(frame)
        self.assertLess(mean_abs_error(result, new), 10.0)

    def test_moving_object_leaves_no_ghost(self) -> None:
        rng = np.random.default_rng(4)
        background = gradient_scene()
        denoiser = TemporalDenoiser(100)
        for _ in range(15):
            denoiser(noisy(background, rng))
        with_object = background.copy()
        with_object[10:30, 10:30] = 250
        denoiser(noisy(with_object, rng))
        result = denoiser(noisy(background, rng))
        self.assertLess(
            mean_abs_error(result[12:28, 12:28], background[12:28, 12:28]), 12.0
        )
        # object entering is shown at once, not faded in
        result = denoiser(noisy(with_object, rng))
        self.assertGreater(float(result[12:28, 12:28].mean()), 235.0)

    def test_strength_zero_is_identity(self) -> None:
        rng = np.random.default_rng(5)
        denoiser = TemporalDenoiser(0)
        for _ in range(3):
            frame = noisy(gradient_scene(), rng)
            result = denoiser(frame)
            np.testing.assert_array_equal(result, frame)
            self.assertIsNot(result, frame)

    def test_configure_validates_and_zero_drops_history(self) -> None:
        denoiser = TemporalDenoiser()
        for bad in (-1, 101, 50.0, True, "50"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                denoiser.configure(bad)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            TemporalDenoiser(200)
        rng = np.random.default_rng(6)
        for _ in range(5):
            denoiser(noisy(gradient_scene(), rng))
        denoiser.configure(0)
        denoiser.configure(50)
        frame = noisy(gradient_scene(), rng)
        np.testing.assert_array_equal(denoiser(frame), frame)

    def test_reset_makes_next_frame_pass_through(self) -> None:
        rng = np.random.default_rng(7)
        denoiser = TemporalDenoiser()
        for _ in range(5):
            denoiser(noisy(gradient_scene(), rng))
        denoiser.reset()
        frame = noisy(gradient_scene(), rng)
        np.testing.assert_array_equal(denoiser(frame), frame)

    def test_shape_change_resets_automatically(self) -> None:
        rng = np.random.default_rng(8)
        denoiser = TemporalDenoiser()
        for _ in range(5):
            denoiser(noisy(gradient_scene(), rng))
        small = noisy(np.full((24, 32, 3), 100, np.float32), rng)
        np.testing.assert_array_equal(denoiser(small), small)
        original_size = noisy(gradient_scene(), rng)
        np.testing.assert_array_equal(denoiser(original_size), original_size)

    def test_dtype_shape_and_input_ownership(self) -> None:
        rng = np.random.default_rng(9)
        denoiser = TemporalDenoiser()
        for _ in range(4):
            frame = noisy(gradient_scene(), rng)
            original = frame.copy()
            result = denoiser(frame)
            np.testing.assert_array_equal(frame, original)
            self.assertEqual(result.dtype, np.uint8)
            self.assertEqual(result.shape, SHAPE)
            result[:] = 0
            np.testing.assert_array_equal(frame, original)
        # mutating a returned frame must not corrupt the history
        result = denoiser(noisy(gradient_scene(), rng))
        self.assertGreater(float(result.mean()), 80.0)

    def test_rejects_malformed_frames(self) -> None:
        denoiser = TemporalDenoiser()
        with self.assertRaises(ValueError):
            denoiser(np.zeros((8, 8, 3), np.float32))
        with self.assertRaises(ValueError):
            denoiser(np.zeros((8, 8), np.uint8))


class ProfileDenoiseTests(unittest.TestCase):
    def test_field_is_validated_and_live(self) -> None:
        self.assertEqual(Profile.parse({"denoise": 70}).denoise, 70)
        for bad in (-1, 101, 2.5, True):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "denoise"):
                Profile.parse({"denoise": bad})
        self.assertNotIn("denoise", RESTART_FIELDS)

    def test_effect_averages_the_whole_camera_frame_before_framing(self) -> None:
        rng = np.random.default_rng(5)
        scene = gradient_scene()
        effect = ProfileEffect(
            Profile(denoise=80, crop=(0.25, 0.25, 0.5, 0.5)),
            StartupSettings(out_width=32, out_height=24),
        )
        self.addCleanup(effect.close)
        for _ in range(15):
            frame = noisy(scene, rng)
            out = effect(frame)
        assert out is not None
        crop = scene[12:36, 16:48]
        self.assertEqual(out.shape, crop.shape)
        self.assertLess(
            np.std(out.astype(np.float32) - crop),
            0.6 * np.std(frame[12:36, 16:48].astype(np.float32) - crop),
        )
        # white balance and the camera view keep the raw picture
        self.assertIs(effect._source, frame)
        effect.update(Profile(crop=(0.25, 0.25, 0.5, 0.5)))
        frame = noisy(scene, rng)
        out = effect(frame)
        assert out is not None
        np.testing.assert_array_equal(out, frame[12:36, 16:48])

    def test_screens_are_not_averaged(self) -> None:
        rng = np.random.default_rng(6)
        effect = ProfileEffect(
            Profile(denoise=100, source="screen", screen_region=(0, 0, 64, 48)),
            StartupSettings(out_width=64, out_height=48),
        )
        self.addCleanup(effect.close)
        for _ in range(3):
            frame = noisy(gradient_scene(), rng)
            np.testing.assert_array_equal(effect(frame), frame)


if __name__ == "__main__":
    unittest.main()
