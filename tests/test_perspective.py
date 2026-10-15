"""Perspective view warps a chosen quad to an upright rectangle."""

import json
import math
from pathlib import Path
import tempfile
import unittest
from typing import Any, cast
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.perspective import PerspectiveView
from webcam_mods.profiles import (
    RESTART_FIELDS,
    Profile,
    ProfileStore,
    Quad,
    validate_quad,
)
from webcam_mods.settings import StartupSettings
from webcam_mods.utils.video import Frame

FULL: Quad = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def scene(width: int = 320, height: int = 240) -> Frame:
    """Gray frame with a white rectangle at x 80..240, y 60..180."""
    frame = np.full((height, width, 3), 50, np.uint8)
    frame[60:180, 80:240] = 255
    return frame


class ValidateQuadTests(unittest.TestCase):
    def test_accepts_valid_quads(self) -> None:
        for quad in (
            FULL,
            ((0.1, 0.1), (0.9, 0.2), (0.8, 0.9), (0.2, 0.8)),
            ((0.2, 0.1), (0.8, 0.1), (1.0, 0.9), (0.0, 0.9)),
        ):
            with self.subTest(quad=quad):
                self.assertEqual(validate_quad(quad), quad)

    def test_accepts_numpy_scalars_and_rotated_start(self) -> None:
        quad = validate_quad(np.array(FULL, np.float32).tolist())
        self.assertEqual(quad, FULL)
        points = [tuple(np.float32(v) for v in point) for point in FULL]
        self.assertEqual(validate_quad(points), FULL)
        # a rotated start corner is still clockwise, so it only rotates the view
        rotated = ((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
        self.assertEqual(validate_quad(rotated), rotated)

    def test_accepts_json_lists_and_ints(self) -> None:
        loaded = json.loads("[[0, 0], [1, 0], [1, 1], [0, 1]]")
        quad = validate_quad(loaded)
        self.assertEqual(quad, FULL)
        self.assertIsInstance(quad, tuple)
        self.assertTrue(all(isinstance(point, tuple) for point in quad))
        self.assertTrue(all(isinstance(v, float) for point in quad for v in point))

    def test_rejects_malformed_input(self) -> None:
        bad: list[Any] = [
            None,
            "quad",
            42,
            {"tl": (0, 0)},
            [],
            [(0, 0), (1, 0), (1, 1)],
            [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5)],
            [(0, 0), (1, 0), (1, 1), (0,)],
            [(0, 0), (1, 0), (1, 1), (0, 1, 0)],
            [(0, 0), (1, 0), (1, 1), "ab"],
            [(0, 0), (1, 0), (1, 1), (0, "1")],
            [(0, 0), (1, 0), (1, 1), (0, None)],
            [(0, 0), (1, 0), (1, 1), (0, True)],
        ]
        for quad in bad:
            with self.subTest(quad=quad), self.assertRaises(ValueError):
                validate_quad(quad)

    def test_rejects_out_of_range_and_non_finite(self) -> None:
        for bad in (-0.01, 1.01, math.nan, math.inf, -math.inf):
            for index in range(4):
                for axis in range(2):
                    points = [list(point) for point in FULL]
                    points[index][axis] = bad
                    with self.subTest(value=bad, index=index, axis=axis):
                        with self.assertRaises(ValueError):
                            validate_quad(points)

    def test_rejects_tiny_area(self) -> None:
        # 9% x 9% of the frame is under the 1% area floor
        tiny = ((0.4, 0.4), (0.49, 0.4), (0.49, 0.49), (0.4, 0.49))
        with self.assertRaises(ValueError):
            validate_quad(tiny)
        ok = ((0.4, 0.4), (0.52, 0.4), (0.52, 0.52), (0.4, 0.52))
        self.assertEqual(validate_quad(ok), ok)

    def test_rejects_degenerate_quads(self) -> None:
        for quad in (
            ((0.2, 0.2), (0.2, 0.2), (0.8, 0.8), (0.1, 0.8)),  # repeated point
            ((0.0, 0.5), (0.5, 0.5), (1.0, 0.5), (0.5, 0.5)),  # collinear
            ((0.1, 0.1), (0.5, 0.1), (0.9, 0.1), (0.5, 0.9)),  # collinear corner
        ):
            with self.subTest(quad=quad), self.assertRaises(ValueError):
                validate_quad(quad)

    def test_rejects_non_convex(self) -> None:
        arrow = ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.3))
        dart = ((0.1, 0.1), (0.9, 0.1), (0.5, 0.4), (0.1, 0.9))
        for quad in (arrow, dart):
            with self.subTest(quad=quad), self.assertRaises(ValueError):
                validate_quad(quad)

    def test_rejects_self_intersecting_and_wrong_order(self) -> None:
        for name, quad in {
            "bowtie": ((0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)),
            "bowtie vertical": ((0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)),
            "counter-clockwise": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
            "reversed": ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
        }.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_quad(quad)


