"""Chroma key mask, parameter validation and edge despill."""

import unittest

import numpy as np

from webcam_mods.mods.chroma import ChromaKeySegmenter

GREEN = (64, 177, 0)
SKIN = (130, 165, 200)
GRAY = (128, 128, 128)


def solid(color: tuple[int, int, int], size: tuple[int, int] = (16, 16)) -> np.ndarray:
    frame = np.empty((*size, 3), np.uint8)
    frame[:] = color
    return frame


def keyed_scene() -> np.ndarray:
    frame = solid(GREEN, (96, 128))
    frame[20:60, 20:50] = SKIN
    frame[20:60, 70:100] = GRAY
    return frame


class ChromaKeyMaskTests(unittest.TestCase):
    def test_backdrop_is_transparent_and_foreground_opaque(self) -> None:
        mask = ChromaKeySegmenter().predict(keyed_scene())
        self.assertEqual(mask.shape, (96, 128))
        self.assertEqual(mask.dtype, np.float32)
        self.assertLessEqual(float(mask.max()), 1.0)
        self.assertGreaterEqual(float(mask.min()), 0.0)
        self.assertLess(float(mask[75:, 105:].max()), 0.02)
        self.assertGreater(float(mask[25:55, 25:45].min()), 0.98)
        self.assertGreater(float(mask[25:55, 75:95].min()), 0.98)

    def test_key_matches_independent_of_brightness(self) -> None:
        segmenter = ChromaKeySegmenter()
        dark = solid((32, 88, 0))
        bright = solid((128, 255, 0))
        self.assertLess(float(segmenter.predict(dark).max()), 0.02)
        self.assertLess(float(segmenter.predict(bright).max()), 0.02)

    def test_softness_widens_the_transition(self) -> None:
        # gradient from the key color to gray across 256 columns
        ramp = np.linspace(0, 1, 256, dtype=np.float32)[None, :, None]
        gradient = (np.array(GREEN) * (1 - ramp) + np.array(GRAY) * ramp).astype(
            np.uint8
        )
        gradient = np.repeat(gradient, 8, axis=0)

        def partial(softness: int) -> int:
            mask = ChromaKeySegmenter(softness=softness).predict(gradient)
            row = mask[4]
            # 8-bit chroma rounding allows small wiggle on the soft ramp
            if softness:
                self.assertGreater(float(np.diff(row).min()), -0.08)
            return int(np.count_nonzero((row > 0.05) & (row < 0.95)))

        hard, soft = partial(0), partial(100)
        self.assertLess(hard, 8)
        self.assertGreater(soft, 4 * hard)

    def test_tolerance_controls_hard_key_radius(self) -> None:
        # halfway between key and gray: ~40 CrCb units off the key
        near = solid(
            ((GREEN[0] + GRAY[0]) // 2, (GREEN[1] + GRAY[1]) // 2, GRAY[2] // 2)
        )
        strict = ChromaKeySegmenter(tolerance=0, softness=0)
        loose = ChromaKeySegmenter(tolerance=100, softness=0)
        self.assertGreater(float(strict.predict(near).min()), 0.99)
        self.assertLess(float(loose.predict(near).max()), 0.01)
        # exact key is transparent even at zero tolerance
        self.assertLess(float(strict.predict(solid(GREEN)).max()), 0.01)

    def test_other_key_colors(self) -> None:
        segmenter = ChromaKeySegmenter(color=(200, 50, 0))
        frame = solid((200, 50, 0), (32, 32))
        frame[8:24, 8:24] = SKIN
        mask = segmenter.predict(frame)
        self.assertLess(float(mask[:4].max()), 0.02)
        self.assertGreater(float(mask[12:20, 12:20].min()), 0.98)

    def test_input_not_mutated_and_output_is_new(self) -> None:
        frame = keyed_scene()
        original = frame.copy()
        segmenter = ChromaKeySegmenter()
        mask = segmenter.predict(frame)
        np.testing.assert_array_equal(frame, original)
        mask[:] = 0
        self.assertGreater(float(segmenter.predict(frame).max()), 0.9)

    def test_rejects_malformed_frames(self) -> None:
        segmenter = ChromaKeySegmenter()
        with self.assertRaises(ValueError):
            segmenter.predict(np.zeros((8, 8, 3), np.float32))
        with self.assertRaises(ValueError):
            segmenter.predict(np.zeros((8, 8), np.uint8))

    def test_close_is_a_noop(self) -> None:
        segmenter = ChromaKeySegmenter()
        segmenter.close()
        segmenter.close()
        self.assertEqual(segmenter.predict(solid(GRAY)).shape, (16, 16))


class ChromaKeyConfigureTests(unittest.TestCase):
    def test_invalid_settings_raise_and_keep_previous_state(self) -> None:
        segmenter = ChromaKeySegmenter()
        frame = keyed_scene()
        before = segmenter.predict(frame)
        bad: list[tuple[object, ...]] = [
            ((0, 0), 40, 30, 50),
            ((0, 0, 256), 40, 30, 50),
            ((0, -1, 0), 40, 30, 50),
            ((0.5, 0, 0), 40, 30, 50),
            (("a", 0, 0), 40, 30, 50),
            (GREEN, -1, 30, 50),
            (GREEN, 101, 30, 50),
            (GREEN, 40, 101, 50),
            (GREEN, 40, 30, -1),
            (GREEN, True, 30, 50),
            (GREEN, 40.0, 30, 50),
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                segmenter.configure(*args)  # type: ignore[arg-type]
        np.testing.assert_array_equal(segmenter.predict(frame), before)

    def test_constructor_validates(self) -> None:
        with self.assertRaises(ValueError):
            ChromaKeySegmenter(tolerance=200)

    def test_configure_changes_key(self) -> None:
        segmenter = ChromaKeySegmenter()
        blue = solid((200, 50, 0))
        self.assertGreater(float(segmenter.predict(blue).min()), 0.9)
        segmenter.configure((200, 50, 0), 40, 30, 50)
        self.assertLess(float(segmenter.predict(blue).max()), 0.02)


class ChromaDespillTests(unittest.TestCase):
    def setUp(self) -> None:
        # left half backdrop; right half foreground, green-tinted above, gray below
        self.frame = solid(GRAY, (32, 32))
        self.frame[:16, 16:] = (100, 200, 100)
        self.mask = np.ones((32, 32), np.float32)
        self.mask[:, :16] = 0

    def test_reduces_green_at_edge_and_leaves_neutral_pixels(self) -> None:
        original = self.frame.copy()
        result = ChromaKeySegmenter(spill=100).despill(self.frame, self.mask)
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(result.shape, self.frame.shape)
        np.testing.assert_array_equal(self.frame, original)
        edge, source = result[:16, 16], self.frame[:16, 16]
        self.assertTrue(np.all(edge[:, 1] < source[:, 1]))
        self.assertTrue(np.all(edge[:, 1] >= 100), "green stays at max(R, B) or above")
        np.testing.assert_array_equal(edge[:, [0, 2]], source[:, [0, 2]])
        np.testing.assert_array_equal(result[16:], self.frame[16:])
        # interior far from the backdrop keeps legitimate green
        np.testing.assert_array_equal(result[:16, 28:], self.frame[:16, 28:])

    def test_spill_amount_scales_reduction(self) -> None:
        def green_at_edge(spill: int) -> int:
            result = ChromaKeySegmenter(spill=spill).despill(self.frame, self.mask)
            return int(result[8, 16, 1])

        self.assertEqual(green_at_edge(0), 200)
        self.assertGreater(green_at_edge(20), green_at_edge(100))
        self.assertGreater(200, green_at_edge(20))

    def test_zero_spill_returns_unchanged_copy(self) -> None:
        result = ChromaKeySegmenter(spill=0).despill(self.frame, self.mask)
        np.testing.assert_array_equal(result, self.frame)
        self.assertIsNot(result, self.frame)

    def test_blue_key_clamps_blue_channel(self) -> None:
        frame = solid(GRAY, (32, 32))
        frame[:, 16:] = (220, 120, 120)
        result = ChromaKeySegmenter(color=(200, 50, 0), spill=100).despill(
            frame, self.mask
        )
        self.assertLess(int(result[8, 16, 0]), 220)
        self.assertGreaterEqual(int(result[8, 16, 0]), 120)
        np.testing.assert_array_equal(result[8, 16, 1:], frame[8, 16, 1:])

    def test_achromatic_key_is_noop(self) -> None:
        result = ChromaKeySegmenter(color=(128, 128, 128)).despill(
            self.frame, self.mask
        )
        np.testing.assert_array_equal(result, self.frame)

    def test_accepts_trailing_channel_mask_and_checks_shape(self) -> None:
        segmenter = ChromaKeySegmenter(spill=100)
        np.testing.assert_array_equal(
            segmenter.despill(self.frame, self.mask[:, :, None]),
            segmenter.despill(self.frame, self.mask),
        )
        with self.assertRaises(ValueError):
            segmenter.despill(self.frame, np.ones((8, 8), np.float32))

    def test_predict_then_despill_pipeline(self) -> None:
        frame = keyed_scene()
        segmenter = ChromaKeySegmenter()
        result = segmenter.despill(frame, segmenter.predict(frame))
        self.assertEqual(result.shape, frame.shape)
        np.testing.assert_array_equal(result[25:55, 75:95], frame[25:55, 75:95])


if __name__ == "__main__":
    unittest.main()
