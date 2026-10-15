"""Demand-driven, bounded preview frames for the native control window."""

import base64
import threading
import time
from typing import Any, Callable, NotRequired, TypedDict, cast

import cv2

from webcam_mods.input.input import AdapterMetadata, FrameOutput
from webcam_mods.timing import FramePacer
from webcam_mods.utils.video import Frame

# output: final frames; source: oriented camera frames before framing and
# effects; mask: segmentation confidence aligned with the output
VIEWS = ("output", "source", "mask")
Guides = dict[str, list[float]]


class PreviewFrame(TypedDict):
    jpeg: str
    width: int
    height: int
    view: str
    # normalized [x, y, width, height] boxes for the app to draw over the frame
    guides: NotRequired[Guides]


class NativePreview:
    """Keep one JPEG of the requested view; encode only while the window asks."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._requested: float | None = None
        self._view = "output"
        self._latest: PreviewFrame | None = None
        self._closed = False

    def get(self, view: str = "output") -> PreviewFrame | None:
        if view not in VIEWS:
            raise ValueError(f"view must be one of {', '.join(VIEWS)}")
        with self._lock:
            if self._closed:
                return None
            now = self._clock()
            if (
                self._requested is None
                or now - self._requested > 1
                or view != self._view
            ):
                self._latest = None
            self._requested, self._view = now, view
            return self._latest.copy() if self._latest is not None else None

    def wants(self, view: str) -> bool:
        """True while the window recently requested this view."""
        with self._lock:
            return self._wants(view)

    def _wants(self, view: str) -> bool:
        return (
            not self._closed
            and self._requested is not None
            and self._clock() - self._requested <= 1
            and self._view == view
        )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._latest = None
            self._requested = None

    def publish(
        self, frame: Frame, view: str = "output", guides: Guides | None = None
    ) -> None:
        if not self.wants(view):
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
                "view": view,
            }
            if guides:
                result["guides"] = guides
        except cv2.error:
            # preview failures must not interrupt camera output
            return
        with self._lock:
            if self._wants(view):
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
