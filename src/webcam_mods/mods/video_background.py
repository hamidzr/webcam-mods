"""Looping video backgrounds decoded in step with wall-clock time."""

from collections.abc import Callable
import math
import time
from typing import cast

import cv2

from webcam_mods.utils.video import Frame

# processing that falls further behind than this skips ahead instead of decoding
# every missed frame
_MAX_CATCH_UP_SECONDS = 1.0


class LoopingVideo:
    """Frames of a video file at its own frame rate, starting over at the end.

    Decoding runs on the caller's thread, at most once per video frame; when
    processing runs faster than the video, the same frame object repeats, so
    callers can skip work with an identity check.
    """

    def __init__(self, path: str, *, clock: Callable[[], float] | None = None) -> None:
        self.path = path
        self._clock = clock or time.monotonic
        self._capture = cv2.VideoCapture(path)
        if not self._capture.isOpened():
            self._capture.release()
            raise ValueError("background image or video could not be read")
        frame = self._read()
        if frame is None:
            self._capture.release()
            raise ValueError("background video has no readable frames")
        fps = float(self._capture.get(cv2.CAP_PROP_FPS))
        self.fps = fps if math.isfinite(fps) and 1 <= fps <= 240 else 30.0
        self._frame = frame
        self._index = 0
        self._start = self._clock()

    def _read(self) -> Frame | None:
        ok, frame = self._capture.read()
        return cast(Frame, frame) if ok and frame is not None else None

    def frame(self) -> Frame:
        """Video frame for the current time; the first frame follows the last."""
        now = self._clock()
        # epsilon keeps exact frame boundaries from rounding down
        target = int((now - self._start) * self.fps + 1e-6)
        if target <= self._index:
            return self._frame
        if target - self._index > _MAX_CATCH_UP_SECONDS * self.fps:
            self._start = now - (self._index + 1) / self.fps
            target = self._index + 1
        while self._index < target - 1 and self._capture.grab():
            self._index += 1
        frame = self._read() if self._index == target - 1 else None
        if frame is None:
            frame = self._rewind()
            self._start, self._index = now, 0
        else:
            self._index = target
        self._frame = frame
        return frame

    def _rewind(self) -> Frame:
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        frame = self._read()
        if frame is None:
            # some containers cannot seek; reopening always starts at the top
            self._capture.release()
            self._capture = cv2.VideoCapture(self.path)
            frame = self._read()
        return frame if frame is not None else self._frame

    def close(self) -> None:
        self._capture.release()
