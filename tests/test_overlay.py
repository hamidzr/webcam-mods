"""Overlay composites a logo and name caption from cached layers."""

import os
from pathlib import Path
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np
from PIL import ImageFont

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods import overlay
from webcam_mods.mods.overlay import (
    POSITIONS,
    Overlay,
    OverlaySettings,
    Position,
)
from webcam_mods.profiles import RESTART_FIELDS, Profile, ProfileStore
from webcam_mods.settings import StartupSettings
from webcam_mods.utils.video import Frame

WIDTH, HEIGHT = 640, 480
BACKGROUND = 100


def gray_frame(width: int = WIDTH, height: int = HEIGHT) -> Frame:
    return np.full((height, width, 3), BACKGROUND, np.uint8)


def changed_box(before: Frame, after: Frame) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1), x1/y1 exclusive, of changed pixels."""
    changed = np.any(before != after, axis=2)
    if not changed.any():
        return None
    ys, xs = np.nonzero(changed)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def in_corner(
    box: tuple[int, int, int, int], position: Position, width: int, height: int
) -> bool:
    x0, y0, x1, y1 = box
    horizontal = x1 <= width // 2 if position.endswith("left") else x0 >= width // 2
    vertical = y1 <= height // 2 if position.startswith("top") else y0 >= height // 2
    return horizontal and vertical


class OverlayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def write_logo(
        self,
        name: str = "logo.png",
        size: tuple[int, int] = (200, 100),
        color: tuple[int, ...] = (0, 0, 255, 255),
        channels: int = 4,
    ) -> str:
        """Write a solid logo of `size` (w, h) and return its path."""
        logo = np.empty((size[1], size[0], channels), np.uint8)
        logo[:] = color[:channels]
        path = os.path.join(self.tmp, name)
        self.assertTrue(cv2.imwrite(path, logo))
        return path


class SettingsTests(OverlayTestCase):
    def test_defaults_are_empty(self) -> None:
        self.assertTrue(OverlaySettings().is_empty())

    def test_is_empty_false_with_image_or_caption(self) -> None:
        self.assertFalse(OverlaySettings(logo_path="x.png").is_empty())
        self.assertFalse(OverlaySettings(caption="Ada").is_empty())
        self.assertTrue(OverlaySettings(caption="   ").is_empty())

    def test_rejects_invalid_values(self) -> None:
        bad: list[dict[str, Any]] = [
            {"logo_position": "middle"},
            {"caption_position": "left"},
            {"logo_scale": 4},
            {"logo_scale": 61},
            {"logo_scale": 15.5},
            {"logo_scale": True},
            {"logo_opacity": -1},
            {"logo_opacity": 101},
            {"caption": "x" * 81},
            {"caption_detail": "x" * 81},
            {"caption": "line\nbreak"},
            {"caption": "tab\there"},
            {"caption_detail": "bell\x07"},
            {"caption": 5},
            {"logo_path": None},
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                OverlaySettings(**kwargs)
            with self.subTest(profile=kwargs), self.assertRaises(ValueError):
                Profile.parse(kwargs)

    def test_captions_allow_any_printable_text(self) -> None:
        # joined emoji and no-break spaces are not control characters
        text = "Ada\u00a0Lovelace \U0001f469\u200d\U0001f4bb"
        self.assertEqual(Profile.parse({"caption": text}).caption, text)
        OverlaySettings(caption=text)

    def test_accepts_bounds(self) -> None:
        for scale in (5, 60):
            OverlaySettings(logo_scale=scale)
        for opacity in (0, 100):
            OverlaySettings(logo_opacity=opacity)
        OverlaySettings(caption="x" * 80, caption_detail="y" * 80)
        for position in POSITIONS:
            OverlaySettings(logo_position=position, caption_position=position)


class ConfigureTests(OverlayTestCase):
    def test_unreadable_image_raises(self) -> None:
        missing = os.path.join(self.tmp, "missing.png")
        garbage = os.path.join(self.tmp, "garbage.png")
        with open(garbage, "wb") as handle:
            handle.write(b"not an image")
        for path in (missing, garbage):
            with self.subTest(path=path), self.assertRaises(ValueError):
                Overlay().configure(OverlaySettings(logo_path=path))

    def test_oversized_image_raises(self) -> None:
        path = self.write_logo("wide.png", size=(overlay.MAX_LOGO_SIDE + 1, 1))
        with self.assertRaises(ValueError):
            Overlay(OverlaySettings(logo_path=path))

    def test_failed_configure_keeps_previous_overlay(self) -> None:
        shown = Overlay(OverlaySettings(caption="Ada"))
        before = shown(gray_frame())
        with self.assertRaises(ValueError):
            shown.configure(OverlaySettings(logo_path="/nonexistent/logo.png"))
        np.testing.assert_array_equal(shown(gray_frame()), before)

    def test_jpeg_gray_and_sixteen_bit_images_load(self) -> None:
        jpeg = os.path.join(self.tmp, "logo.jpg")
        self.assertTrue(cv2.imwrite(jpeg, np.full((50, 80, 3), 200, np.uint8)))
        gray = os.path.join(self.tmp, "gray.png")
        self.assertTrue(cv2.imwrite(gray, np.full((50, 80), 200, np.uint8)))
        deep = os.path.join(self.tmp, "deep.png")
        self.assertTrue(cv2.imwrite(deep, np.full((50, 80, 3), 51400, np.uint16)))
        for path in (jpeg, gray, deep):
            with self.subTest(path=path):
                out = Overlay(OverlaySettings(logo_path=path))(gray_frame())
                box = changed_box(gray_frame(), out)
                self.assertIsNotNone(box)
                assert box is not None
                x0, y0, x1, y1 = box
                # opaque light logo: center pixel is the logo gray
                center = out[(y0 + y1) // 2, (x0 + x1) // 2]
                self.assertTrue(np.all(np.abs(center.astype(int) - 200) <= 2))


class CompositeTests(OverlayTestCase):
    def test_empty_settings_is_identity(self) -> None:
        frame = gray_frame()
        for stage in (Overlay(), Overlay(OverlaySettings())):
            out = stage(frame)
            np.testing.assert_array_equal(out, frame)

    def test_logo_changes_pixels_only_in_its_corner(self) -> None:
        path = self.write_logo()
        for position in POSITIONS:
            with self.subTest(position=position):
                stage = Overlay(
                    OverlaySettings(
                        logo_path=path, logo_position=position, logo_scale=20
                    )
                )
                frame = gray_frame()
                out = stage(frame)
                box = changed_box(frame, out)
                self.assertIsNotNone(box)
                assert box is not None
                self.assertTrue(in_corner(box, position, WIDTH, HEIGHT))
                # opaque red logo at 20% of the frame width, aspect kept
                self.assertAlmostEqual(box[2] - box[0], round(0.2 * WIDTH), delta=1)
                self.assertAlmostEqual(box[3] - box[1], round(0.1 * WIDTH), delta=1)
                x0, y0, x1, y1 = box
                np.testing.assert_array_equal(
                    out[(y0 + y1) // 2, (x0 + x1) // 2], (0, 0, 255)
                )

    def test_logo_alpha_is_respected(self) -> None:
        logo = np.zeros((100, 200, 4), np.uint8)
        logo[:, 100:] = (0, 255, 0, 255)  # transparent left half, opaque green right
        path = os.path.join(self.tmp, "half.png")
        self.assertTrue(cv2.imwrite(path, logo))
        frame = gray_frame()
        out = Overlay(OverlaySettings(logo_path=path, logo_scale=20))(frame)
        x0, y0, x1, y1 = changed_box(frame, out) or (0, 0, 0, 0)
        self.assertAlmostEqual(x1 - x0, 0.1 * WIDTH, delta=2)
        self.assertGreater(x1, 0.9 * WIDTH)

    def test_logo_opacity_blends(self) -> None:
        path = self.write_logo()
        frame = gray_frame()
        out = Overlay(OverlaySettings(logo_path=path, logo_opacity=50))(frame)
        x0, y0, x1, y1 = changed_box(frame, out) or (0, 0, 0, 0)
        pixel = out[(y0 + y1) // 2, (x0 + x1) // 2].astype(int)
        # half red over gray 100
        self.assertTrue(np.all(np.abs(pixel - (50, 50, 177)) <= 2), pixel)

    def test_zero_opacity_leaves_frame_unchanged(self) -> None:
        path = self.write_logo()
        frame = gray_frame()
        out = Overlay(OverlaySettings(logo_path=path, logo_opacity=0))(frame)
        np.testing.assert_array_equal(out, frame)

    def test_scale_controls_logo_width(self) -> None:
        path = self.write_logo()
        widths = []
        for scale in (10, 30):
            frame = gray_frame()
            out = Overlay(OverlaySettings(logo_path=path, logo_scale=scale))(frame)
            box = changed_box(frame, out) or (0, 0, 0, 0)
            widths.append(box[2] - box[0])
        self.assertAlmostEqual(widths[0], 0.1 * WIDTH, delta=1)
        self.assertAlmostEqual(widths[1], 0.3 * WIDTH, delta=1)

    def test_tall_logo_stays_inside_frame(self) -> None:
        path = self.write_logo(size=(20, 400))
        frame = gray_frame()
        out = Overlay(OverlaySettings(logo_path=path, logo_scale=60))(frame)
        box = changed_box(frame, out)
        self.assertIsNotNone(box)
        assert box is not None
        self.assertGreaterEqual(box[1], 1)
        self.assertLessEqual(box[3], HEIGHT - 1)

    def test_caption_changes_pixels_only_in_its_corner_band(self) -> None:
        for position in POSITIONS:
            with self.subTest(position=position):
                stage = Overlay(
                    OverlaySettings(caption="Ada Lovelace", caption_position=position)
                )
                frame = gray_frame()
                out = stage(frame)
                box = changed_box(frame, out)
                self.assertIsNotNone(box)
                assert box is not None
                self.assertTrue(in_corner(box, position, WIDTH, HEIGHT))
                x0, y0, x1, y1 = box
                # a lower-third band, not a full-frame wash
                self.assertLess(y1 - y0, 0.25 * HEIGHT)
                self.assertLess(x1 - x0, 0.6 * WIDTH)
                if position.endswith("left"):
                    self.assertGreater(x0, 0)
                else:
                    self.assertLess(x1, WIDTH)

    def test_caption_renders_text_over_dark_panel(self) -> None:
        frame = gray_frame()
        out = Overlay(OverlaySettings(caption="Ada Lovelace"))(frame)
        x0, y0, x1, y1 = changed_box(frame, out) or (0, 0, 0, 0)
        panel = out[y0:y1, x0:x1]
        # text is bright, panel behind it is darker than the background
        self.assertGreater(int(panel.max()), 200)
        self.assertLess(int(panel[2, (x1 - x0) // 2].max()), BACKGROUND)
        bright = np.count_nonzero(panel.max(axis=2) > 180)
        self.assertGreater(bright, 50)

    def test_caption_detail_adds_a_smaller_second_line(self) -> None:
        frame = gray_frame()
        single = changed_box(
            frame, Overlay(OverlaySettings(caption="Ada Lovelace"))(frame)
        )
        double = changed_box(
            frame,
            Overlay(OverlaySettings(caption="Ada Lovelace", caption_detail="Analyst"))(
                frame
            ),
        )
        assert single is not None and double is not None
        self.assertGreater(double[3] - double[1], single[3] - single[1])
        # the second line is smaller than the name line
        self.assertLess(double[3] - double[1], 2 * (single[3] - single[1]))

    def test_detail_without_caption_draws_nothing(self) -> None:
        frame = gray_frame()
        out = Overlay(OverlaySettings(caption_detail="Analyst"))(frame)
        np.testing.assert_array_equal(out, frame)

    def test_longest_caption_fits_inside_frame(self) -> None:
        for width, height in ((640, 480), (320, 240), (1280, 720)):
            with self.subTest(size=(width, height)):
                frame = gray_frame(width, height)
                stage = Overlay(
                    OverlaySettings(caption="W" * 80, caption_detail="i" * 80)
                )
                out = stage(frame)
                box = changed_box(frame, out)
                self.assertIsNotNone(box)
                assert box is not None
                self.assertGreater(box[0], 0)
                self.assertLess(box[2], width)

    def test_shared_corner_stacks_without_overlap(self) -> None:
        path = self.write_logo()
        for position in POSITIONS:
            with self.subTest(position=position):
                stage = Overlay(
                    OverlaySettings(
                        logo_path=path,
                        logo_position=position,
                        caption="Ada Lovelace",
                        caption_detail="Analyst",
                        caption_position=position,
                    )
                )
                logo, caption = stage.layer_for(WIDTH, HEIGHT).patches
                disjoint = (
                    logo.y + logo.height <= caption.y
                    or caption.y + caption.height <= logo.y
                    or logo.x + logo.width <= caption.x
                    or caption.x + caption.width <= logo.x
                )
                self.assertTrue(disjoint)
                frame = gray_frame()
                box = changed_box(frame, stage(frame))
                assert box is not None
                self.assertTrue(in_corner(box, position, WIDTH, HEIGHT))

    def test_logo_and_caption_in_different_corners_do_not_move(self) -> None:
        path = self.write_logo()
        both = Overlay(
            OverlaySettings(
                logo_path=path,
                logo_position="top-right",
                caption="Ada",
                caption_position="bottom-left",
            )
        )
        caption_only = Overlay(OverlaySettings(caption="Ada"))
        logo_only = Overlay(OverlaySettings(logo_path=path))
        frame = gray_frame()
        expected = caption_only(logo_only(frame))
        np.testing.assert_array_equal(both(frame), expected)

    def test_input_is_not_mutated(self) -> None:
        path = self.write_logo()
        frame = gray_frame()
        original = frame.copy()
        out = Overlay(
            OverlaySettings(
                logo_path=path, caption="Ada Lovelace", caption_detail="Analyst"
            )
        )(frame)
        np.testing.assert_array_equal(frame, original)
        self.assertIsNot(out, frame)
        self.assertFalse(np.array_equal(out, frame))
        self.assertEqual((out.dtype, out.shape), (frame.dtype, frame.shape))

    def test_non_contiguous_frame_composites(self) -> None:
        stage = Overlay(OverlaySettings(caption="Ada"))
        base = np.full((HEIGHT, WIDTH * 2, 3), BACKGROUND, np.uint8)
        view = base[:, ::2]
        np.testing.assert_array_equal(stage(view), stage(np.ascontiguousarray(view)))


class ProfileOverlayTests(OverlayTestCase):
    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(
            profile, StartupSettings(out_width=WIDTH, out_height=HEIGHT)
        )
        self.addCleanup(effect.close)
        return effect

    def test_overlay_fields_are_live_and_saved_with_absolute_paths(self) -> None:
        fields = {
            "logo_path",
            "logo_position",
            "logo_scale",
            "logo_opacity",
            "caption",
            "caption_detail",
            "caption_position",
        }
        self.assertFalse(fields & RESTART_FIELDS)
        store = ProfileStore(Path(self.tmp) / "profiles.sqlite3")
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        store.save("talk", {"logo_path": "logo.png", "caption": "Ada"})
        saved = store.get("talk")
        self.assertEqual(saved.logo_path, os.path.join(os.getcwd(), "logo.png"))
        self.assertEqual(saved.caption, "Ada")

    def test_overlay_draws_last_and_applies_live(self) -> None:
        frame = gray_frame()
        effect = self.effect(Profile())
        np.testing.assert_array_equal(effect(frame), frame)
        self.assertIsNone(effect.overlay)
        captioned = Profile(caption="Ada Lovelace", brightness=20)
        effect.update(captioned)
        out = effect(frame)
        assert out is not None
        box = changed_box(np.full_like(frame, BACKGROUND + 20), out)
        assert box is not None
        self.assertTrue(in_corner(box, "bottom-left", WIDTH, HEIGHT))
        # brightness and color apply under the caption, never to the white text
        self.assertGreater(int(out.max()), 240)
        stage = effect.overlay
        effect.update(captioned)
        effect(frame)
        self.assertIs(effect.overlay, stage)
        effect.update(Profile(caption="Ada Lovelace", caption_position="top-right"))
        box = changed_box(frame, effect(frame))
        assert box is not None
        self.assertTrue(in_corner(box, "top-right", WIDTH, HEIGHT))
        effect.update(Profile())
        np.testing.assert_array_equal(effect(frame), frame)
        self.assertIsNone(effect.overlay)

    def test_mirrored_profiles_keep_captions_readable(self) -> None:
        frame = gray_frame()
        plain = self.effect(Profile(caption="Ada Lovelace"))(frame)
        mirrored = self.effect(Profile(caption="Ada Lovelace", mirror=True))(frame)
        assert plain is not None and mirrored is not None
        np.testing.assert_array_equal(plain, mirrored)

    def test_unreadable_logo_fails_on_update_and_keeps_the_overlay(self) -> None:
        path = self.write_logo()
        effect = self.effect(Profile(logo_path=path, logo_scale=20))
        frame = gray_frame()
        before = effect(frame)
        with self.assertRaisesRegex(ValueError, "cannot read image"):
            effect.update(Profile(logo_path=os.path.join(self.tmp, "missing.png")))
        np.testing.assert_array_equal(effect(frame), before)
        # the logo is read once, when chosen
        with patch.object(overlay.cv2, "imread") as imread:
            effect.update(Profile(logo_path=path, logo_scale=30))
            box = changed_box(frame, effect(frame))
        imread.assert_not_called()
        assert box is not None
        self.assertAlmostEqual(box[2] - box[0], 0.3 * WIDTH, delta=1)


class CacheTests(OverlayTestCase):
    def test_layer_is_reused_for_the_same_size(self) -> None:
        stage = Overlay(OverlaySettings(caption="Ada"))
        first = stage.layer_for(WIDTH, HEIGHT)
        stage(gray_frame())
        self.assertIs(stage.layer_for(WIDTH, HEIGHT), first)
        self.assertIsNot(stage.layer_for(320, 240), first)

    def test_configure_drops_cached_layers(self) -> None:
        stage = Overlay(OverlaySettings(caption="Ada"))
        first = stage.layer_for(WIDTH, HEIGHT)
        stage.configure(OverlaySettings(caption="Grace"))
        self.assertIsNot(stage.layer_for(WIDTH, HEIGHT), first)

    def test_cache_is_bounded(self) -> None:
        stage = Overlay(OverlaySettings(caption="Ada"))
        for width in range(100, 100 + 2 * overlay.MAX_CACHED_SIZES * 20, 20):
            stage.layer_for(width, 100)
        self.assertLessEqual(len(stage._source.layers), overlay.MAX_CACHED_SIZES)

    def test_frames_of_any_size_work(self) -> None:
        path = self.write_logo()
        stage = Overlay(
            OverlaySettings(
                logo_path=path,
                caption="Ada Lovelace",
                caption_detail="Analyst",
                caption_position="bottom-right",
            )
        )
        for width, height in ((1280, 720), (320, 240), (640, 480), (64, 48), (1, 1)):
            with self.subTest(size=(width, height)):
                frame = gray_frame(width, height)
                out = stage(frame)
                self.assertEqual(out.shape, frame.shape)
                self.assertEqual(out.dtype, np.uint8)
        frame = gray_frame(1280, 720)
        self.assertIsNotNone(changed_box(frame, stage(frame)))


class FontTests(unittest.TestCase):
    def setUp(self) -> None:
        overlay._font_path.cache_clear()
        overlay._font.cache_clear()
        self.addCleanup(overlay._font_path.cache_clear)
        self.addCleanup(overlay._font.cache_clear)

    def test_falls_back_to_pillow_default_font(self) -> None:
        with patch.object(overlay, "FONT_CANDIDATES", ("/nonexistent/font.ttf",)):
            self.assertIsNone(overlay._font_path())
            font = overlay._font(24)
        self.assertGreater(font.getlength("Ada"), 0)

    def test_unloadable_font_file_falls_back(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".ttf") as bogus:
            bogus.write(b"not a font")
            bogus.flush()
            with patch.object(overlay, "FONT_CANDIDATES", (bogus.name,)):
                font = overlay._font(24)
        self.assertGreater(font.getlength("Ada"), 0)

    def test_font_lookup_is_cached(self) -> None:
        self.assertIs(overlay._font(20), overlay._font(20))
        self.assertIsNot(overlay._font(20), overlay._font(21))

    def test_caption_renders_with_fallback_font(self) -> None:
        with patch.object(overlay, "FONT_CANDIDATES", ()):
            frame = gray_frame()
            out = Overlay(OverlaySettings(caption="Ada", caption_detail="Analyst"))(
                frame
            )
            self.assertIsInstance(overlay._font(12), ImageFont.FreeTypeFont)
        self.assertGreater(int(out.max()), 200)


if __name__ == "__main__":
    unittest.main()