class OutputSizeTests(unittest.TestCase):
    def test_full_quad_matches_frame(self) -> None:
        self.assertEqual(PerspectiveView(FULL).output_size(640, 480), (640, 480))
        self.assertEqual(PerspectiveView(FULL).output_size(1280, 720), (1280, 720))

    def test_aspect_follows_quad_edges_in_pixels(self) -> None:
        # 50% x 25% of 640x480 is 320x120 px, aspect 8:3
        quad: Quad = ((0.25, 0.375), (0.75, 0.375), (0.75, 0.625), (0.25, 0.625))
        width, height = PerspectiveView(quad).output_size(640, 480)
        self.assertEqual((width, height), (640, 240))
        self.assertAlmostEqual(width / height, 320 / 120, places=2)

    def test_portrait_quad_fits_by_height(self) -> None:
        quad: Quad = ((0.4, 0.1), (0.6, 0.1), (0.6, 0.9), (0.4, 0.9))
        width, height = PerspectiveView(quad).output_size(640, 480)
        self.assertEqual(height, 480)
        self.assertAlmostEqual(width / height, 128 / 384, delta=0.01)

    def test_trapezoid_uses_average_edges(self) -> None:
        quad: Quad = ((0.2, 0.2), (0.8, 0.2), (1.0, 0.8), (0.0, 0.8))
        # top 384 px, bottom 640 px -> 512; both sides ~ 297 px
        width, height = PerspectiveView(quad).output_size(640, 480)
        side = math.hypot(0.2 * 640, 0.6 * 480)
        self.assertAlmostEqual(width / height, 512 / side, delta=0.02)

    def test_dimensions_are_even_and_within_the_frame(self) -> None:
        rng = np.random.default_rng(7)
        checked = 0
        while checked < 200:
            x0, y0 = rng.uniform(0, 0.4, 2)
            x1, y1 = rng.uniform(0.6, 1.0, 2)
            jitter = rng.uniform(-0.05, 0.05, 8)
            quad = (
                (x0 + max(0, jitter[0]), y0 + max(0, jitter[1])),
                (x1 + min(0, jitter[2]), y0 + max(0, jitter[3])),
                (x1 + min(0, jitter[4]), y1 + min(0, jitter[5])),
                (x0 + max(0, jitter[6]), y1 + min(0, jitter[7])),
            )
            try:
                valid = validate_quad(quad)
            except ValueError:
                continue
            checked += 1
            for width, height in ((640, 480), (1280, 720), (641, 481), (333, 777)):
                out_w, out_h = PerspectiveView(valid).output_size(width, height)
                self.assertEqual((out_w % 2, out_h % 2), (0, 0))
                self.assertGreaterEqual(min(out_w, out_h), 2)
                self.assertLessEqual(out_w, width)
                self.assertLessEqual(out_h, height)


