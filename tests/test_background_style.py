"""Any solid background color and image background fill position."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.person_segmentation import _fill_crop
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings


def empty_room() -> Mock:
    """Segmenter that finds no person, so the whole frame is background."""
    segmenter = Mock()
    segmenter.predict.side_effect = lambda image: np.zeros(image.shape[:2], np.float32)
    return segmenter


class BackgroundStyleProfileTests(unittest.TestCase):
    def test_color_and_position_are_validated(self) -> None:
        profile = Profile.parse({"background_color": "#12ab9f"})
        self.assertEqual(profile.background_color, "#12AB9F")
        self.assertEqual(profile.background_bgr, (0x9F, 0xAB, 0x12))
        self.assertEqual(Profile(color=40).background_bgr, (40, 40, 40))
        for value in ("12AB9F", "#12AB9", "#12AB9G", 0x12AB9F, ""):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "background_color"):
                    Profile.parse({"background_color": value})
        for key in ("image_x", "image_y"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                Profile.parse({key: 1.5})
        self.assertFalse({"background_color", "image_x", "image_y"} & RESTART_FIELDS)

    def test_fill_crop_keeps_aspect_and_slides_to_anchor(self) -> None:
        image = np.zeros((10, 40, 3), np.uint8)
        image[:, :, 0] = np.arange(40, dtype=np.uint8)
        for anchor, first in (((0, 0.5), 0), ((0.5, 0.5), 15), ((1, 0.5), 30)):
            with self.subTest(anchor=anchor):
                part = _fill_crop(image, 20, 20, anchor)
                self.assertEqual(part.shape[:2], (10, 10))
                self.assertEqual(int(part[0, 0, 0]), first)
        tall = _fill_crop(np.zeros((40, 10, 3), np.uint8), 20, 10, (0.5, 1))
        self.assertEqual(tall.shape[:2], (5, 10))


class BackgroundStyleEffectTests(unittest.TestCase):
    frame = np.full((48, 48, 3), 100, np.uint8)

    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(profile, StartupSettings(out_width=48, out_height=48))
        self.addCleanup(effect.close)
        return effect

    def test_any_color_applies_live_without_reloading_segmentation(self) -> None:
        with patch(
            "webcam_mods.mods.person_segmentation.MediaPipeSegmenter",
            return_value=empty_room(),
        ) as model:
            effect = self.effect(Profile(effect="color", background_color="#0080FF"))
            result = effect(self.frame)
            assert result is not None
            np.testing.assert_allclose(
                result.reshape(-1, 3).mean(0), (255, 128, 0), atol=2
            )
            effect.update(Profile(effect="color", color=30))
            result = effect(self.frame)
            assert result is not None
            np.testing.assert_allclose(result, 30, atol=2)
        model.assert_called_once()

    def test_image_fills_without_stretching_at_chosen_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wide.png"
            # wide image: red left third, green middle, blue right third
            wide = np.zeros((40, 120, 3), np.uint8)
            wide[:, :40, 2] = 255
            wide[:, 40:80, 1] = 255
            wide[:, 80:, 0] = 255
            cv2.imwrite(str(path), wide)
            with patch(
                "webcam_mods.mods.person_segmentation.MediaPipeSegmenter",
                return_value=empty_room(),
            ) as model:
                effect = self.effect(Profile(effect="image", image_path=str(path)))
                for x, channel in ((0.5, 1), (0, 2), (1, 0)):
                    with self.subTest(image_x=x):
                        effect.update(
                            Profile(effect="image", image_path=str(path), image_x=x)
                        )
                        result = effect(self.frame)
                        assert result is not None
                        # a square output shows one third of the wide image
                        means = result.reshape(-1, 3).mean(0)
                        self.assertGreater(means[channel], 240)
                        self.assertLess(np.delete(means, channel).max(), 15)
            model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
