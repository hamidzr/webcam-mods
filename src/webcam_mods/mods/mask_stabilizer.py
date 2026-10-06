"""Temporal confidence smoothing with immediate response to visible motion."""

from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame

Mask = NDArray[np.float32]
_MOTION_KERNEL = np.ones((3, 3), np.uint8)


class MaskStabilizer:
    """Own previous image/mask for one run; never blur spatial detail."""

    def __init__(self) -> None:
        self._mask: Mask | None = None
        self._gray: NDArray[np.uint8] | None = None

    def apply(self, frame: Frame, mask: Mask) -> Mask:
        if mask.shape != frame.shape[:2]:
            raise ValueError("mask dimensions must match frame")
        gray = cast(NDArray[np.uint8], cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        previous_gray = self._gray
        previous = self._mask
        if (
            previous is None
            or previous_gray is None
            or previous.shape != mask.shape
            or float(np.abs(mask - previous).mean()) > 0.12
        ):
            result = mask.copy()
        else:
            # expand visible motion by one pixel to protect moving boundaries
            motion = cv2.absdiff(gray, previous_gray) > 12
            changed = cv2.dilate(motion.astype(np.uint8), _MOTION_KERNEL) != 0
            # local motion must not disable stabilization of stationary edges
            result = np.asarray(previous + 0.35 * (mask - previous), dtype=np.float32)
            np.copyto(result, mask, where=changed)
        self._mask = result.copy()
        self._gray = gray
        return result

    def reset(self) -> None:
        self._mask = None
        self._gray = None
