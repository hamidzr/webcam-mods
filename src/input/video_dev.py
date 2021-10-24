import cv2
from contextlib import contextmanager
import time
import os

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


VIDEO_IN = int(os.getenv('VIDEO_IN', next(available_camera_indices())))

def open_video_capture(width=None, height=None, input_dev=0):
    # Grab the webcam feed and get the dimensions of a frame
    videoIn = cv2.VideoCapture(input_dev)
    if not videoIn.isOpened():
        # raise ValueError("error opening video")
        print(f"failed to open video input device #{input_dev}")
        time.sleep(1) # FIXME
        return (videoIn, 0, 0 , 0)
    # length = int(videoIn.get(cv2.CAP_PROP_FRAME_COUNT))
    # width = int(videoIn.get(cv2.CAP_PROP_FRAME_WIDTH))
    # height = int(videoIn.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # fps = videoIn.get(cv2.CAP_PROP_FPS)
    if (width is not None and height is not None):
        videoIn.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        videoIn.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    # videoIn.set(cv2.CAP_PROP_FPS, 30)
    in_width = int(videoIn.get(cv2.CAP_PROP_FRAME_WIDTH))
    in_height = int(videoIn.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = videoIn.get(cv2.CAP_PROP_FPS)
    return (videoIn, in_width, in_height, fps)


@contextmanager
def video_capture(width=None, height=None, input_dev=0):
    videoIn, in_width, in_height, fps = open_video_capture(width, height, input_dev)
    try:
        yield (videoIn, in_width, in_height, fps)
    finally:
        videoIn.release()
