from webcam_mods import config
from webcam_mods.settings import StartupSettings, load_settings
import cv2
from webcam_mods.input.input import FrameInput
from webcam_mods.utils.video import Frame
from loguru import logger
from typing import Any, Iterator, Optional, cast
import time


def available_camera_indices(end: int = 3) -> Iterator[int]:
    """
    Check up to `end` video devices to find available ones.
    """
    index = 0
    i = end
    while i > 0:
        cap = cv2.VideoCapture(index)
        try:
            available = cap.read()[0]
        finally:
            cap.release()
        if available:
            yield index
        index += 1
        i -= 1


def open_video_capture(
    width: Optional[int] = None,
    height: Optional[int] = None,
    input_dev: int = 0,
    *,
    fps: float | None = None,
    pixel_format: str | None = None,
) -> Optional[tuple[cv2.VideoCapture, int, int, float]]:
    # Grab the webcam feed and get the dimensions of a frame
    fps = config.IN_FPS if fps is None else fps
    pixel_format = config.IN_FORMAT if pixel_format is None else pixel_format
    if len(pixel_format) != 4:
        raise ValueError("input format must contain exactly four characters")
    videoIn = cv2.VideoCapture(input_dev)

    videoIn.set(cv2.CAP_PROP_FPS, fps)
    videoIn.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*pixel_format.upper()))

    if width is not None and height is not None:
        videoIn.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        videoIn.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    if not videoIn.isOpened():
        logger.error(f"failed to open video input device #{input_dev}")
        videoIn.release()
        return None
    in_width = int(videoIn.get(cv2.CAP_PROP_FRAME_WIDTH))
    in_height = int(videoIn.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = videoIn.get(cv2.CAP_PROP_FPS)
    return (videoIn, in_width, in_height, fps)


# @contextmanager
# def video_capture(width=None, height=None, input_dev=0):
#     videoIn, in_width, in_height, fps = open_video_capture(width, height, input_dev)
#     try:
#         yield (videoIn, in_width, in_height, fps)
#     finally:
#         videoIn.release()


class Webcam(FrameInput):
    def __init__(
        self,
        device_index: int | None = None,
        *,
        settings: StartupSettings | None = None,
        **kwargs: Any,
    ) -> None:
        self.settings = settings or load_settings()
        kwargs.setdefault("width", self.settings.in_width)
        kwargs.setdefault("height", self.settings.in_height)
        kwargs.setdefault("fps", self.settings.in_fps)
        kwargs.setdefault("device", self.settings.video_out)
        super().__init__(**kwargs)
        device_index = self.settings.video_in if device_index is None else device_index
        self.cap = None
        self.device_index = (
            device_index
            if device_index is not None
            else next(available_camera_indices(end=5))
        )

    def setup(self):
        open_rv = None
        for c in range(5):
            open_rv = open_video_capture(
                width=self.width,
                height=self.height,
                input_dev=self.device_index,
                fps=self.settings.in_fps,
                pixel_format=self.settings.in_format,
            )
            if open_rv is not None:
                break
            logger.error(
                f"retrying ({c + 1}) to open video input device #{self.device_index}"
            )
            time.sleep(2)
        if open_rv is None:
            raise FileNotFoundError("failed to open video input device")
        cap, width, height, fps = open_rv
        self.cap = cap
        self.width = width
        self.height = height
        self.fps = fps
        return {"width": width, "height": height, "fps": fps}

    def teardown(self, *args: Any) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def is_setup(self):
        if self.cap is None:
            return False
        return self.cap.isOpened()

    def frame(self) -> Optional[Frame]:
        ret, frame = self.cap.read()
        ret = cast(bool, ret)
        if not ret or frame is None:
            return None
        return frame
