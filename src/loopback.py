from sys import stderr
import pyvirtualcam
from .config import IN_HEIGHT, IN_WIDTH, MAX_OUT_FPS, no_signal_img, OUT_HEIGHT, OUT_WIDTH
from pyvirtualcam import PixelFormat
from src.uses.interactive_controls import key_listener
from inotify_simple import INotify, flags
from src.input.video_dev import Webcam
from src.input.input import FrameInput
import time
import os

# We need to look at system information (os) and write to the device (fcntl)
from src.mods.video_mods import resize_and_pad
from typing import cast

# WARN output dimensions should be smaller than input.. for now

VIDEO_OUT = 10

default_input = Webcam(width=IN_WIDTH, height=IN_HEIGHT)

def live_loop(mod=None, on_demand=False, finput: FrameInput = default_input, interactive_listener=key_listener):
    print(f'begin loopback write from #{finput.__class__.__name__} to #{VIDEO_OUT}')

    if interactive_listener is not None:
        interactive_listener.start()
    consumers = -1
    paused = False
    inotify = INotify(nonblocking=True)
    if on_demand:
        watch_flags = flags.CREATE | flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE
        inotify.add_watch(f'/dev/video{VIDEO_OUT}', watch_flags)
        paused = True


    # This is the loop that reads from the input, edits, and then writes to the loopback
    inp_props = finput.setup()
    finput.teardown()
    out_fps = min(MAX_OUT_FPS, inp_props['fps'])
    with pyvirtualcam.Camera(width=OUT_WIDTH, height=OUT_HEIGHT, fps=out_fps, fmt=PixelFormat.BGR, print_fps=True) as cam:
        print(f'Using virtual camera: {cam.device}')
        print(f'input: {inp_props}, output: ({OUT_WIDTH}, {OUT_HEIGHT}, {out_fps})')
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
                        finput.teardown()
                        print("No consumers remaining, paused")
            frame = None
            if paused:
                frame = paused_frame
                time.sleep(0.5) # lower the fps when paused
            else:
                if not finput.is_setup():
                    finput.setup()

                frame = finput.frame()
                if frame is None:
                    continue
                try:
                    if mod:
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
