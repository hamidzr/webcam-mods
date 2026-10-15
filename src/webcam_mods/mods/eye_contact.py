"""Gaze nudged toward a camera above the screen by sliding each iris up its eye."""

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.mods.face_landmarks import (
    LEFT_EYE,
    LEFT_IRIS,
    POINTS,
    RIGHT_EYE,
    RIGHT_IRIS,
    Landmarks,
)
from webcam_mods.utils.video import Frame, validate_frame

# shares of the opening height, from each lid, over which the shift fades in; the
# iris top slides under the upper lid quickly while sclera stretches above the lower
_UPPER_RAMP = 0.2
_LOWER_RAMP = 0.45
# share of the eye width at each corner over which the shift fades in
_CORNER_RAMP = 0.25
# largest shift as a share of the iris radius
_IRIS_SHIFT = 0.6
# largest shift as a share of the local opening height; keeps the warp from folding
_OPENING_SHIFT = 0.25
# opening height to eye width below which the eye counts as closed
_CLOSED = 0.12


def _smoothstep(value: NDArray[np.float32]) -> NDArray[np.float32]:
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def _lid(points: NDArray[np.float32]) -> tuple[NDArray[np.float32], ...]:
    order = np.argsort(points[:, 0])
    return points[order, 0], points[order, 1]


def _correct_eye(
    source: Frame,
    result: Frame,
    landmarks: Landmarks,
    eye: tuple[int, ...],
    iris: tuple[int, ...],
    share: float,
) -> None:
    contour = landmarks[list(eye)]
    corner = contour[0]
    axis = contour[8] - corner
    width = float(np.hypot(*axis))
    if width < 4:
        return
    along = axis / width
    # perpendicular pointing down the picture, from the upper lid to the lower one
    across = np.array([-along[1], along[0]], np.float32)
    if across[1] < 0:
        across = -across
    local = (contour - corner) @ np.stack([along, across], axis=1)
    first, second = local[:9], local[[8, *range(9, 16), 0]]
    upper, lower = (
        (first, second) if first[:, 1].mean() < second[:, 1].mean() else (second, first)
    )
    upper_u, upper_v = _lid(upper)
    lower_u, lower_v = _lid(lower)
    center = landmarks[iris[0]]
    radius = float(np.mean(np.hypot(*(landmarks[list(iris[1:])] - center).T)))
    iris_u = float((center - corner) @ along)
    opening = float(
        np.interp(iris_u, lower_u, lower_v) - np.interp(iris_u, upper_u, upper_v)
    )
    if opening < _CLOSED * width:
        return
    shift = share * _IRIS_SHIFT * radius
    if shift < 0.05:
        return
    height, frame_width = source.shape[:2]
    left = max(0, int(np.floor(contour[:, 0].min())) - 1)
    top = max(0, int(np.floor(contour[:, 1].min())) - 1)
    right = min(frame_width, int(np.ceil(contour[:, 0].max())) + 2)
    bottom = min(height, int(np.ceil(contour[:, 1].max())) + 2)
    if left >= right or top >= bottom:
        return
    rows, columns = np.mgrid[top:bottom, left:right].astype(np.float32)
    u = (columns - corner[0]) * along[0] + (rows - corner[1]) * along[1]
    v = (columns - corner[0]) * across[0] + (rows - corner[1]) * across[1]
    lid_top = np.interp(u, upper_u, upper_v).astype(np.float32)
    span = np.maximum(np.interp(u, lower_u, lower_v) - lid_top, 1e-3, dtype=np.float32)
    t = (v - lid_top) / span
    reach = np.minimum(
        shift * _smoothstep(np.minimum(u, width - u) / (_CORNER_RAMP * width)),
        _OPENING_SHIFT * span,
    )
    reach *= _smoothstep(t / _UPPER_RAMP) * _smoothstep((1 - t) / _LOWER_RAMP)
    # each pixel shows what sits below it, so the iris rises toward the upper lid
    result[top:bottom, left:right] = cv2.remap(
        source,
        (columns + reach * across[0]).astype(np.float32),
        (rows + reach * across[1]).astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def correct_gaze(frame: Frame, landmarks: Landmarks, strength: int) -> Frame:
    """Move both irises up inside their lids; strength 0..100, 0 returns a copy.

    Lids, brows and skin keep every pixel. Closed eyes stay as they are.
    """
    validate_frame(frame)
    if (
        not isinstance(strength, (int, np.integer))
        or isinstance(strength, bool)
        or not 0 <= strength <= 100
    ):
        raise ValueError("strength must be an int in 0..100")
    if landmarks.shape != (POINTS, 2) or not np.isfinite(landmarks).all():
        raise ValueError(f"landmarks must be {POINTS} finite (x, y) points")
    result = frame.copy()
    if strength == 0:
        return result
    points = landmarks.astype(np.float32)
    for eye, iris in ((LEFT_EYE, LEFT_IRIS), (RIGHT_EYE, RIGHT_IRIS)):
        _correct_eye(frame, result, points, eye, iris, strength / 100)
    return result
