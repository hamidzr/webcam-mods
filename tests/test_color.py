"""Color adjustment and auto light behavior on synthetic frames."""

import math
import unittest

import numpy as np

from webcam_mods.mods.color import (
    AutoLight,
    ColorAdjuster,
    ColorSettings,
    neutral_balance,
)
from webcam_mods.utils.video import Frame


def solid(b: int, g: int, r: int, shape: tuple[int, int] = (48, 64)) -> Frame:
    frame = np.empty((*shape, 3), np.uint8)
    frame[:] = (b, g, r)
    return frame


def random_frame(seed: int = 1, shape: tuple[int, int] = (48, 64)) -> Frame:
    return np.random.default_rng(seed).integers(0, 256, (*shape, 3), np.uint8)


def adjust(frame: Frame, **fields: float) -> Frame:
    return ColorAdjuster(ColorSettings(**fields))(frame)  # type: ignore[arg-type]


def mean_bgr(frame: Frame) -> tuple[float, float, float]:
    b, g, r = frame.reshape(-1, 3).mean(axis=0)
    return float(b), float(g), float(r)


class ColorSettingsTests(unittest.TestCase):
    def test_defaults_are_identity(self) -> None:
        self.assertTrue(ColorSettings().is_identity())
        for field in ("contrast", "saturation", "temperature", "tint", "sharpness"):
            self.assertFalse(ColorSettings(**{field: 1}).is_identity())
        self.assertFalse(ColorSettings(exposure=0.5).is_identity())

    def test_accepts_bounds_and_normalizes_exposure(self) -> None:
        ColorSettings(-2.0, -100, -100, -100, -100, 0)
        ColorSettings(2.0, 100, 100, 100, 100, 100)
        settings = ColorSettings(exposure=1)
        self.assertIsInstance(settings.exposure, float)
        self.assertEqual(settings, ColorSettings(exposure=1.0))

    def test_rejects_out_of_range(self) -> None:
        bad: list[dict[str, float]] = [
            {"exposure": 2.01},
            {"exposure": -2.01},
            {"contrast": 101},
            {"contrast": -101},
            {"saturation": 101},
            {"saturation": -101},
            {"temperature": 101},
            {"temperature": -101},
            {"tint": 101},
            {"tint": -101},
            {"sharpness": 101},
            {"sharpness": -1},
        ]
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ColorSettings(**fields)  # type: ignore[arg-type]

    def test_rejects_wrong_types(self) -> None:
        bad: list[dict[str, object]] = [
            {"contrast": True},
            {"sharpness": True},
            {"temperature": 1.5},
            {"tint": "5"},
            {"saturation": None},
            {"exposure": True},
            {"exposure": "1"},
            {"exposure": math.nan},
            {"exposure": math.inf},
            {"exposure": -math.inf},
        ]
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ColorSettings(**fields)  # type: ignore[arg-type]

    def test_error_names_the_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "temperature"):
            ColorSettings(temperature=500)


