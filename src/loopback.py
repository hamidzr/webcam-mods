from src.output.pyvirtcam import VirtualCam
from sys import stderr
from .config import IN_HEIGHT, IN_WIDTH, MAX_OUT_FPS, no_signal_img, OUT_HEIGHT, OUT_WIDTH, VIDEO_OUT
from src.uses.interactive_controls import key_listener
from inotify_simple import INotify, flags
from src.input.video_dev import Webcam
from src.input.input import FrameInput, FrameOutput
import time

# We need to look at system information (os) and write to the device (fcntl)
from src.mods.video_mods import resize_and_pad

# WARN output dimensions should be smaller than input.. for now

default_input = Webcam(width=IN_WIDTH, height=IN_HEIGHT)
with default_input as (fIn, inp_props):
    out_fps = min(MAX_OUT_FPS, inp_props['fps'])
    default_output = VirtualCam(width=OUT_WIDTH, height=OUT_HEIGHT, fps=out_fps)

def live_loop(
    mod=None,
    on_demand=False,
    fIn: FrameInput = default_input,
    fOut: FrameOutput = default_output,
    interactive_listener=key_listener,
):
    # print(f'begin loopback write from #{input_cls.__name__} to #{output_cls.__name__}')

    if interactive_listener is not None:
        interactive_listener.start()
    consumers = 0
    paused = False
    inotify = INotify(nonblocking=True)
    if on_demand:
        watch_flags = flags.CREATE | flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE
        inotify.add_watch(f'/dev/video{VIDEO_OUT}', watch_flags)
        paused = True

    # This is the loop that reads from the input, edits, and then writes to the loopback
    with default_output as (cam, outp_props):
        print(f'input: {inp_props}, output: {outp_props}')
        paused_frame = resize_and_pad(no_signal_img, sw=fOut.width, sh=fOut.height)
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
                        fIn.teardown()
                        print("No consumers remaining, paused")
            frame = None
            if paused:
                frame = paused_frame
                time.sleep(0.5) # lower the fps when paused
            else:
                if not fIn.is_setup():
                    fIn.setup()

                frame = fIn.frame()
                if frame is None:
                    continue
                try:
                    if mod:
                        frame = mod(frame)
                    frame = resize_and_pad(
                        frame, sw=fOut.width, sh=fOut.height)
                    last_frame = frame
                except Exception as e:
                    print(f"failed to process frame: {e}", file=stderr)
                    frame = last_frame

            # assert frame.shape[0] == out_height
            # assert frame.shape[1] == out_width
            cam.send(frame)
            cam.wait_until_next_frame()


if __name__ == "__main__":
    live_loop()
