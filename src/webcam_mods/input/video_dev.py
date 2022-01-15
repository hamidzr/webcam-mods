from webcam_mods import config
import cv2
from webcam_mods.input.input import FrameInput
from webcam_mods.utils.video import Frame
from loguru import logger
from typing import Optional, cast
import time


def available_camera_indices(end: int = 3):
    """
    Check up to `end` video devices to find available ones.
    """
    index = 0
    i = end
    while i > 0:
        cap = cv2.VideoCapture(index)
        if cap.read()[0]:
            cap.release()
            yield index
        index += 1
        i -= 1


def open_video_capture(width=None, height=None, input_dev=0):
    # Grab the webcam feed and get the dimensions of a frame
    videoIn = cv2.VideoCapture(input_dev)

    # TODO make this a configurable cli option
    if len(config.IN_FORMAT) > 4:
        logger.error(f"input fmt can be at most 4 characters long, got {len(fmt)}")
        exit(1)

    videoIn.set(cv2.CAP_PROP_FPS, 30.0)

    videoIn.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.IN_FORMAT.lower()))
    videoIn.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.IN_FORMAT.upper()))

    if width is not None and height is not None:
        videoIn.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        videoIn.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    if not videoIn.isOpened():
        logger.error(f"failed to open video input device #{input_dev}")
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
    def __init__(self, device_index: int = None, **kwargs):
        super().__init__(**kwargs)
        self.device_index = (
            device_index or config.VIDEO_IN or next(available_camera_indices(end=5))
        )

    def setup(self):
        open_rv = None
        for c in range(5):
            open_rv = open_video_capture(
                width=self.width, height=self.height, input_dev=self.device_index
            )
            if open_rv is not None:
                break
            logger.error(
                f"retrying ({c+1}) to open video input device #{self.device_index}"
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

    def teardown(self, *args):
        if self.is_setup():
            self.cap.release()

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
