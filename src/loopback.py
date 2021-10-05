from sys import stderr
import cv2
import pyvirtualcam
from .config import IN_HEIGHT, IN_WIDTH, MAX_OUT_FPS, no_signal_img, OUT_HEIGHT, OUT_WIDTH
from pyvirtualcam import PixelFormat
from src.uses.interactive_controls import key_listener
from inotify_simple import INotify, flags
import time

# We need to look at system information (os) and write to the device (fcntl)
import os
from src.mods.video_mods import resize_and_pad
from src.video_in_out import open_video_capture
from typing import cast
import numpy as np

# WARN output dimentions should be smaller than input.. for now

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
VIDEO_OUT = 10


def live_loop(mod, on_demand=False, interactive_listener=key_listener):
    print(f'begin loopback write from dev #{VIDEO_IN} to #{VIDEO_OUT}')

    if interactive_listener is not None:
        interactive_listener.start()
    consumers = -1
    paused = False
    inotify = INotify(nonblocking=True)
    if on_demand:
        watch_flags = flags.CREATE | flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE
        inotify.add_watch(f'/dev/video{VIDEO_OUT}', watch_flags)
        paused = True


    # This is the loop that reads from the webcam, edits, and then writes to the loopback
    cap, in_width, in_height, in_fps = open_video_capture(width=IN_WIDTH, height=IN_HEIGHT, input_dev=VIDEO_IN)
    out_fps = min(MAX_OUT_FPS, in_fps)
    # cap.release()
    with pyvirtualcam.Camera(width=OUT_WIDTH, height=OUT_HEIGHT, fps=out_fps, fmt=PixelFormat.BGR, print_fps=True) as cam:
        print(f'Using virtual camera: {cam.device}')
        print(f'input: ({in_width}, {in_height}, {in_fps}), output: ({OUT_WIDTH}, {OUT_HEIGHT}, {out_fps})')
        paused_frame = resize_and_pad(no_signal_img, sw=OUT_WIDTH, sh=OUT_HEIGHT)
        last_frame = paused_frame
        while True:
            if on_demand:
                for event in inotify.read(0):
                    for flag in flags.from_mask(event.mask):
                        if flag == flags.CLOSE_NOWRITE or flag == flags.CLOSE_WRITE:
                            consumers -= 1
                        if flag == flags.OPEN:
                            consumers += 1
                    if consumers > 0:
                        paused = False
                        print("Consumers:", consumers)
                    else:
                        consumers = 0
                        paused = True
                        if cap.isOpened():
                            cap.release()
                        print("No consumers remaining, paused")
            frame = None
            if paused:
                frame = paused_frame
                time.sleep(0.5) # lower the fps when paused
            else:
                if not cap.isOpened():
                    cap, *_ = open_video_capture(width=IN_WIDTH, height=IN_HEIGHT, input_dev=VIDEO_IN)

                ret, frame = cap.read()
                ret = cast(bool, ret)
                if not ret or frame is None:
                    continue
                try:
                    frame = mod(frame)
                    frame = resize_and_pad(
                        frame, sw=OUT_WIDTH, sh=OUT_HEIGHT)
                    last_frame = frame
                except Exception as e:
                    print(f"failed to process frame: {e}", file=stderr)
                    frame = last_frame

            # assert frame.shape[0] == OUT_HEIGHT
            # assert frame.shape[1] == OUT_WIDTH
            cam.send(frame)
            cam.sleep_until_next_frame()


if __name__ == "__main__":
    live_loop()
