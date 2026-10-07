"""Demand-driven, bounded preview frames for the native control window."""

import base64
import threading
import time
from typing import Any, Callable, TypedDict, cast

import cv2

from webcam_mods.input.input import AdapterMetadata, FrameOutput
from webcam_mods.timing import FramePacer
from webcam_mods.utils.video import Frame


class PreviewFrame(TypedDict):
    jpeg: str
    width: int
    height: int


class NativePreview:
    """Keep one JPEG; encode only while the window requests frames."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._requested: float | None = None
        self._latest: PreviewFrame | None = None
        self._closed = False

    def get(self) -> PreviewFrame | None:
        with self._lock:
            if self._closed:
                return None
            now = self._clock()
            if self._requested is None or now - self._requested > 1:
                self._latest = None
            self._requested = now
            return self._latest.copy() if self._latest is not None else None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._latest = None
            self._requested = None

    def publish(self, frame: Frame) -> None:
        with self._lock:
            now = self._clock()
            if self._closed or self._requested is None or now - self._requested > 1:
                return

        height, width = frame.shape[:2]
        scale = min(1, 640 / width, 480 / height)
        width, height = max(1, int(width * scale)), max(1, int(height * scale))
        try:
            if (width, height) != (frame.shape[1], frame.shape[0]):
                frame = cast(
                    Frame,
                    cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA),
                )
            success, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            if not success or encoded.nbytes > 512 * 1024:
                return
            result: PreviewFrame = {
                "jpeg": base64.b64encode(encoded).decode("ascii"),
                "width": width,
                "height": height,
            }
        except cv2.error:
            # preview failures must not interrupt camera output
            return
        with self._lock:
            if (
                not self._closed
                and self._requested is not None
                and self._clock() - self._requested <= 1
            ):
                self._latest = result


class NativePreviewOutput(FrameOutput):
    """Headless sink for testing effects without a virtual camera driver."""

    id = "native-preview"

    def __init__(self, width: int, height: int, fps: float) -> None:
        super().__init__(width=width, height=height, fps=fps, device="native-preview")
        self._active = False
        self._pacer = FramePacer(fps)

    def setup(self) -> AdapterMetadata:
        self._active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self._active = False

    def is_setup(self) -> bool:
        return self._active

    def send(self, frame: Frame) -> None:
        pass

    def wait_until_next_frame(self) -> None:
        self._pacer.wait()

    def is_in_use(self) -> bool:
        return self._active