class WarpTests(unittest.TestCase):
    def test_identity_quad_reproduces_the_frame(self) -> None:
        rng = np.random.default_rng(3)
        frame = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
        out = PerspectiveView(FULL)(frame)
        self.assertEqual(out.shape, frame.shape)
        self.assertEqual(out.dtype, np.uint8)
        diff = np.abs(out.astype(int) - frame.astype(int))
        self.assertLessEqual(int(diff.max()), 1)

    def test_inner_rectangle_fills_the_output(self) -> None:
        frame = scene()
        quad: Quad = ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))
        out = PerspectiveView(quad)(frame)
        self.assertEqual(out.shape, frame.shape)
        white = np.all(out >= 250, axis=2)
        # only the one-pixel border blends with the gray outside
        self.assertGreater(white.mean(), 0.98)
        # the surrounding gray never leaks into the middle of the output
        self.assertTrue(np.all(out[4:-4, 4:-4] >= 250))

    def test_corner_markers_land_in_output_corners(self) -> None:
        frame = np.full((240, 320, 3), 40, np.uint8)
        corners = {"tl": (60, 40), "tr": (260, 50), "br": (270, 200), "bl": (50, 190)}
        colors = {
            "tl": (0, 0, 255),
            "tr": (0, 255, 0),
            "br": (255, 0, 0),
            "bl": (0, 255, 255),
        }
        polygon = np.array([corners[k] for k in ("tl", "tr", "br", "bl")], np.int32)
        cv2.fillConvexPoly(frame, polygon, (200, 200, 200))
        for key, (x, y) in corners.items():
            cv2.circle(frame, (x, y), 4, colors[key], -1)
        quad = validate_quad([(x / 320, y / 240) for x, y in polygon.tolist()])
        out = PerspectiveView(quad)(frame)
        h, w = out.shape[:2]
        for key, (ox, oy) in {
            "tl": (3, 3),
            "tr": (w - 4, 3),
            "br": (w - 4, h - 4),
            "bl": (3, h - 4),
        }.items():
            patch = out[max(0, oy - 2) : oy + 3, max(0, ox - 2) : ox + 3].astype(int)
            expected = np.array(colors[key])
            error = np.abs(patch - expected).sum(axis=2).min()
            self.assertLess(int(error), 120, key)
        # trapezoid interior becomes a filled rectangle
        interior = out[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
        self.assertTrue(np.all(np.abs(interior.astype(int) - 200) <= 2))

    def test_keystone_straightens_a_trapezoid_checkerboard(self) -> None:
        # board drawn as a trapezoid; after the warp its square edges are vertical
        quad_px = np.array([(100, 40), (220, 40), (280, 200), (40, 200)], np.float32)
        flat = np.zeros((240, 320, 3), np.uint8)
        cell = 40
        for row in range(6):
            for col in range(8):
                if (row + col) % 2 == 0:
                    flat[
                        row * cell : (row + 1) * cell, col * cell : (col + 1) * cell
                    ] = 255
        flat_corners = np.array([(0, 0), (320, 0), (320, 240), (0, 240)], np.float32)
        to_scene = cv2.getPerspectiveTransform(flat_corners, quad_px)
        board = cast(
            Frame,
            cv2.warpPerspective(flat, to_scene, (320, 240), flags=cv2.INTER_LINEAR),
        )
        quad = validate_quad([(x / 320, y / 240) for x, y in quad_px])
        out = PerspectiveView(quad)(board)
        # output aspect comes from mean edge lengths, so compare against the
        # flat pattern resampled to the output size, away from cell edges
        out_h, out_w = out.shape[:2]
        expected = cv2.resize(flat, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
        mask = np.zeros((out_h, out_w), bool)
        cell_w, cell_h = out_w / 8, out_h / 6
        margin = 6
        for row in range(6):
            for col in range(8):
                mask[
                    int(row * cell_h) + margin : int((row + 1) * cell_h) - margin,
                    int(col * cell_w) + margin : int((col + 1) * cell_w) - margin,
                ] = True
        self.assertGreater(int(mask.sum()), 10000)
        agree = (out[mask][:, 0] > 127) == (expected[mask][:, 0] > 127)
        self.assertGreater(agree.mean(), 0.98)

    def test_output_has_the_configured_size(self) -> None:
        quad: Quad = ((0.25, 0.375), (0.75, 0.375), (0.75, 0.625), (0.25, 0.625))
        view = PerspectiveView(quad)
        for width, height in ((640, 480), (1280, 720), (320, 240)):
            frame = np.zeros((height, width, 3), np.uint8)
            out = view(frame)
            self.assertEqual(out.shape, (*view.output_size(width, height)[::-1], 3))

    def test_configure_changes_the_view(self) -> None:
        frame = scene()
        view = PerspectiveView(FULL)
        before = view(frame)
        view.configure(((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)))
        after = view(frame)
        self.assertFalse(np.array_equal(before, after))
        self.assertTrue(np.all(after[2:-2, 2:-2] >= 250))

    def test_configure_rejects_invalid_quads_and_keeps_the_old_one(self) -> None:
        frame = scene()
        view = PerspectiveView(FULL)
        before = view(frame)
        with self.assertRaises(ValueError):
            view.configure(((0, 0), (0, 1), (1, 1), (1, 0)))
        np.testing.assert_array_equal(view(frame), before)
        with self.assertRaises(ValueError):
            PerspectiveView(((0, 0), (1, 1), (1, 0), (0, 1)))

    def test_transform_is_cached_per_frame_size(self) -> None:
        view = PerspectiveView(FULL)
        state = view._state
        first = view._transform(state, 640, 480)
        self.assertIs(view._transform(state, 640, 480), first)
        self.assertIsNot(view._transform(state, 320, 240), first)
        view.configure(FULL)
        self.assertIsNot(view._transform(view._state, 640, 480), first)

    def test_input_is_not_mutated(self) -> None:
        frame = scene()
        original = frame.copy()
        out = PerspectiveView(((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)))(
            frame
        )
        np.testing.assert_array_equal(frame, original)
        self.assertFalse(np.shares_memory(out, frame))

    def test_non_contiguous_frame_warps(self) -> None:
        base = np.repeat(scene(), 2, axis=1)
        view = PerspectiveView(((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)))
        np.testing.assert_array_equal(
            view(base[:, ::2]), view(np.ascontiguousarray(base[:, ::2]))
        )


INNER: Quad = ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))


