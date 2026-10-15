"""Spotlight background: dim the background, lift the person, live tuning."""

import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.person_segmentation import _lift_table
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings


def scene() -> np.ndarray:
    """Gray frame whose left half is the person, marked by red 101."""
    frame = np.full((48, 64, 3), 100, np.uint8)
    frame[:, :32, 2] = 101
    return frame


def person_segmenter() -> Mock:
    segmenter = Mock()
    segmenter.predict.side_effect = lambda image: (image[:, :, 2] == 101).astype(
        np.float32
    )
    return segmenter


class SpotlightTests(unittest.TestCase):
    def test_profile_fields_are_validated_and_live(self) -> None:
        self.assertEqual(Profile.parse({"effect": "spotlight"}).spotlight_dim, 60)
        for key in ("spotlight_dim", "spotlight_lift"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                Profile.parse({key: 101})
        self.assertFalse({"spotlight_dim", "spotlight_lift"} & RESTART_FIELDS)

    def test_lift_keeps_black_and_white(self) -> None:
        np.testing.assert_array_equal(_lift_table(0), np.arange(256))
        table = _lift_table(100)
        self.assertEqual((table[0], table[255]), (0, 255))
        self.assertGreater(table[64], 100)
        self.assertTrue(np.all(np.diff(table.astype(int)) >= 0))

    def test_background_dims_and_person_lifts_with_live_changes(self) -> None:
        segmenter = person_segmenter()
        with patch(
            "webcam_mods.mods.person_segmentation.MediaPipeSegmenter",
            return_value=segmenter,
        ) as model:
            effect = ProfileEffect(
                Profile(effect="spotlight", spotlight_dim=60, spotlight_lift=20),
                StartupSettings(out_width=64, out_height=48),
            )
            self.addCleanup(effect.close)
            result = effect(scene())
            assert result is not None
            # interior columns avoid the softened mask edge
            person, background = result[:, :20].mean(), result[:, 44:].mean()
            self.assertGreater(person, 110)
            self.assertAlmostEqual(background, 40, delta=2)
            effect.update(
                Profile(effect="spotlight", spotlight_dim=0, spotlight_lift=0)
            )
            result = effect(scene())
            assert result is not None
            np.testing.assert_allclose(result[:, 44:], 100, atol=1)
            self.assertLess(abs(result[:, :20].mean() - 100), 2)
        model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
