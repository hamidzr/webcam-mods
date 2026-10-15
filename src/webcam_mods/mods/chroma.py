"""Chroma-key segmentation backend with edge despill."""

from collections.abc import Sequence
from typing import NamedTuple, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame, validate_frame

Mask = NDArray[np.float32]
# percent to CrCb distance; a green key sits ~80 from neutral gray
_UNITS_PER_PERCENT = 0.6
# luma floor for chroma gain, so near-black pixels do not amplify noise
_MAX_GAIN_LUMA = 40
_MIN_RAMP = 1e-3
# keys with less channel spread than this have no dominant channel to despill
_MIN_DOMINANCE = 24
_EDGE_KERNEL = (9, 9)


class _Key(NamedTuple):
    gain: Mask
    cr: float
    cb: float
    radius: float
    inv_ramp: float
    dominant: int | None
    spill: float


class ChromaKeySegmenter:
    """Key a solid backdrop color; predict() matches the person segmenter contract."""

    def __init__(
        self,
        color: tuple[int, int, int] = (64, 177, 0),
        tolerance: int = 40,
        softness: int = 30,
        spill: int = 50,
    ) -> None:
        self._key: _Key
        self.configure(color, tolerance, softness, spill)

    def configure(
        self, color: tuple[int, int, int], tolerance: int, softness: int, spill: int
    ) -> None:
        """Validate and swap all key settings at once; bad input changes nothing."""
        if (
            not isinstance(color, Sequence)
            or len(color) != 3
            or not all(_is_int(c) and 0 <= c <= 255 for c in color)
        ):
            raise ValueError("key color must be three BGR ints in 0..255")
        for name, value in (
            ("tolerance", tolerance),
            ("softness", softness),
            ("spill", spill),
        ):
            if not _is_int(value) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an int in 0..100")
        bgr = np.array([[color]], dtype=np.uint8)
        key_y, key_cr, key_cb = (
            int(v) for v in cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)[0, 0]
        )
        key_y = max(key_y, 1)
        # shadowed backdrop keeps its hue but loses chroma magnitude; scaling a
        # pixel's chroma to the key's luma makes the distance lighting-robust
        floor = min(_MAX_GAIN_LUMA, key_y)
        gain = key_y / np.maximum(np.arange(256), floor)
        spread = max(color) - min(color)
        dominant = int(np.argmax(color)) if spread >= _MIN_DOMINANCE else None
        # single assignment so a concurrent predict() sees old or new, never mixed
        self._key = _Key(
            gain.astype(np.float32),
            key_cr - 128.0,
            key_cb - 128.0,
            tolerance * _UNITS_PER_PERCENT,
            1 / max(softness * _UNITS_PER_PERCENT, _MIN_RAMP),
            dominant,
            spill / 100,
        )

    def predict(self, frame: Frame) -> Mask:
        """Return HxW float32 alpha: 1 keeps foreground, 0 is backdrop."""
        validate_frame(frame)
        key = self._key
        planes = cast(list[NDArray[np.uint8]], cv2.split(_ycrcb(frame)))
        y, cr, cb = planes
        gain = key.gain.take(y)
        dcr = np.subtract(cr, 128, dtype=np.float32)
        dcb = np.subtract(cb, 128, dtype=np.float32)
        dcr *= gain
        dcb *= gain
        dcr -= key.cr
        dcb -= key.cb
        mask = cast(Mask, cv2.magnitude(dcr, dcb))
        mask -= key.radius
        mask *= key.inv_ramp
        np.clip(mask, 0, 1, out=mask)
        # light cleanup of isolated chroma noise
        return cast(Mask, cv2.GaussianBlur(mask, (3, 3), 0))

    def despill(self, frame: Frame, mask: Mask) -> Frame:
        """Clamp the key's dominant channel to the other two near backdrop edges.

        Weight is 0 away from the backdrop, rising to full within ~4 px of it,
        scaled by spill. Pixels already at or below the clamp are untouched, so
        neutral colors never change. Keys without a dominant channel are a no-op.
        """
        validate_frame(frame)
        alpha = _plane(mask, frame)
        key = self._key
        if key.dominant is None or key.spill == 0:
            return frame.copy()
        edge = cast(Mask, cv2.blur(1.0 - alpha, _EDGE_KERNEL))
        weight = np.clip(edge * 2.0, 0.0, 1.0, out=edge)
        weight *= key.spill
        planes = list(cv2.split(frame))
        dominant = planes[key.dominant]
        others = [p for i, p in enumerate(planes) if i != key.dominant]
        excess = cv2.subtract(dominant, cv2.max(others[0], others[1]))
        reduced = dominant.astype(np.float32)
        reduced -= excess * weight
        planes[key.dominant] = cv2.convertScaleAbs(reduced)
        return cast(Frame, cv2.merge(planes))

    def close(self) -> None:
        """No resources to release; present for segmenter contract compatibility."""


def _ycrcb(frame: Frame) -> Frame:
    return cast(Frame, cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb))


def _is_int(value: object) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, bool)


def _plane(mask: Mask, frame: Frame) -> Mask:
    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.ndim == 3 and alpha.shape[2] == 1:
        alpha = alpha[:, :, 0]
    if alpha.shape != frame.shape[:2]:
        raise ValueError("mask dimensions must match frame")
    return alpha
