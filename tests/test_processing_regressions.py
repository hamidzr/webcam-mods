"""Extreme crop geometry, no-op ownership and static background caching."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.mods.person_segmentation import PersonEffects
from webcam_mods.mods.video_mods import (
    crop,
    pad_inward_centered,
    resize_and_pad,
    resize_to_box,
)
from webcam_mods.session import RunSession
from webcam_mods.utils.config import Config


class ProcessingRegressionTests(unittest.TestCase):
    def test_matching_aspect_crops_fill_output_without_rounding_borders(self) -> None:
        for dims, output in (
            ((156, 117), (640, 480)),
            ((308, 231), (640, 480)),
            ((616, 462), (320, 240)),
            ((15, 9), (25, 15)),
        ):
            with self.subTest(dims=dims, output=output):
                config = Config(path=None, width=640, height=480)
                config.crop_dims = list(dims)
                source = np.full((480, 640, 3), 123, np.uint8)
                prepared = RunSession(settings=config).prepare(source)
                result = resize_and_pad(prepared, *output)
                self.assertEqual(result.shape, (output[1], output[0], 3))
                np.testing.assert_array_equal(result, 123)

    def test_differing_aspect_outputs_keep_centered_letterboxing(self) -> None:
        for dims, output, fitted in (
            ((4, 2), (7, 7), (7, 3)),
            ((400, 300), (200, 151), (200, 150)),
            ((420, 315), (641, 479), (638, 479)),
            ((1, 480), (641, 479), (1, 479)),
        ):
            with self.subTest(dims=dims, output=output):
                source = np.full((dims[1], dims[0], 3), 123, np.uint8)
                resized = resize_to_box(source, *output)
                self.assertEqual(resized.shape, (fitted[1], fitted[0], 3))
                expected = np.zeros((output[1], output[0], 3), np.uint8)
                left, top = (output[0] - fitted[0]) // 2, (output[1] - fitted[1]) // 2
                expected[top : top + fitted[1], left : left + fitted[0]] = 123
                np.testing.assert_array_equal(resize_and_pad(source, *output), expected)

    def test_valid_narrow_crops_and_odd_outputs(self) -> None:
        for dims in ([1, 480], [640, 1], [1, 1]):
            for output in ((640, 480), (641, 479), (1, 1)):
                with self.subTest(dims=dims, output=output):
                    config = Config(path=None, width=640, height=480)
                    config.crop_dims = dims
                    self.assertTrue(config.valid(config.to_dict()))
                    source = np.full((480, 640, 3), 123, np.uint8)
                    prepared = RunSession(settings=config).prepare(source)
                    result = resize_and_pad(prepared, *output)
                    self.assertEqual(result.shape, (output[1], output[0], 3))
                    self.assertEqual(int(result.max()), 123)
                    np.testing.assert_array_equal(source, 123)

    def test_no_op_padding_retains_owned_crop(self) -> None:
        source = np.zeros((12, 17, 3), np.uint8)
        result = RunSession(Config(path=None, width=17, height=12)).prepare(source)
        self.assertFalse(np.shares_memory(result, source))
        self.assertIs(pad_inward_centered(result), result)
        self.assertIs(resize_and_pad(result, 17, 12), result)
        self.assertIsNone(crop(source, 0, 12))

    def test_static_background_cache_updates_size_and_pixels(self) -> None:
        effects = PersonEffects()
        background = np.full((8, 10, 3), 42, np.uint8)
        effects.set_background(background)
        background.fill(99)
        try:
            with (
                patch.object(effects, "mask") as mask,
                patch(
                    "webcam_mods.mods.person_segmentation.cv2.resize", wraps=cv2.resize
                ) as resize,
            ):
                for size in ((4, 6), (4, 6), (6, 4), (6, 4)):
                    frame = np.zeros((*size, 3), np.uint8)
                    mask.return_value = frame, np.zeros((*size, 1), np.float32)
                    result = effects.swap_bg(frame)
                    np.testing.assert_array_equal(result, 42)
                    self.assertEqual(result.shape, frame.shape)
                self.assertEqual(resize.call_count, 2)
                effects.set_background(background)
                np.testing.assert_array_equal(effects.swap_bg(frame), 99)
                background.fill(73)
                np.testing.assert_array_equal(effects.swap_bg(frame, background), 73)
        finally:
            effects.close()
        self.assertIsNone(effects._background)
        self.assertIsNone(effects._background_source)