class Sink:
    def __init__(self) -> None:
        self.guides: list[object] = []

    def wants(self, view: str) -> bool:
        return view == "source"

    def publish(
        self, frame: Frame, view: str = "output", guides: object = None
    ) -> None:
        self.guides.append(guides)


class DeskViewProfileTests(unittest.TestCase):
    def test_perspective_is_validated_saved_and_live(self) -> None:
        corners = [[0.1, 0.2], [0.9, 0.2], [1, 0.9], [0, 0.9]]
        profile = Profile.parse({"perspective": corners})
        self.assertEqual(
            profile.perspective, ((0.1, 0.2), (0.9, 0.2), (1.0, 0.9), (0.0, 0.9))
        )
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = ProfileStore(Path(directory.name) / "profiles.db")
        store.save("Desk", {"perspective": corners})
        self.assertEqual(store.get("Desk"), profile)
        for bad in (
            [[0, 0], [0, 1], [1, 1], [1, 0]],
            [[0.4, 0.4], [0.45, 0.4], [0.45, 0.45], [0.4, 0.45]],
            [[0, 0], [1, 0], [1, 1.5], [0, 1]],
            "0 0 1 0 1 1 0 1",
        ):
            with self.subTest(perspective=bad):
                with self.assertRaisesRegex(ValueError, "perspective"):
                    Profile.parse({"perspective": bad})
        self.assertNotIn("perspective", RESTART_FIELDS)

    def test_desk_view_replaces_crop_and_tracking(self) -> None:
        sink = Sink()
        settings = StartupSettings(out_width=320, out_height=240)
        with patch("webcam_mods.effects.TrackingEffect") as tracking:
            tracker = tracking.return_value
            tracker.side_effect = lambda frame, region: frame
            tracker.face = tracker.crop = None
            effect = ProfileEffect(
                Profile(track=True, crop=(0, 0, 0.5, 0.5), perspective=INNER),
                settings,
                preview=sink,
            )
            self.addCleanup(effect.close)
            result = effect(scene())
            tracking.assert_not_called()
            assert result is not None
            # the white rectangle in the middle of the camera fills the picture
            self.assertEqual(result.shape, (240, 320, 3))
            self.assertTrue(np.all(result[4:-4, 4:-4] >= 250))
            self.assertEqual(sink.guides[-1], {})
            effect.update(Profile(track=True, crop=(0, 0, 0.5, 0.5)))
            effect(scene())
            tracking.assert_called_once()
            tracker.assert_called_once()

    def test_screen_sources_ignore_desk_view(self) -> None:
        effect = ProfileEffect(
            Profile(source="screen", screen_region=(0, 0, 320, 240), perspective=INNER),
            StartupSettings(out_width=320, out_height=240),
        )
        self.addCleanup(effect.close)
        result = effect(scene())
        assert result is not None
        np.testing.assert_array_equal(result, scene())


if __name__ == "__main__":
    unittest.main()
