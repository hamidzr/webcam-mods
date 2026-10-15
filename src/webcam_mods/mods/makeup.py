"""Lip color and blush placed with face mesh landmarks."""

from dataclasses import dataclass
import math
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.mods.face_landmarks import (
    CHEEKS,
    FACE_SIDES,
    LIPS_INNER,
    LIPS_OUTER,
    MOUTH_CORNERS,
    POINTS,
    Landmarks,
)
from webcam_mods.utils.video import Frame, validate_frame

BGR = tuple[int, int, int]
# lip edges feather over this share of the mouth width
_LIP_FEATHER = 0.015
# share of the gap between the lips' mean lightness and the color's that closes
_LIP_LIGHTNESS = 0.8
# blush spread, across and along the face, as shares of the face width
_BLUSH_WIDTH = 0.09
_BLUSH_HEIGHT = 0.065
# color shift at the middle of each cheek at full strength
_BLUSH_MAX = 0.5


@dataclass(frozen=True)
class Makeup:
    lip_color: BGR = (72, 58, 178)
    lip_strength: int = 0
    blush_color: BGR = (140, 130, 232)
    blush_strength: int = 0

    def __post_init__(self) -> None:
        for key in ("lip_strength", "blush_strength"):
            value = getattr(self, key)
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(f"{key} must be an int in 0..100")

    def is_empty(self) -> bool:
        return not (self.lip_strength or self.blush_strength)


def _lab(color: BGR) -> NDArray[np.float32]:
    pixel = np.array([[color]], np.float32) / 255
    return np.asarray(cv2.cvtColor(pixel, cv2.COLOR_BGR2LAB)[0, 0], np.float32)


def _tint(
    region: Frame, weight: NDArray[np.float32], color: BGR, lightness: float
) -> Frame:
    """Move a region's color toward a color by weight 0..1, keeping its shading."""
    lab = np.asarray(
        cv2.cvtColor(region.astype(np.float32) / 255, cv2.COLOR_BGR2LAB), np.float32
    )
    target = _lab(color)
    share = weight[:, :, None]
    lab[:, :, 1:] += (target[1:] - lab[:, :, 1:]) * share
    total = float(weight.sum())
    if lightness and total > 0:
        mean = float((lab[:, :, 0] * weight).sum()) / total
        lab[:, :, 0] += (target[0] - mean) * lightness * weight
    return cast(
        Frame, cv2.convertScaleAbs(cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), alpha=255)
    )


def _box(
    points: NDArray[np.float32], pad: float, shape: tuple[int, ...]
) -> tuple[int, int, int, int] | None:
    left = max(0, math.floor(float(points[:, 0].min()) - pad))
    top = max(0, math.floor(float(points[:, 1].min()) - pad))
    right = min(shape[1], math.ceil(float(points[:, 0].max()) + pad) + 1)
    bottom = min(shape[0], math.ceil(float(points[:, 1].max()) + pad) + 1)
    return None if left >= right or top >= bottom else (left, top, right, bottom)


def _lips(result: Frame, landmarks: Landmarks, color: BGR, strength: int) -> None:
    corners = landmarks[list(MOUTH_CORNERS)]
    width = float(np.hypot(*(corners[1] - corners[0])))
    if width < 6:
        return
    feather = max(1.0, _LIP_FEATHER * width)
    outer = landmarks[list(LIPS_OUTER)]
    box = _box(outer, 3 * feather, result.shape)
    if box is None:
        return
    left, top, right, bottom = box
    mask = np.zeros((bottom - top, right - left), np.uint8)
    for points, fill in ((outer, 255), (landmarks[list(LIPS_INNER)], 0)):
        # sixteenths of a pixel keep small mouths smooth
        shifted = np.round((points - (left, top)) * 16).astype(np.int32)
        cv2.fillPoly(mask, [shifted], fill, cv2.LINE_AA, shift=4)
    weight = np.asarray(
        cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), feather), np.float32
    )
    weight *= strength / 100
    region = result[top:bottom, left:right]
    result[top:bottom, left:right] = _tint(region, weight, color, _LIP_LIGHTNESS)


def _blush(result: Frame, landmarks: Landmarks, color: BGR, strength: int) -> None:
    sides = landmarks[list(FACE_SIDES)]
    across = sides[1] - sides[0]
    face_width = float(np.hypot(*across))
    if face_width < 20:
        return
    across /= face_width
    down = np.array([-across[1], across[0]], np.float32)
    spread_x, spread_y = _BLUSH_WIDTH * face_width, _BLUSH_HEIGHT * face_width
    for cheek in CHEEKS:
        center = landmarks[cheek]
        box = _box(center[None], 3 * max(spread_x, spread_y), result.shape)
        if box is None:
            continue
        left, top, right, bottom = box
        rows, columns = np.mgrid[top:bottom, left:right].astype(np.float32)
        x, y = columns - center[0], rows - center[1]
        u = (x * across[0] + y * across[1]) / spread_x
        v = (x * down[0] + y * down[1]) / spread_y
        weight = np.exp(-0.5 * (u * u + v * v)).astype(np.float32)
        weight *= _BLUSH_MAX * strength / 100
        region = result[top:bottom, left:right]
        result[top:bottom, left:right] = _tint(region, weight, color, 0)


def apply_makeup(frame: Frame, landmarks: Landmarks, makeup: Makeup) -> Frame:
    """Tint the lips and cheeks; empty makeup returns an unchanged copy.

    Colors replace hue and saturation but keep the picture's shading, so lips stay
    textured and teeth or an open mouth keep their own color.
    """
    validate_frame(frame)
    if landmarks.shape != (POINTS, 2) or not np.isfinite(landmarks).all():
        raise ValueError(f"landmarks must be {POINTS} finite (x, y) points")
    result = frame.copy()
    points = landmarks.astype(np.float32)
    if makeup.blush_strength:
        _blush(result, points, makeup.blush_color, makeup.blush_strength)
    if makeup.lip_strength:
        _lips(result, points, makeup.lip_color, makeup.lip_strength)
    return result
