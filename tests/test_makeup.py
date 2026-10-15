"""Makeup: lip color and blush placed with face mesh landmarks."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.face_landmarks import (
    CHEEKS,
    FACE_SIDES,
    LIPS_INNER,
    LIPS_OUTER,
    POINTS,
)
from webcam_mods.mods.makeup import Makeup, apply_makeup
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings

WIDTH, HEIGHT = 200, 160
SKIN = (130, 160, 210)
LIPS = (150, 140, 200)
TEETH = (235, 235, 235)
RED = (40, 30, 200)
MOUTH = (100, 120)


def lip_outline(half_width: float, half_height: float) -> np.ndarray:
    """Face mesh order: left corner, lower lip to the right corner, upper lip back."""
    lower = [np.pi - i * np.pi / 10 for i in range(11)]
    upper = [i * np.pi / 10 for i in range(1, 10)]
    points = [(np.cos(a), np.sin(a)) for a in lower]
    points += [(np.cos(a), -np.sin(a)) for a in upper]
    return np.array(
        [(MOUTH[0] + x * half_width, MOUTH[1] + y * half_height) for x, y in points],
        np.float32,
    )


def face() -> tuple[np.ndarray, np.ndarray]:
    """Skin with shaded lips around an open mouth, and its landmarks."""
    landmarks = np.zeros((POINTS, 2), np.float32)
    outer, inner = lip_outline(30, 12), lip_outline(22, 4)
    landmarks[list(LIPS_OUTER)] = outer
    landmarks[list(LIPS_INNER)] = inner
    landmarks[list(FACE_SIDES)] = [(20, 70), (180, 70)]
    landmarks[list(CHEEKS)] = [(55, 85), (145, 85)]
    frame = np.full((HEIGHT, WIDTH, 3), SKIN, np.uint8)
    lips = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.fillPoly(lips, [np.round(outer).astype(np.int32)], 255)
    cv2.fillPoly(lips, [np.round(inner).astype(np.int32)], 0)
    # lighter toward the top so shading can be checked
    shade = np.linspace(1.15, 0.85, HEIGHT)[:, None, None]
    colored = np.clip(np.array(LIPS, np.float32) * shade, 0, 255).astype(np.uint8)
    colored = np.broadcast_to(colored, frame.shape)
    frame[lips > 0] = colored[lips > 0]
    cv2.fillPoly(frame, [np.round(inner).astype(np.int32)], TEETH)
    return frame, landmarks


def lip_pixels() -> np.ndarray:
    _, landmarks = face()
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.fillPoly(mask, [np.round(landmarks[list(LIPS_OUTER)]).astype(np.int32)], 255)
    cv2.fillPoly(mask, [np.round(landmarks[list(LIPS_INNER)]).astype(np.int32)], 0)
    return cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0


def lab(pixels: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(
        pixels.reshape(-1, 1, 3).astype(np.float32) / 255, cv2.COLOR_BGR2LAB
    ).reshape(-1, 3)


class ApplyMakeupTests(unittest.TestCase):
    def test_lips_take_the_color_but_keep_shading_and_teeth(self) -> None:
        frame, landmarks = face()
        tinted = apply_makeup(frame, landmarks, Makeup(lip_color=RED, lip_strength=100))
        self.assertEqual((tinted.shape, tinted.dtype), (frame.shape, frame.dtype))
        inside = lip_pixels()
        before, after = lab(frame[inside]), lab(tinted[inside])
        target = lab(np.array([RED], np.uint8))[0]
        self.assertLess(
            np.abs(after[:, 1:].mean(0) - target[1:]).max(),
            0.3 * np.abs(before[:, 1:].mean(0) - target[1:]).max(),
        )
        self.assertGreater(after[:, 0].std(), 0.5 * before[:, 0].std())
        np.testing.assert_allclose(tinted[MOUTH[1], MOUTH[0]], TEETH, atol=3)
        # far from the mouth nothing changes
        np.testing.assert_array_equal(tinted[:60], frame[:60])

    def test_strength_scales_the_lip_color(self) -> None:
        frame, landmarks = face()
        inside = lip_pixels()
        redness = [
            lab(apply_makeup(frame, landmarks, Makeup(RED, strength))[inside])[
                :, 1
            ].mean()
            for strength in (0, 40, 100)
        ]
        self.assertLess(redness[0], redness[1])
        self.assertLess(redness[1], redness[2])

    def test_blush_warms_the_cheeks_and_fades_out(self) -> None:
        frame, landmarks = face()
        blushed = apply_makeup(frame, landmarks, Makeup(blush_strength=100))

        def warmth(x: int, y: int) -> float:
            return float(
                lab(blushed[y : y + 1, x : x + 1])[0, 1]
                - lab(frame[y : y + 1, x : x + 1])[0, 1]
            )

        for x in (55, 145):
            with self.subTest(cheek=x):
                self.assertGreater(warmth(x, 85), 5)
                self.assertGreater(warmth(x, 85), 3 * warmth(x + 30, 85))
        self.assertLess(warmth(100, 85), 0.5)
        np.testing.assert_array_equal(blushed[:20], frame[:20])

    def test_empty_makeup_returns_an_unchanged_copy(self) -> None:
        frame, landmarks = face()
        copy = apply_makeup(frame, landmarks, Makeup())
        self.assertIsNot(copy, frame)
        np.testing.assert_array_equal(copy, frame)

    def test_validates_arguments(self) -> None:
        for options in (
            {"lip_strength": 101},
            {"blush_strength": -1},
            {"lip_strength": True},
        ):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, "strength"):
                    Makeup(**options)  # type: ignore[arg-type]
        frame, landmarks = face()
        broken = landmarks.copy()
        broken[CHEEKS[0]] = np.inf
        for points in (landmarks[:400], broken):
            with self.subTest(points=len(points)):
                with self.assertRaisesRegex(ValueError, "landmarks"):
                    apply_makeup(frame, points, Makeup(lip_strength=50))


class FakeLandmarks:
    made: list["FakeLandmarks"] = []

    def __init__(self) -> None:
        self.closed = False
        FakeLandmarks.made.append(self)

    def detect(self, frame: np.ndarray) -> np.ndarray:
        return face()[1]

    def close(self) -> None:
        self.closed = True


class ProfileMakeupTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeLandmarks.made = []
        patcher = patch("webcam_mods.effects.FaceLandmarks", FakeLandmarks)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fields_are_validated_and_live(self) -> None:
        profile = Profile.parse(
            {
                "lip_color": "#a01020",
                "lip_strength": 70,
                "blush_color": "#FF8899",
                "blush_strength": 30,
            }
        )
        self.assertEqual(
            (profile.lip_color, profile.lip_bgr), ("#A01020", (32, 16, 160))
        )
        self.assertEqual(profile.blush_bgr, (153, 136, 255))
        for config in (
            {"lip_strength": 101},
            {"blush_strength": 2.5},
            {"lip_color": "red"},
            {"blush_color": None},
        ):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, next(iter(config))):
                    Profile.parse(config)
        self.assertFalse(
            {"lip_color", "lip_strength", "blush_color", "blush_strength"}
            & RESTART_FIELDS
        )

    def test_makeup_shares_the_face_mesh_with_eye_contact(self) -> None:
        frame, _ = face()
        effect = ProfileEffect(
            Profile(), StartupSettings(out_width=WIDTH, out_height=HEIGHT)
        )
        self.addCleanup(effect.close)
        np.testing.assert_array_equal(effect(frame), frame)
        effect.update(Profile(lip_color="#C81E28", lip_strength=100))
        tinted = effect(frame)
        assert tinted is not None
        inside = lip_pixels()
        self.assertGreater(
            lab(tinted[inside])[:, 1].mean(), lab(frame[inside])[:, 1].mean() + 5
        )
        effect.update(Profile(lip_strength=100, eye_contact=50))
        effect(frame)
        effect.update(Profile(eye_contact=50))
        effect(frame)
        (landmarks,) = FakeLandmarks.made
        self.assertFalse(landmarks.closed)
        effect.update(Profile())
        effect(frame)
        self.assertTrue(landmarks.closed)

    def test_shared_screens_get_no_makeup(self) -> None:
        screen, _ = face()
        effect = ProfileEffect(
            Profile(
                source="screen", screen_region=(0, 0, WIDTH, HEIGHT), lip_strength=100
            ),
            StartupSettings(out_width=WIDTH, out_height=HEIGHT),
        )
        self.addCleanup(effect.close)
        np.testing.assert_array_equal(effect(screen), screen)
        self.assertEqual(FakeLandmarks.made, [])


if __name__ == "__main__":
    unittest.main()
