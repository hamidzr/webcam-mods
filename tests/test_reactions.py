"""Gesture reactions: held gestures set off animations over the picture."""

import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.reactions import (
    CONFETTI,
    DETECT_INTERVAL,
    HOLD_SECONDS,
    GestureTrigger,
    Reactions,
    Sprite,
    emoji_sprite,
    reaction_for,
)
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings

WIDTH, HEIGHT = 160, 90


def frame() -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), 100, np.uint8)


def square_sprite(glyph: str) -> Sprite:
    alpha = np.ones((20, 20), np.float32)
    return Sprite(np.full((20, 20, 3), 250, np.float32), alpha)


class Hands:
    """Gesture source that reports the scripted gestures."""

    def __init__(self) -> None:
        self.gestures: list[str] = []
        self.looks = 0
        self.closed = False

    def detect(self, frame: np.ndarray) -> list[str]:
        self.looks += 1
        return list(self.gestures)

    def close(self) -> None:
        self.closed = True


class GestureTriggerTests(unittest.TestCase):
    def test_gestures_map_to_reactions(self) -> None:
        self.assertEqual(reaction_for(["Thumb_Up"]), "thumbs-up")
        self.assertEqual(reaction_for(["Thumb_Down"]), "thumbs-down")
        self.assertEqual(reaction_for(["Victory", "Open_Palm"]), "balloons")
        self.assertEqual(reaction_for(["ILoveYou"]), "hearts")
        self.assertEqual(reaction_for(["Thumb_Up", "Thumb_Up"]), CONFETTI)
        for gestures in ([], ["Open_Palm"], ["Closed_Fist"], ["Victory", "ILoveYou"]):
            with self.subTest(gestures=gestures):
                self.assertIsNone(reaction_for(gestures))

    def test_fires_once_held_and_again_only_after_release(self) -> None:
        trigger = GestureTrigger()
        self.assertIsNone(trigger.observe("hearts", 0.0))
        self.assertIsNone(trigger.observe("hearts", HOLD_SECONDS - 0.01))
        self.assertEqual(trigger.observe("hearts", HOLD_SECONDS), "hearts")
        self.assertIsNone(trigger.observe("hearts", 5.0))
        # a different gesture restarts the hold
        self.assertIsNone(trigger.observe("balloons", 5.1))
        self.assertIsNone(trigger.observe("hearts", 5.2))
        self.assertIsNone(trigger.observe(None, 5.3))
        self.assertIsNone(trigger.observe("hearts", 5.4))
        self.assertEqual(trigger.observe("hearts", 5.4 + HOLD_SECONDS), "hearts")


class ReactionsTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("webcam_mods.mods.reactions.emoji_sprite", square_sprite)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hands = Hands()
        self.warnings: list[str] = []
        self.reactions = Reactions(self.hands, on_warning=self.warnings.append, seed=3)

    def test_held_gesture_plays_then_ends(self) -> None:
        self.hands.gestures = ["Thumb_Up"]
        picture = frame()
        now = 0.0
        while self.reactions.playing is None and now < 2:
            self.reactions.detect(picture, now)
            now += 1 / 30
        self.assertEqual(self.reactions.playing, "thumbs-up")
        self.assertAlmostEqual(now, HOLD_SECONDS, delta=DETECT_INTERVAL + 0.05)
        # looked a few times a second, not on every frame
        self.assertLessEqual(self.hands.looks, round(now / DETECT_INTERVAL) + 1)
        drawn = self.reactions.draw(picture, now + 0.5)
        self.assertGreater(int((drawn != picture).any(axis=2).sum()), 100)
        # the bubble sits in the upper right
        changed = np.argwhere((drawn != picture).any(axis=2))
        self.assertGreater(changed[:, 1].mean(), WIDTH / 2)
        self.assertLess(changed[:, 0].mean(), HEIGHT / 2)
        self.assertIs(self.reactions.draw(picture, now + 2.5), picture)
        self.assertIsNone(self.reactions.playing)
        np.testing.assert_array_equal(picture, frame())

    def test_one_reaction_at_a_time(self) -> None:
        self.assertTrue(self.reactions.start("hearts", 0.0))
        self.assertFalse(self.reactions.start("balloons", 1.0))
        self.assertEqual(self.reactions.playing, "hearts")
        self.assertTrue(self.reactions.start("balloons", 3.5))

    def test_rising_reactions_enter_from_below_and_confetti_from_above(self) -> None:
        picture = frame()
        self.reactions.start("balloons", 0.0)
        early = np.argwhere((self.reactions.draw(picture, 0.6) != picture).any(axis=2))
        self.assertGreater(len(early), 0)
        self.assertGreater(early[:, 0].mean(), HEIGHT / 2)
        confetti = Reactions(self.hands, seed=3)
        confetti.start(CONFETTI, 0.0)
        early = np.argwhere((confetti.draw(picture, 1.0) != picture).any(axis=2))
        self.assertGreater(len(early), 0)
        self.assertLess(early[:, 0].mean(), HEIGHT * 0.6)
        np.testing.assert_array_equal(confetti.draw(picture, 2.99), picture)

    def test_missing_emoji_font_warns_once_but_confetti_still_shows(self) -> None:
        with patch("webcam_mods.mods.reactions.emoji_sprite", return_value=None):
            self.assertFalse(self.reactions.start("hearts", 0.0))
            self.assertFalse(self.reactions.start("thumbs-up", 1.0))
            self.assertTrue(self.reactions.start(CONFETTI, 2.0))
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("emoji font", self.warnings[0])

    def test_close_stops_the_recognizer(self) -> None:
        self.reactions.start("hearts", 0.0)
        self.reactions.close()
        self.assertTrue(self.hands.closed)
        self.assertIsNone(self.reactions.playing)

    def test_emoji_sprite_without_fonts_is_none(self) -> None:
        with patch("webcam_mods.mods.reactions.EMOJI_FONTS", ()):
            emoji_sprite.cache_clear()
            self.addCleanup(emoji_sprite.cache_clear)
            self.assertIsNone(emoji_sprite("\N{BALLOON}"))


class ProfileReactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.made: list[Mock] = []

        def make(**options: object) -> Mock:
            reactions = Mock()
            reactions.draw.side_effect = lambda picture, now: picture + 1
            self.made.append(reactions)
            return reactions

        patcher = patch("webcam_mods.effects.Reactions", side_effect=make)
        patcher.start()
        self.addCleanup(patcher.stop)

    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(
            profile, StartupSettings(out_width=WIDTH, out_height=HEIGHT)
        )
        self.addCleanup(effect.close)
        return effect

    def test_field_is_validated_and_live(self) -> None:
        self.assertTrue(Profile.parse({"reactions": True}).reactions)
        for bad in (1, "true", None):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "reactions"):
                    Profile.parse({"reactions": bad})
        self.assertNotIn("reactions", RESTART_FIELDS)

    def test_reactions_read_the_camera_and_draw_last(self) -> None:
        picture = frame()
        effect = self.effect(Profile(brightness=0))
        np.testing.assert_array_equal(effect(picture), picture)
        self.assertEqual(self.made, [])
        effect.update(Profile(reactions=True, caption="Ada"))
        output = effect(picture)
        (reactions,) = self.made
        seen = reactions.detect.call_args.args[0]
        np.testing.assert_array_equal(seen, picture)
        # drawn over the finished picture, caption included
        drawn = reactions.draw.call_args.args[0]
        self.assertFalse(np.array_equal(drawn, picture))
        np.testing.assert_array_equal(output, drawn + 1)
        effect.update(Profile())
        effect(picture)
        reactions.close.assert_called_once_with()
        effect.update(Profile(reactions=True))
        effect(picture)
        effect.close()
        self.made[1].close.assert_called_once_with()

    def test_shared_screens_react_only_to_the_presenter_camera(self) -> None:
        screen = frame()
        region = (0, 0, WIDTH, HEIGHT)
        effect = self.effect(
            Profile(source="screen", screen_region=region, reactions=True)
        )
        np.testing.assert_array_equal(effect(screen), screen)
        self.assertEqual(self.made, [])
        presenter = self.effect(
            Profile(
                source="screen", screen_region=region, presenter=True, reactions=True
            )
        )
        camera = np.full((HEIGHT, WIDTH, 3), 30, np.uint8)
        presenter.camera_feed = lambda: camera
        presenter(screen)
        (reactions,) = self.made
        np.testing.assert_array_equal(reactions.detect.call_args.args[0], camera)
        reactions.draw.assert_called_once()


if __name__ == "__main__":
    unittest.main()
