"""Profile color settings, live color in the pipeline and click-to-white-balance."""

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.control import Controller
from webcam_mods.effects import ProfileEffect
from webcam_mods.profiles import RESTART_FIELDS, Profile, ProfileStore
from webcam_mods.settings import StartupSettings


class ColorProfileTests(unittest.TestCase):
    def test_defaults_are_neutral_and_ranges_are_enforced(self) -> None:
        profile = Profile.parse({"exposure": 1, "contrast": -100, "sharpness": 100})
        self.assertEqual((profile.exposure, profile.contrast), (1, -100))
        self.assertEqual(Profile().temperature, 0)
        for key, value in (
            ("exposure", 2.5),
            ("exposure", True),
            ("contrast", 101),
            ("saturation", 1.5),
            ("temperature", -101),
            ("tint", "5"),
            ("sharpness", -1),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(ValueError, key):
                    Profile.parse({key: value})
        self.assertFalse(
            {"exposure", "contrast", "saturation", "temperature", "tint", "sharpness"}
            & RESTART_FIELDS
        )


class ProfileEffectColorTests(unittest.TestCase):
    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(profile, StartupSettings(out_width=64, out_height=48))
        self.addCleanup(effect.close)
        return effect

    def test_color_applies_live_after_brightness(self) -> None:
        frame = np.full((48, 64, 3), 100, np.uint8)
        effect = self.effect(Profile(temperature=50))
        warm = effect(frame)
        assert warm is not None
        blue, _, red = warm.reshape(-1, 3).mean(axis=0)
        self.assertGreater(red, blue + 20)
        effect.update(Profile(brightness=20, exposure=1))
        bright = effect(frame)
        assert bright is not None
        # brightness lifts 100 to 120 first, then one stop doubles it
        self.assertAlmostEqual(float(bright.mean()), 240, delta=2)
        effect.update(Profile())
        np.testing.assert_array_equal(effect(frame), frame)

    def test_white_balance_neutralizes_clicked_patch(self) -> None:
        frame = np.zeros((48, 64, 3), np.uint8)
        frame[:, :32] = (150, 120, 100)
        frame[:, 32:] = (0, 0, 255)
        effect = self.effect(Profile(mirror=True))
        with self.assertRaisesRegex(RuntimeError, "no camera picture"):
            effect.white_balance(0.5, 0.5)
        effect(frame)
        # mirrored, so the bluish half is on the right of the camera view
        temperature, tint = effect.white_balance(0.75, 0.5)
        self.assertGreater(temperature, 0)
        effect.update(Profile(mirror=True, temperature=temperature, tint=tint))
        balanced = effect(frame)
        assert balanced is not None
        blue, green, red = balanced[:, 40:].reshape(-1, 3).mean(axis=0)
        self.assertLess(max(blue, green, red) - min(blue, green, red), 4)
        # picks at the frame edge clamp inside it
        self.assertEqual(len(effect.white_balance(1, 0)), 2)


class AutoLightProfileTests(unittest.TestCase):
    def test_auto_light_lifts_dark_framed_picture_live(self) -> None:
        with self.assertRaisesRegex(ValueError, "auto_light"):
            Profile.parse({"auto_light": 101})
        self.assertNotIn("auto_light", RESTART_FIELDS)
        dark = np.full((48, 64, 3), 30, np.uint8)
        effect = ProfileEffect(
            Profile(auto_light=100), StartupSettings(out_width=64, out_height=48)
        )
        self.addCleanup(effect.close)
        lifted = effect(dark)
        assert lifted is not None
        self.assertGreater(float(lifted.mean()), 60)
        # the gain eases over about a second and never darkens
        bright = np.full((48, 64, 3), 200, np.uint8)
        eased = effect(bright)
        assert eased is not None
        self.assertTrue(np.all(eased >= bright))
        effect.update(Profile())
        np.testing.assert_array_equal(effect(dark), dark)


class ControllerWhiteBalanceTests(unittest.TestCase):
    def test_white_balance_needs_running_session_and_valid_point(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        effect = Mock()
        effect.white_balance.return_value = (12, -3)
        started = threading.Event()

        def runner(profile, stop, ready, source_ready, **callbacks):
            callbacks["on_effect"](effect)
            ready()
            started.set()
            stop.wait(5)

        with patch("webcam_mods.control.run_profile", runner):
            controller = Controller(
                ProfileStore(Path(directory.name) / "profiles.db"), lambda _: None
            )
        self.addCleanup(controller.stop)
        dispatch = controller.dispatch
        with self.assertRaisesRegex(RuntimeError, "no running session"):
            dispatch("session.white_balance", {"x": 0.5, "y": 0.5})
        controller.start(Profile(), "preview")
        self.assertTrue(started.wait(1))
        for params in ({"x": 0.5}, {"x": 1.5, "y": 0}, {"x": True, "y": 0}):
            with self.subTest(params=params):
                with self.assertRaisesRegex(ValueError, "x and y in 0..1"):
                    dispatch("session.white_balance", params)
        self.assertEqual(
            dispatch("session.white_balance", {"x": 0.25, "y": 1}),
            {"temperature": 12, "tint": -3},
        )
        effect.white_balance.assert_called_once_with(0.25, 1)


if __name__ == "__main__":
    unittest.main()
