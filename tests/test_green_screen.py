"""Green screen keying as a profile segmentation choice, tuned live."""

import unittest
from unittest.mock import patch

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings

GREEN_BGR = (64, 177, 0)


def green_room() -> np.ndarray:
    """Green backdrop with a gray person in the middle."""
    frame = np.empty((48, 64, 3), np.uint8)
    frame[:] = GREEN_BGR
    frame[12:36, 20:44] = 128
    return frame


class GreenScreenProfileTests(unittest.TestCase):
    def test_key_fields_are_validated_and_live(self) -> None:
        profile = Profile.parse({"segmentation": "chroma", "key_color": "#0047bb"})
        self.assertEqual(profile.key_color, "#0047BB")
        self.assertEqual(profile.key_bgr, (0xBB, 0x47, 0))
        self.assertEqual(Profile().key_bgr, GREEN_BGR)
        with self.assertRaisesRegex(ValueError, "key_color"):
            Profile.parse({"key_color": "green"})
        for key in ("key_tolerance", "key_softness", "key_spill"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                Profile.parse({key: 101})
        self.assertFalse(
            {"segmentation", "key_color", "key_tolerance", "key_softness", "key_spill"}
            & RESTART_FIELDS
        )


class GreenScreenEffectTests(unittest.TestCase):
    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(profile, StartupSettings(out_width=64, out_height=48))
        self.addCleanup(effect.close)
        return effect

    def test_backdrop_is_replaced_without_person_model(self) -> None:
        profile = Profile(
            effect="color", background_color="#FF0000", segmentation="chroma"
        )
        with patch(
            "webcam_mods.mods.person_segmentation.MediaPipeSegmenter"
        ) as person_model:
            effect = self.effect(profile)
            result = effect(green_room())
        person_model.assert_not_called()
        assert result is not None
        np.testing.assert_allclose(result[2, 2], (0, 0, 255), atol=3)
        np.testing.assert_allclose(result[24, 32], (128, 128, 128), atol=3)
        assert effect.background is not None
        mask = effect.background.mask
        assert mask is not None
        self.assertLess(float(mask[2, 2]), 0.05)
        self.assertGreater(float(mask[24, 32]), 0.95)

    def test_key_settings_apply_live_on_the_same_segmenter(self) -> None:
        profile = Profile(
            effect="color", background_color="#FF0000", segmentation="chroma"
        )
        effect = self.effect(profile)
        effect(green_room())
        background = effect.background
        # a blue key leaves the green backdrop in place
        blue = Profile(
            effect="color",
            background_color="#FF0000",
            segmentation="chroma",
            key_color="#0047BB",
        )
        effect.update(blue)
        result = effect(green_room())
        assert result is not None
        self.assertIs(effect.background, background)
        np.testing.assert_allclose(result[2, 2], GREEN_BGR, atol=3)
        with self.assertRaisesRegex(ValueError, "key_tolerance"):
            effect.update(Profile(segmentation="chroma", key_tolerance=-1))


if __name__ == "__main__":
    unittest.main()
