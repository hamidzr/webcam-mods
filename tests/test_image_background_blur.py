"""Static image blur is prepared once, while foreground frames stay live."""

import unittest
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import cv2
import numpy as np
from typer.testing import CliRunner

from webcam_mods import entry
from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.person_segmentation import PersonEffects
from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.settings import StartupSettings


class ImageBackgroundBlurTests(unittest.TestCase):
    def test_blur_cache_reused_and_invalidated(self) -> None:
        background = np.random.default_rng(42).integers(
            0, 256, (8, 10, 3), dtype=np.uint8
        )
        source = background.copy()
        effects = PersonEffects()
        self.addCleanup(effects.close)
        effects.set_background(background, blur_kernel=3)
        background.fill(0)
        original_blur = cv2.blur
        with (
            patch.object(effects, "mask") as mask,
            patch(
                "webcam_mods.mods.person_segmentation.cv2.blur", wraps=cv2.blur
            ) as blur,
        ):
            for index, (height, width) in enumerate(((4, 6), (4, 6), (6, 4), (6, 4))):
                frame = np.full((height, width, 3), 213 + index, np.uint8)
                alpha = np.zeros((height, width, 1), np.float32)
                alpha[:, :2] = 1
                mask.return_value = frame, alpha
                expected = original_blur(cv2.resize(source, (width, height)), (3, 3))
                result = effects.swap_bg(frame)
                np.testing.assert_array_equal(result[:, :2], frame[:, :2])
                np.testing.assert_array_equal(result[:, 2:], expected[:, 2:])
            self.assertEqual(blur.call_count, 2)
            cached = effects._background
            effects.swap_bg(frame)
            self.assertIs(effects._background, cached)
            self.assertEqual(blur.call_count, 2)

            effects.set_background(source, blur_kernel=5)
            effects.swap_bg(frame)
            self.assertEqual(blur.call_count, 3)
            self.assertEqual(blur.call_args.args[1], (5, 5))
            effects.set_background(np.full_like(source, 73), blur_kernel=5)
            result = effects.swap_bg(frame)
            np.testing.assert_array_equal(result[:, 2:], 73)
            self.assertEqual(blur.call_count, 4)

    def test_default_background_skips_blur(self) -> None:
        effects = PersonEffects()
        self.addCleanup(effects.close)
        frame = np.zeros((4, 6, 3), np.uint8)
        effects.set_background(np.full_like(frame, 42))
        with (
            patch.object(effects, "mask", return_value=(frame, np.zeros((4, 6, 1)))),
            patch("webcam_mods.mods.person_segmentation.cv2.blur") as blur,
        ):
            np.testing.assert_array_equal(effects.swap_bg(frame), 42)
            effects.swap_bg(frame)
            blur.assert_not_called()

    def test_coreimage_composites_cached_pixels_without_live_blur(self) -> None:
        effects = PersonEffects()
        self.addCleanup(effects.close)
        effects.processor = Mock()
        frame = np.zeros((4, 6, 3), np.uint8)
        effects.set_background(np.full_like(frame, 42), blur_kernel=3)
        with (
            patch.object(effects, "mask", return_value=(frame, np.zeros((4, 6, 1)))),
            patch(
                "webcam_mods.mods.person_segmentation.cv2.blur", wraps=cv2.blur
            ) as blur,
        ):
            effects.swap_bg(frame)
            effects.swap_bg(frame)
            blur.assert_called_once()
        first, second = effects.processor.process.call_args_list
        self.assertIs(first.kwargs["background"], second.kwargs["background"])
        self.assertNotIn("blur_radius", first.kwargs)

    def test_invalid_kernel_preserves_cached_background(self) -> None:
        effects = PersonEffects()
        self.addCleanup(effects.close)
        background = np.full((4, 6, 3), 42, np.uint8)
        effects.set_background(background, blur_kernel=3)
        for kernel in (0, -1, 2, True, 3.0):
            with self.subTest(kernel=kernel), self.assertRaises(ValueError):
                effects.set_background(np.zeros_like(background), blur_kernel=kernel)
            np.testing.assert_array_equal(effects._background_source, background)
            self.assertEqual(effects._background_blur_kernel, 3)


class ImageBlurConfigurationTests(unittest.TestCase):
    def test_profile_defaults_validation_and_round_trip(self) -> None:
        self.assertFalse(
            Profile.parse({"effect": "image", "image_path": "bg.jpg"}).image_blur
        )
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Profile.parse({"image_blur": value})
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.sqlite3")
            store.save(
                "Image blur",
                {
                    "effect": "image",
                    "image_path": "bg.jpg",
                    "image_blur": True,
                    "blur_kernel": 15,
                },
            )
            saved = store.get("Image blur")
            self.assertTrue(saved.image_blur)
            self.assertEqual(saved.blur_kernel, 15)

    def test_profile_prepares_image_blur_once(self) -> None:
        image = np.full((4, 6, 3), 42, np.uint8)
        for enabled, kernel in ((False, 1), (True, 15)):
            with (
                self.subTest(enabled=enabled),
                patch("webcam_mods.effects.cv2.imread", return_value=image) as read,
                patch.object(entry, "BackgroundEffect") as background,
            ):
                background.return_value.side_effect = lambda frame: frame
                effect = ProfileEffect(
                    Profile(
                        effect="image",
                        image_path="bg.jpg",
                        image_blur=enabled,
                        blur_kernel=15,
                    ),
                    StartupSettings(),
                )
                self.addCleanup(effect.close)
                effect(image)
                effect(image)
                read.assert_called_once_with("bg.jpg")
                background.assert_called_once()
                self.assertEqual(
                    background.call_args.kwargs["image_blur_kernel"], kernel
                )
                effect.close()
                background.return_value.close.assert_called_once()

    def test_cli_image_blur_and_default(self) -> None:
        image = np.zeros((4, 6, 3), np.uint8)
        for options, kernel in (([], 1), (["--blur", "--blur-kernel-size", "15"], 15)):
            with (
                self.subTest(options=options),
                patch.object(entry.cv2, "imread", return_value=image),
                patch.object(entry, "BackgroundEffect") as background,
                patch.object(entry, "_run"),
            ):
                result = CliRunner().invoke(
                    entry.app, ["bg-swap", *options, "--no-controls"]
                )
                self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                self.assertEqual(
                    background.call_args.kwargs["image_blur_kernel"], kernel
                )

    def test_invalid_cli_image_kernel_fails_before_loading_or_capture(self) -> None:
        for kernel in ("0", "2", "512"):
            with (
                self.subTest(kernel=kernel),
                patch.object(entry.cv2, "imread") as read,
                patch.object(entry, "_run") as run,
            ):
                result = CliRunner().invoke(
                    entry.app,
                    [
                        "bg-swap",
                        "--blur",
                        "--blur-kernel-size",
                        kernel,
                        "--no-controls",
                    ],
                )
                self.assertNotEqual(result.exit_code, 0)
                read.assert_not_called()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