class ColorAdjusterTests(unittest.TestCase):
    def test_identity_returns_input_pixels(self) -> None:
        frame = random_frame()
        out = ColorAdjuster()(frame)
        np.testing.assert_array_equal(out, frame)
        out = ColorAdjuster(ColorSettings())(frame)
        self.assertIs(out, frame)

    def test_neutral_lut_is_pixel_exact(self) -> None:
        # exposure of zero but another lut stage forces the table path
        frame = random_frame(2)
        np.testing.assert_array_equal(adjust(frame, temperature=0, contrast=0), frame)

    def test_exposure_scales_by_two_to_the_stops(self) -> None:
        gray = solid(100, 100, 100)
        up = adjust(gray, exposure=1.0)
        down = adjust(gray, exposure=-1.0)
        self.assertTrue(np.all(up == 200))
        self.assertTrue(np.all(down == 50))
        self.assertTrue(np.all(adjust(solid(160, 160, 160), exposure=1.0) == 255))
        self.assertTrue(np.all(adjust(gray, exposure=2.0) == 255))
        self.assertTrue(np.all(adjust(gray, exposure=-2.0) == 25))

    def test_contrast_spreads_and_flattens_around_mid_gray(self) -> None:
        frame = np.tile(np.linspace(64, 192, 64).astype(np.uint8), (8, 1))
        frame = np.repeat(frame[:, :, None], 3, axis=2)
        self.assertGreater(adjust(frame, contrast=50).std(), frame.std() * 1.3)
        self.assertLess(adjust(frame, contrast=-50).std(), frame.std() * 0.7)
        self.assertTrue(np.all(adjust(frame, contrast=-100) == 128))
        mid = solid(128, 128, 128)
        np.testing.assert_array_equal(adjust(mid, contrast=80), mid)

    def test_saturation_minus_100_is_grayscale(self) -> None:
        out = adjust(random_frame(3), saturation=-100)
        np.testing.assert_array_equal(out[:, :, 0], out[:, :, 1])
        np.testing.assert_array_equal(out[:, :, 1], out[:, :, 2])

    def test_saturation_scales_chroma(self) -> None:
        frame = solid(100, 120, 160)
        base = int(frame[0, 0, 2]) - int(frame[0, 0, 0])
        more = adjust(frame, saturation=50)
        less = adjust(frame, saturation=-50)
        self.assertGreater(int(more[0, 0, 2]) - int(more[0, 0, 0]), base * 1.4)
        self.assertLess(int(less[0, 0, 2]) - int(less[0, 0, 0]), base * 0.6)
        gray = solid(90, 90, 90)
        np.testing.assert_array_equal(adjust(gray, saturation=100), gray)

    def test_temperature_trades_blue_for_red(self) -> None:
        gray = solid(128, 128, 128)
        warm = mean_bgr(adjust(gray, temperature=50))
        cool = mean_bgr(adjust(gray, temperature=-50))
        self.assertGreater(warm[2], 128)
        self.assertLess(warm[0], 128)
        self.assertEqual(warm[1], 128)
        self.assertLess(cool[2], 128)
        self.assertGreater(cool[0], 128)

    def test_tint_moves_green(self) -> None:
        gray = solid(128, 128, 128)
        magenta = mean_bgr(adjust(gray, tint=50))
        green = mean_bgr(adjust(gray, tint=-50))
        self.assertLess(magenta[1], 128)
        self.assertGreater(green[1], 128)
        self.assertEqual((magenta[0], magenta[2]), (128, 128))

    def test_sharpness_steepens_a_step_edge(self) -> None:
        frame = solid(60, 60, 60, (16, 32))
        frame[:, 16:] = 180
        out = adjust(frame, sharpness=100)
        before = np.abs(np.diff(frame[:, :, 1].astype(int), axis=1)).max()
        after = np.abs(np.diff(out[:, :, 1].astype(int), axis=1)).max()
        self.assertGreater(after, before)
        # flat areas far from the edge stay put
        self.assertTrue(np.all(out[:, :4] == 60))
        self.assertTrue(np.all(out[:, -4:] == 180))
        # overshoot on both sides is what sharpening looks like
        self.assertLess(int(out[8, 14, 1]), 60)
        self.assertGreater(int(out[8, 17, 1]), 180)

    def test_sharpness_scales_with_amount(self) -> None:
        frame = solid(60, 60, 60, (16, 32))
        frame[:, 16:] = 180

        def peak(amount: int) -> int:
            return int(adjust(frame, sharpness=amount)[8, 17, 1])

        self.assertGreater(peak(100), peak(50))
        self.assertGreaterEqual(peak(50), peak(10))

    def test_inputs_are_not_mutated_and_shape_dtype_hold(self) -> None:
        frame = random_frame(4, (30, 41))
        original = frame.copy()
        settings = ColorSettings(0.5, 20, 30, -10, 15, 40)
        for fields in (
            {"exposure": 0.5},
            {"contrast": 20},
            {"saturation": 30},
            {"temperature": -10},
            {"sharpness": 40},
            {
                "exposure": 0.5,
                "contrast": 20,
                "saturation": 30,
                "temperature": -10,
                "tint": 15,
                "sharpness": 40,
            },
        ):
            out = adjust(frame, **fields)
            self.assertIsNot(out, frame)
            self.assertEqual(out.dtype, np.uint8)
            self.assertEqual(out.shape, frame.shape)
            np.testing.assert_array_equal(frame, original)
        self.assertEqual(ColorAdjuster(settings)(frame).shape, frame.shape)

    def test_handles_non_contiguous_views(self) -> None:
        frame = random_frame(5, (24, 40))
        view = frame[:, ::2]
        settings = ColorSettings(0.3, 10, 20, 5, -5, 30)
        np.testing.assert_array_equal(
            ColorAdjuster(settings)(view),
            ColorAdjuster(settings)(np.ascontiguousarray(view)),
        )

    def test_configure_swaps_settings_and_skips_equal_ones(self) -> None:
        adjuster = ColorAdjuster()
        frame = solid(100, 100, 100)
        self.assertIs(adjuster(frame), frame)
        adjuster.configure(ColorSettings(exposure=1.0))
        self.assertTrue(np.all(adjuster(frame) == 200))
        plan = adjuster._plan
        adjuster.configure(ColorSettings(exposure=1.0))
        self.assertIs(adjuster._plan, plan)
        adjuster.configure(ColorSettings())
        self.assertIs(adjuster(frame), frame)

    def test_rejects_malformed_frames(self) -> None:
        adjuster = ColorAdjuster(ColorSettings(exposure=1.0))
        for bad in (
            np.zeros((4, 4), np.uint8),
            np.zeros((4, 4, 3), np.float32),
            np.zeros((0, 4, 3), np.uint8),
        ):
            with self.assertRaises(ValueError):
                adjuster(bad)


