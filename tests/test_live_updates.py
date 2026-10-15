"""Running sessions apply live profile changes without reopening devices."""

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


class ControllerLiveUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = ProfileStore(Path(directory.name) / "profiles.db")
        self.effect = Mock()
        self.started = threading.Event()
        self.events: list[dict[str, object]] = []

        def runner(profile, stop, ready, source_ready, **callbacks):
            callbacks["on_effect"](self.effect)
            self.warn = callbacks["on_warning"]
            ready()
            self.started.set()
            stop.wait(5)

        with patch("webcam_mods.control.run_profile", runner):
            self.controller = Controller(self.store, self.events.append)
        self.addCleanup(self.controller.stop)

    def start(self, profile: Profile) -> None:
        self.controller.start(profile, "preview")
        self.assertTrue(self.started.wait(1))

    def test_update_requires_running_session(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no running session"):
            self.controller.dispatch("session.update", {"config": {}})

    def test_live_fields_reach_effect_and_restart_fields_are_rejected(self) -> None:
        self.start(Profile(effect="blur"))
        config = {"effect": "color", "color": 90, "brightness": 30, "mirror": True}
        result = self.controller.dispatch("session.update", {"config": config})
        self.assertEqual(result["state"], "running")
        self.effect.update.assert_called_once_with(Profile.parse(config))
        for name, value in (("width", 1280), ("fps", 60.0), ("capture", "opencv")):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, f"restart required.*{name}"),
            ):
                self.controller.dispatch(
                    "session.update", {"config": {**config, name: value}}
                )
        self.assertEqual(self.effect.update.call_count, 1)
        self.assertEqual(self.controller.profile, Profile.parse(config))

    def test_rejected_effect_update_keeps_running_profile(self) -> None:
        self.start(Profile())
        self.effect.update.side_effect = ValueError("background image unreadable")
        with self.assertRaisesRegex(ValueError, "unreadable"):
            self.controller.dispatch(
                "session.update",
                {"config": {"effect": "image", "image_path": "/missing.jpg"}},
            )
        self.assertEqual(self.controller.profile, Profile())

    def test_update_params_and_stop_clear_effect(self) -> None:
        self.start(Profile())
        with self.assertRaisesRegex(ValueError, "requires only config"):
            self.controller.dispatch("session.update", {"config": {}, "extra": 1})
        self.warn("Could not apply settings: test")
        self.assertIn(
            {"event": "warning", "data": {"message": "Could not apply settings: test"}},
            self.events,
        )
        self.controller.stop()
        with self.assertRaisesRegex(RuntimeError, "no running session"):
            self.controller.dispatch("session.update", {"config": {}})

    def test_restart_fields_cover_capture_and_output_shape(self) -> None:
        self.assertTrue(
            {"width", "height", "fps", "camera_id", "output_width", "capture"}
            <= RESTART_FIELDS
        )
        self.assertFalse(
            {"effect", "track", "brightness", "mirror", "segmentation"} & RESTART_FIELDS
        )


class ProfileEffectLiveTests(unittest.TestCase):
    frame = np.full((48, 64, 3), 10, np.uint8)

    def effect(self, profile: Profile, **kwargs: object) -> ProfileEffect:
        effect = ProfileEffect(
            profile, StartupSettings(out_width=64, out_height=48), **kwargs  # type: ignore[arg-type]
        )
        self.addCleanup(effect.close)
        return effect

    def test_background_mode_changes_reuse_segmentation(self) -> None:
        image = np.full((4, 6, 3), 42, np.uint8)
        with (
            patch("webcam_mods.entry.BackgroundEffect") as background,
            patch("webcam_mods.effects.cv2.imread", return_value=image) as read,
        ):
            background.return_value.side_effect = lambda frame: frame
            effect = self.effect(Profile(effect="blur"))
            effect(self.frame)
            effect.update(Profile(effect="color", color=80))
            effect(self.frame)
            effect.update(Profile(effect="image", image_path="bg.jpg"))
            read.assert_called_once_with("bg.jpg")
            effect(self.frame)
            background.assert_called_once()
            configure = background.return_value.configure
            self.assertEqual(
                [call.args[:2] for call in configure.call_args_list[:1]],
                [("color_bg", 80)],
            )
            self.assertEqual(configure.call_args_list[1].args[0], "swap_bg")
            self.assertIs(configure.call_args_list[1].args[1], image)
            effect.update(Profile(effect="image", image_path="bg.jpg", smoothing=True))
            effect(self.frame)
            self.assertEqual(background.call_count, 2)
            background.return_value.close.assert_called_once()
            effect.update(Profile())
            effect(self.frame)
            self.assertEqual(background.return_value.close.call_count, 2)
            read.assert_called_once()

    def test_tracking_toggles_without_restart(self) -> None:
        with patch("webcam_mods.effects.TrackingEffect") as tracking:
            tracking.return_value.side_effect = lambda frame: frame[:24, :32]
            effect = self.effect(Profile())
            self.assertEqual(effect(self.frame).shape, (48, 64, 3))
            effect.update(Profile(track=True))
            self.assertEqual(effect(self.frame).shape, (24, 32, 3))
            tracking.assert_called_once()
            effect.update(Profile(brightness=5))
            result = effect(self.frame)
            self.assertEqual(result.shape, (48, 64, 3))
            self.assertTrue(np.all(result == 15))
            tracking.return_value.close.assert_called_once()

    def test_failed_update_warns_and_keeps_processing(self) -> None:
        warnings: list[str] = []
        with patch(
            "webcam_mods.entry.BackgroundEffect", side_effect=RuntimeError("no model")
        ):
            effect = self.effect(Profile(brightness=5), on_warning=warnings.append)
            effect.update(Profile(effect="blur", brightness=5))
            result = effect(self.frame)
        self.assertTrue(np.all(result == 15))
        self.assertEqual(warnings, ["Could not apply settings: no model"])
        self.assertEqual(effect.profile, Profile(brightness=5))

    def test_unreadable_image_fails_at_update_time(self) -> None:
        effect = self.effect(Profile())
        with patch("webcam_mods.effects.cv2.imread", return_value=None):
            with self.assertRaisesRegex(ValueError, "could not be read"):
                effect.update(Profile(effect="image", image_path="missing.jpg"))
        np.testing.assert_array_equal(effect(self.frame), self.frame)

    def test_latest_update_wins_and_closed_effect_rejects_updates(self) -> None:
        effect = self.effect(Profile())
        effect.update(Profile(brightness=1))
        effect.update(Profile(brightness=2))
        self.assertTrue(np.all(effect(self.frame) == 12))
        effect.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            effect.update(Profile())


if __name__ == "__main__":
    unittest.main()
