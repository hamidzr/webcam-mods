"""Bounded, run-owned recording and replay, and still snapshots."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import time
from typing import cast

import cv2

from webcam_mods.utils.video import Frame

# compressed recordings keep a minute or more of 720p in the default limit
_JPEG_QUALITY = 90


class Recorder:
    def __init__(
        self,
        max_bytes: int = 256 * 1024 * 1024,
        *,
        compress: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("recording limit must be positive")
        self.max_bytes = max_bytes
        # JPEG frames: about 25 times longer recordings for some encode time
        self.compress = compress
        self._clock = clock
        self.frames: list[Frame] = []
        self.size_bytes = 0
        self.index = 0
        self.recording = False
        self.replaying = False
        self._span: tuple[float, float] | None = None

    @property
    def state(self) -> str:
        """recording, replaying or idle."""
        if self.recording:
            return "recording"
        return "replaying" if self.replaying else "idle"

    @property
    def seconds(self) -> float:
        """Time from the first to the last recorded frame."""
        return 0.0 if self._span is None else self._span[1] - self._span[0]

    def command(self, action: str) -> bool:
        if action == "record":
            self.frames.clear()
            self.size_bytes = self.index = 0
            self._span = None
            self.recording, self.replaying = True, False
        elif action == "stop":
            self.recording = self.replaying = False
        elif action == "replay":
            if not self.frames:
                return False
            self.index = 0
            self.recording, self.replaying = False, True
        else:
            return False
        return True

    def engage(self, frame: Frame) -> Frame:
        if self.recording:
            stored = self._encode(frame) if self.compress else frame.copy()
            if self.size_bytes + stored.nbytes > self.max_bytes:
                self.recording = False
            else:
                self.frames.append(stored)
                self.size_bytes += stored.nbytes
                now = self._clock()
                self._span = (now if self._span is None else self._span[0], now)
        elif self.replaying:
            stored = self.frames[self.index]
            self.index = (self.index + 1) % len(self.frames)
            return self._decode(stored) if self.compress else stored.copy()
        return frame

    @staticmethod
    def _encode(frame: Frame) -> Frame:
        ok, data = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
        )
        if not ok:
            raise RuntimeError("could not compress the recorded frame")
        return cast(Frame, data)

    @staticmethod
    def _decode(data: Frame) -> Frame:
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("could not read the recorded frame")
        return cast(Frame, frame)

    def close(self) -> None:
        self.frames.clear()
        self.size_bytes = self.index = 0
        self._span = None
        self.recording = self.replaying = False


def save_snapshot(frame: Frame, directory: Path, now: datetime | None = None) -> Path:
    """Write frame as a PNG named for the time, never replacing a file."""
    ok, data = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("could not encode the snapshot")
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"Webcam Mods {(now or datetime.now()):%Y-%m-%d at %H.%M.%S}"
    for number in range(1, 1000):
        path = directory / (stem + (f" ({number})" if number > 1 else "") + ".png")
        try:
            with path.open("xb") as file:
                file.write(data.tobytes())
        except FileExistsError:
            continue
        return path
    raise RuntimeError("too many snapshots with the same time")