class NeutralBalanceTests(unittest.TestCase):
    def assert_neutral(self, sample: Frame) -> tuple[int, int]:
        temperature, tint = neutral_balance(sample)
        self.assertIsInstance(temperature, int)
        self.assertIsInstance(tint, int)
        self.assertTrue(-100 <= temperature <= 100 and -100 <= tint <= 100)
        out = ColorAdjuster(ColorSettings(temperature=temperature, tint=tint))(sample)
        means = mean_bgr(out)
        self.assertLessEqual(max(means) - min(means), 4, (means, temperature, tint))
        return temperature, tint

    def test_round_trip_removes_a_color_cast(self) -> None:
        temperature, tint = self.assert_neutral(solid(110, 128, 150))
        # red heavy sample needs cooling
        self.assertLess(temperature, 0)
        self.assert_neutral(solid(160, 128, 100))
        self.assert_neutral(solid(120, 150, 120))
        self.assert_neutral(solid(120, 105, 120))

    def test_round_trip_on_textured_sample(self) -> None:
        rng = np.random.default_rng(7)
        base = np.array([105, 125, 150], np.float64)
        noise = rng.normal(0, 8, (40, 40, 3))
        sample = np.clip(base + noise, 0, 255).astype(np.uint8)
        self.assert_neutral(sample)

    def test_neutral_sample_needs_no_correction(self) -> None:
        self.assertEqual(neutral_balance(solid(128, 128, 128)), (0, 0))
        self.assertEqual(neutral_balance(solid(0, 0, 0)), (0, 0))

    def test_inverts_the_adjuster_gains(self) -> None:
        for temperature, tint in ((30, 0), (-40, 25), (60, -35), (0, 50), (-80, -60)):
            gain_b = 1 - 0.3 * temperature / 100
            gain_g = 1 - 0.2 * tint / 100
            gain_r = 1 + 0.3 * temperature / 100
            sample = solid(
                round(150 / gain_b), round(150 / gain_g), round(150 / gain_r)
            )
            found = neutral_balance(sample)
            with self.subTest(temperature=temperature, tint=tint):
                self.assertLessEqual(abs(found[0] - temperature), 1)
                self.assertLessEqual(abs(found[1] - tint), 1)

    def test_clamps_extreme_casts(self) -> None:
        self.assertEqual(neutral_balance(solid(255, 128, 0))[0], 100)
        self.assertEqual(neutral_balance(solid(0, 128, 255))[0], -100)
        self.assertEqual(neutral_balance(solid(128, 255, 128))[1], 100)
        self.assertEqual(neutral_balance(solid(128, 1, 128))[1], -100)
        self.assertEqual(neutral_balance(solid(128, 0, 128))[1], 0)

    def test_rejects_malformed_samples(self) -> None:
        with self.assertRaises(ValueError):
            neutral_balance(np.zeros((4, 4), np.uint8))

    def test_does_not_mutate_sample(self) -> None:
        sample = random_frame(8)
        original = sample.copy()
        neutral_balance(sample)
        np.testing.assert_array_equal(sample, original)


