"""Eye contact: irises slide up inside their lids, lids and skin stay put."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.eye_contact import correct_gaze
from webcam_mods.mods.face_landmarks import (
    LEFT_EYE,
    LEFT_IRIS,
    POINTS,
    RIGHT_EYE,
    RIGHT_IRIS,
)
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings

SKIN = (120, 150, 200)
WIDTH, HEIGHT = 200, 120
IRIS_RADIUS = 14


def eye_points(
    center: tuple[float, float], width: float, height: float, *, reverse: bool
) -> np.ndarray:
    """Face mesh eye contour: corner, lower lid, other corner, upper lid back."""
    cx, cy = center
    lower = [np.pi - i * np.pi / 8 for i in range(9)]
    upper = [i * np.pi / 8 for i in range(1, 8)]
    points = [(np.cos(a), np.sin(a)) for a in lower]
    points += [(np.cos(a), -np.sin(a)) for a in upper]
    sign = -1 if reverse else 1
    return np.array(
        [(cx + sign * x * width / 2, cy + y * height / 2) for x, y in points],
        np.float32,
    )


def scene(opening: float = 36, look_down: float = 4) -> tuple[np.ndarray, np.ndarray]:
    """Two almond eyes with dark irises low in them, and their landmarks."""
    frame = np.full((HEIGHT, WIDTH, 3), SKIN, np.uint8)
    landmarks = np.zeros((POINTS, 2), np.float32)
    for (cx, cy), eye, iris, reverse in (
        ((60, 60), LEFT_EYE, LEFT_IRIS, False),
        ((140, 60), RIGHT_EYE, RIGHT_IRIS, True),
    ):
        contour = eye_points((cx, cy), 80, opening, reverse=reverse)
        landmarks[list(eye)] = contour
        center = (cx, cy + look_down)
        landmarks[iris[0]] = center
        landmarks[list(iris[1:])] = [
            (center[0] + IRIS_RADIUS * dx, center[1] + IRIS_RADIUS * dy)
            for dx, dy in ((1, 0), (0, -1), (-1, 0), (0, 1))
        ]
        opening_mask = np.zeros((HEIGHT, WIDTH), np.uint8)
        cv2.fillPoly(opening_mask, [np.round(contour).astype(np.int32)], 255)
        layer = np.full_like(frame, 245)
        cv2.circle(layer, (cx, round(cy + look_down)), IRIS_RADIUS, (40, 50, 60), -1)
        frame[opening_mask > 0] = layer[opening_mask > 0]
    return frame, landmarks


def iris_center_y(frame: np.ndarray, x0: int, x1: int) -> float:
    dark = frame[:, x0:x1].max(axis=2) < 100
    rows = np.nonzero(dark)[0]
    return float(rows.mean())


def outside_eyes(landmarks: np.ndarray) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    for eye in (LEFT_EYE, RIGHT_EYE):
        cv2.fillPoly(mask, [np.round(landmarks[list(eye)]).astype(np.int32)], 255)
    return cv2.dilate(mask, np.ones((3, 3), np.uint8)) == 0


class CorrectGazeTests(unittest.TestCase):
    def test_irises_rise_while_everything_outside_the_eyes_stays(self) -> None:
        frame, landmarks = scene()
        corrected = correct_gaze(frame, landmarks, 100)
        self.assertEqual((corrected.shape, corrected.dtype), (frame.shape, frame.dtype))
        for x0, x1 in ((20, 100), (100, 180)):
            with self.subTest(eye=x0):
                self.assertLess(
                    iris_center_y(corrected, x0, x1),
                    iris_center_y(frame, x0, x1) - 2,
                )
        outside = outside_eyes(landmarks)
        np.testing.assert_array_equal(corrected[outside], frame[outside])

    def test_strength_scales_the_shift(self) -> None:
        frame, landmarks = scene()
        before = iris_center_y(frame, 20, 100)
        rises = [
            before - iris_center_y(correct_gaze(frame, landmarks, strength), 20, 100)
            for strength in (25, 60, 100)
        ]
        self.assertGreater(rises[0], 0)
        self.assertLess(rises[0], rises[1])
        self.assertLess(rises[1], rises[2])

    def test_zero_strength_and_closed_eyes_return_unchanged_copies(self) -> None:
        frame, landmarks = scene()
        copy = correct_gaze(frame, landmarks, 0)
        self.assertIsNot(copy, frame)
        np.testing.assert_array_equal(copy, frame)
        closed, closed_landmarks = scene(opening=6, look_down=0)
        np.testing.assert_array_equal(
            correct_gaze(closed, closed_landmarks, 100), closed
        )

    def test_eyes_at_the_frame_edge_are_clipped(self) -> None:
        frame, landmarks = scene()
        landmarks[list(LEFT_EYE + LEFT_IRIS)] -= (55, 0)
        corrected = correct_gaze(frame, landmarks, 100)
        self.assertEqual(corrected.shape, frame.shape)

    def test_validates_arguments(self) -> None:
        frame, landmarks = scene()
        for strength in (-1, 101, 50.0, True):
            with self.subTest(strength=strength):
                with self.assertRaisesRegex(ValueError, "strength"):
                    correct_gaze(frame, landmarks, strength)  # type: ignore[arg-type]
        broken = landmarks.copy()
        broken[LEFT_IRIS[0]] = np.nan
        for points in (landmarks[:468], broken):
            with self.subTest(points=len(points)):
                with self.assertRaisesRegex(ValueError, "landmarks"):
                    correct_gaze(frame, points, 50)


class FakeLandmarks:
    made: list["FakeLandmarks"] = []

    def __init__(self) -> None:
        self.points: np.ndarray | None = scene()[1]
        self.closed = False
        self.detected = 0
        FakeLandmarks.made.append(self)

    def detect(self, frame: np.ndarray) -> np.ndarray | None:
        self.detected += 1
        return self.points

    def close(self) -> None:
        self.closed = True


class ProfileEyeContactTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeLandmarks.made = []
        patcher = patch("webcam_mods.effects.FaceLandmarks", FakeLandmarks)
        patcher.start()
        self.addCleanup(patcher.stop)

    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(
            profile, StartupSettings(out_width=WIDTH, out_height=HEIGHT)
        )
        self.addCleanup(effect.close)
        return effect

    def test_field_is_validated_and_live(self) -> None:
        self.assertEqual(Profile.parse({"eye_contact": 60}).eye_contact, 60)
        for bad in (-1, 101, 2.5, True, "60"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "eye_contact"):
                    Profile.parse({"eye_contact": bad})
        self.assertNotIn("eye_contact", RESTART_FIELDS)

    def test_landmarker_follows_the_slider_and_closes_with_the_effect(self) -> None:
        frame, _ = scene()
        effect = self.effect(Profile())
        np.testing.assert_array_equal(effect(frame), frame)
        self.assertEqual(FakeLandmarks.made, [])
        effect.update(Profile(eye_contact=80))
        corrected = effect(frame)
        assert corrected is not None
        self.assertLess(
            iris_center_y(corrected, 20, 100), iris_center_y(frame, 20, 100)
        )
        (landmarks,) = FakeLandmarks.made
        # no face found leaves the picture alone
        landmarks.points = None
        np.testing.assert_array_equal(effect(frame), frame)
        effect.update(Profile())
        effect(frame)
        self.assertTrue(landmarks.closed)
        effect.update(Profile(eye_contact=40))
        effect(frame)
        effect.close()
        self.assertEqual(len(FakeLandmarks.made), 2)
        self.assertTrue(FakeLandmarks.made[1].closed)

    def test_shared_screens_only_correct_the_presenter_camera(self) -> None:
        screen = np.full((HEIGHT, WIDTH, 3), 90, np.uint8)
        region = (0, 0, WIDTH, HEIGHT)
        effect = self.effect(
            Profile(source="screen", screen_region=region, eye_contact=100)
        )
        np.testing.assert_array_equal(effect(screen), screen)
        self.assertEqual(FakeLandmarks.made, [])
        presenter = self.effect(
            Profile(
                source="screen", screen_region=region, presenter=True, eye_contact=100
            )
        )
        camera, _ = scene()
        presenter.camera_feed = lambda: camera
        presenter(screen)
        (landmarks,) = FakeLandmarks.made
        self.assertEqual(landmarks.detected, 1)


if __name__ == "__main__":
    unittest.main()
