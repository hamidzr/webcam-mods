"""Shared status frames, generated only while live video is unavailable."""

import time
from typing import cast

import cv2
import numpy as np

from webcam_mods.config import NO_SIGNAL_IMAGE
from webcam_mods.mods.video_mods import resize_and_pad
from webcam_mods.utils.video import Frame
from webcam_mods.settings import SignalPattern


class SignalFrames:
    """Picture-only frames; receivers are public, so no status text is drawn."""

    def __init__(self, width: int, height: int, pattern: SignalPattern) -> None:
        self.width, self.height, self.pattern = width, height, pattern
        self._frame: Frame | None = None
        self._updated = float("-inf")
        self._random = np.random.default_rng()

    def frame(self, *, now: float | None = None) -> Frame:
        now = time.monotonic() if now is None else now
        if self._frame is not None:
            if self.pattern == "color-bars" or now - self._updated < 1 / 8:
                return self._frame
        if self.pattern == "color-bars":
            image = cv2.imread(str(NO_SIGNAL_IMAGE))
            if image is None:
                raise RuntimeError("bundled signal image could not be read")
            frame = resize_and_pad(cast(Frame, image), sw=self.width, sh=self.height)
        else:
            # coarse grayscale grain avoids full-resolution random generation
            grain = self._random.integers(0, 256, (120, 160), dtype=np.uint8)
            grayscale = cv2.resize(
                grain, (self.width, self.height), interpolation=cv2.INTER_NEAREST
            )
            frame = cast(Frame, cv2.cvtColor(grayscale, cv2.COLOR_GRAY2BGR))
        self._frame, self._updated = frame, now
        return frame
