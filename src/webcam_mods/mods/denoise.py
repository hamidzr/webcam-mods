"""Motion-adaptive temporal denoising."""

from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame, validate_frame

# smallest weight of the new frame in static areas, at full strength
_MIN_ALPHA = 0.08
# blurred gray change below _NOISE_FLOOR is noise, above _MOTION_FULL is motion
_NOISE_FLOOR = 6.0
_MOTION_FULL = 20.0
_MOTION_KERNEL = (5, 5)


class TemporalDenoiser:
    """Motion-adaptive running average; static areas average over frames, moving areas pass through."""

    def __init__(self, strength: int = 50) -> None:
        self._strength = 0
        self._static_alpha = 1.0
        self._accumulator: NDArray[np.float32] | None = None
        self.configure(strength)

    def configure(self, strength: int) -> None:
        """Set strength 0..100; 0 is identity and drops history."""
        if (
            not isinstance(strength, (int, np.integer))
            or isinstance(strength, bool)
            or not 0 <= strength <= 100
        ):
            raise ValueError("strength must be an int in 0..100")
        self._strength = int(strength)
        # quadratic keeps the low end gentle: 50 -> ~0.31, 100 -> 0.08
        self._static_alpha = _MIN_ALPHA + (1 - _MIN_ALPHA) * (1 - strength / 100) ** 2
        if self._strength == 0:
            self.reset()

    def reset(self) -> None:
        """Drop averaged history, e.g. after a scene cut."""
        self._accumulator = None

    def __call__(self, frame: Frame) -> Frame:
        validate_frame(frame)
        accumulator = self._accumulator
        if self._strength == 0:
            return frame.copy()
        if accumulator is None or accumulator.shape != frame.shape:
            self._accumulator = frame.astype(np.float32)
            return frame.copy()
        delta = np.subtract(frame, accumulator, dtype=np.float32)
        # blurred gray change so sensor noise does not read as motion
        motion = cast(
            NDArray[np.float32],
            cv2.boxFilter(
                cv2.cvtColor(delta, cv2.COLOR_BGR2GRAY), cv2.CV_32F, _MOTION_KERNEL
            ),
        )
        np.abs(motion, out=motion)
        motion -= _NOISE_FLOOR
        motion *= 1 / (_MOTION_FULL - _NOISE_FLOOR)
        np.clip(motion, 0, 1, out=motion)
        # alpha 1 on motion makes the accumulator equal the new frame: no ghosts
        motion *= 1 - self._static_alpha
        motion += self._static_alpha
        delta *= motion[:, :, None]
        accumulator += delta
        return cast(Frame, cv2.convertScaleAbs(accumulator))