class AutoLightTests(unittest.TestCase):
    def test_dark_frame_brightens_over_time_toward_target(self) -> None:
        frame = solid(40, 40, 40)
        light = AutoLight(100)
        # settle on a mid-brightness scene first so the ramp is visible
        light(solid(115, 115, 115), 0.0)
        levels = []
        for step in range(1, 61):
            levels.append(float(light(frame, step * 0.1)[0, 0, 1]))
        self.assertTrue(all(b >= a for a, b in zip(levels, levels[1:])), levels)
        self.assertGreater(levels[-1], 40 * 2.5)
        self.assertAlmostEqual(levels[-1], 0.45 * 255, delta=4)
        self.assertAlmostEqual(levels[0], 40, delta=15)

    def test_converges_with_the_time_constant(self) -> None:
        light = AutoLight(100, seconds=1.0)
        light(solid(100, 100, 100), 0.0)
        # gain goes 1.1475 -> 2.869 and covers 1 - 1/e of the gap after 1 s
        out = light(solid(40, 40, 40), 1.0)
        gain = 1.1475 + (2.869 - 1.1475) * (1 - math.exp(-1))
        self.assertAlmostEqual(float(out[0, 0, 0]), 40 * gain, delta=1.5)

    def test_first_call_jumps_to_the_desired_gain(self) -> None:
        out = AutoLight(100)(solid(40, 40, 40), 1234.5)
        self.assertAlmostEqual(float(out[0, 0, 0]), 0.45 * 255, delta=2)

    def test_strength_scales_the_lift(self) -> None:
        frame = solid(40, 40, 40)
        weak = int(AutoLight(25)(frame, 0.0)[0, 0, 0])
        mid = int(AutoLight(50)(frame, 0.0)[0, 0, 0])
        strong = int(AutoLight(100)(frame, 0.0)[0, 0, 0])
        self.assertTrue(40 < weak < mid < strong, (weak, mid, strong))
        # strength 50 applies half of the 2.869 gain
        self.assertAlmostEqual(mid, 40 * (1 + 1.869 * 0.5), delta=1.5)

    def test_max_gain_caps_the_lift(self) -> None:
        out = AutoLight(100, max_gain=2.0)(solid(10, 10, 10), 0.0)
        self.assertAlmostEqual(float(out[0, 0, 0]), 20, delta=1)

    def test_never_darkens(self) -> None:
        light = AutoLight(100)
        bright = solid(200, 200, 200)
        for step in range(5):
            np.testing.assert_array_equal(light(bright, step * 0.5), bright)
        # a frame with dark and bright regions only goes up pixelwise
        mixed = random_frame(9)
        mixed[:, :32] //= 6
        out = AutoLight(100)(mixed, 0.0)
        self.assertTrue(np.all(out >= mixed))
        self.assertGreater(out.mean(), mixed.mean())

    def test_strength_zero_is_identity(self) -> None:
        frame = solid(30, 30, 30)
        light = AutoLight(0)
        self.assertIs(light(frame, 0.0), frame)
        light.configure(100)
        self.assertGreater(int(light(frame, 1.0)[0, 0, 0]), 30)
        light.configure(0)
        self.assertIs(light(frame, 2.0), frame)

    def test_disabling_forgets_the_gain(self) -> None:
        light = AutoLight(100)
        light(solid(20, 20, 20), 0.0)
        light.configure(0)
        light.configure(100)
        # fresh start: first call jumps straight to the bright scene's gain
        bright = solid(200, 200, 200)
        np.testing.assert_array_equal(light(bright, 0.01), bright)

    def test_reset_drops_smoothing_state(self) -> None:
        dark, bright = solid(20, 20, 20), solid(200, 200, 200)

        def settled() -> AutoLight:
            light = AutoLight(100)
            for step in range(20):
                light(dark, step * 0.5)
            return light

        light = settled()
        # still lifted a moment later: the gain decays gradually
        self.assertGreater(int(light(bright, 10.01)[0, 0, 0]), 200)
        light = settled()
        light.reset()
        np.testing.assert_array_equal(light(bright, 10.01), bright)

    def test_highlights_roll_off_without_clipping(self) -> None:
        frame = solid(20, 20, 20)
        frame[:, :6] = 240
        frame[:, 6:12] = 250
        frame[:, 12:14] = 255
        out = AutoLight(100)(frame, 0.0)
        low, high, white = int(out[0, 0, 1]), int(out[0, 8, 1]), int(out[0, 12, 1])
        self.assertGreaterEqual(low, 240)
        self.assertGreater(high, low)
        self.assertGreaterEqual(high, 250)
        self.assertEqual(white, 255)
        self.assertGreater(int(out[0, 30, 1]), 20)

    def test_curve_is_monotonic_with_fixed_ends(self) -> None:
        light = AutoLight(100)
        levels = np.arange(256)
        for gain in (1.01, 1.3, 2.0, 2.87, 3.0, 8.0):
            lut = light._lut(gain)
            with self.subTest(gain=gain):
                self.assertEqual(int(lut[0]), 0)
                self.assertEqual(int(lut[255]), 255)
                self.assertTrue(np.all(np.diff(lut.astype(int)) >= 0))
                self.assertTrue(np.all(lut >= levels))
                self.assertGreater(int(lut[250]), int(lut[240]))

    def test_inputs_not_mutated_and_shape_dtype_hold(self) -> None:
        frame = random_frame(10, (36, 50)) // 5
        original = frame.copy()
        out = AutoLight(80)(frame, 0.0)
        self.assertIsNot(out, frame)
        self.assertEqual(out.dtype, np.uint8)
        self.assertEqual(out.shape, frame.shape)
        np.testing.assert_array_equal(frame, original)

    def test_large_and_tiny_frames(self) -> None:
        for shape in ((720, 1280), (3, 5), (1, 1)):
            dark = np.full((*shape, 3), 30, np.uint8)
            out = AutoLight(100)(dark, 0.0)
            self.assertEqual(out.shape, dark.shape)
            self.assertGreater(int(out[0, 0, 0]), 30)

    def test_time_going_backwards_does_not_break_smoothing(self) -> None:
        light = AutoLight(100)
        frame = solid(40, 40, 40)
        first = light(frame, 10.0)
        again = light(frame, 5.0)
        np.testing.assert_array_equal(first, again)

    def test_rejects_invalid_arguments(self) -> None:
        for kwargs in (
            {"strength": True},
            {"strength": 101},
            {"strength": -1},
            {"strength": 5.0},
            {"target": 0.0},
            {"target": 1.0},
            {"target": math.nan},
            {"seconds": 0.0},
            {"seconds": -1.0},
            {"seconds": math.inf},
            {"max_gain": 0.5},
            {"max_gain": math.nan},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AutoLight(**kwargs)  # type: ignore[arg-type]
        light = AutoLight()
        with self.assertRaises(ValueError):
            light.configure(200)
        with self.assertRaises(ValueError):
            light(solid(1, 1, 1), math.nan)
        with self.assertRaises(ValueError):
            light(np.zeros((4, 4), np.uint8), 0.0)


if __name__ == "__main__":
    unittest.main()
