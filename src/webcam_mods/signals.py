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
    def __init__(self, width: int, height: int, pattern: SignalPattern) -> None:
        self.width, self.height, self.pattern = width, height, pattern
        self._bars: Frame | None = None
        self._frame: Frame | None = None
        self._message = ""
        self._updated = float("-inf")
        self._random = np.random.default_rng()

    def frame(self, message: str, *, now: float | None = None) -> Frame:
        now = time.monotonic() if now is None else now
        if self._frame is not None and message == self._message:
            if self.pattern == "color-bars" or now - self._updated < 1 / 8:
                return self._frame
        if self.pattern == "color-bars":
            if self._bars is None:
                image = cv2.imread(str(NO_SIGNAL_IMAGE))
                if image is None:
                    raise RuntimeError("bundled signal image could not be read")
                self._bars = resize_and_pad(
                    cast(Frame, image), sw=self.width, sh=self.height
                )
            frame = self._bars.copy()
        else:
            # coarse grayscale grain avoids full-resolution random generation
            grain = self._random.integers(0, 256, (120, 160), dtype=np.uint8)
            grayscale = cv2.resize(
                grain, (self.width, self.height), interpolation=cv2.INTER_NEAREST
            )
            frame = cast(Frame, cv2.cvtColor(grayscale, cv2.COLOR_GRAY2BGR))
        scale = max(0.3, min(self.width / 800, self.height / 600))
        band = min(self.height, max(20, int(60 * scale)))
        cv2.rectangle(
            frame, (0, self.height - band), (self.width, self.height), (0, 0, 0), -1
        )
        cv2.putText(
            frame,
            message,
            (max(1, int(16 * scale)), self.height - max(1, int(20 * scale))),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (255, 255, 255),
            max(1, round(scale)),
            cv2.LINE_AA,
        )
        self._frame, self._message, self._updated = frame, message, now
        return frame
