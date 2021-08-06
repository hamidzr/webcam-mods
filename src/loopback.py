import cv2
import pyvirtualcam
from pyvirtualcam import PixelFormat

# We need to look at system information (os) and write to the device (fcntl)
import os
from src.mods.video_mods import resize_and_pad
from src.raw_v4l2 import video_capture
from typing import cast
import numpy as np

# WARN output dimentions should be smaller than input.. for now

IN_WIDTH = 640
IN_HEIGHT = 480

OUT_WIDTH = 320  # 240
OUT_HEIGHT = 240  # 320


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


VIDEO_IN = os.getenv('VIDEO_IN', next(available_camera_indices()))
VIDEO_OUT = 10


def live_loop(mod=None):
    print(f'begin loopback write from dev #{VIDEO_IN} to #{VIDEO_OUT}')
    with video_capture(IN_WIDTH, IN_HEIGHT, VIDEO_IN) as cap:
        # This is the loop that reads from the webcam, edits, and then writes to the loopback
        with pyvirtualcam.Camera(width=OUT_WIDTH, height=OUT_HEIGHT, fps=30, fmt=PixelFormat.BGR, print_fps=True) as cam:
            print(f'Using virtual camera: {cam.device}')
            while True:
                ret, frame = cap.read()
                ret = cast(bool, ret)
                if not ret:
                    continue
                # WARN: frame dimensions and format has to match readV4l2
                if mod:
                    frame = mod(frame)

                frame = resize_and_pad(frame, sw=OUT_WIDTH, sh=OUT_HEIGHT)
                # assert frame.shape[0] == OUT_HEIGHT
                # assert frame.shape[1] == OUT_WIDTH
                cam.send(frame)
                cam.sleep_until_next_frame()


if __name__ == "__main__":
    live_loop()
