from webcam_mods.config import (
    IN_HEIGHT,
    IN_WIDTH,
    MAX_OUT_FPS,
    NO_SIGNAL_IMAGE,
    ON_DEMAND,
    ERROR_IMAGE,
)
import cv2
from webcam_mods.uses.interactive_controls import key_listener
import platform
from loguru import logger
from webcam_mods.input.video_dev import Webcam
from webcam_mods.input.input import FrameInput, FrameOutput
import time

# We need to look at system information (os) and write to the device (fcntl)
from webcam_mods.mods.video_mods import resize_and_pad

# WARN output dimensions should be smaller than input.. for now


def default_frame_output(in_fps: int):
    out_fps = min(MAX_OUT_FPS, in_fps)
    if platform.system() == "Linux":
        from webcam_mods.output.v4l2loopback import V4l2Cam

        return V4l2Cam(fps=out_fps)
    else:
        from webcam_mods.output.pyvirtcam import PyVirtualCam

        return PyVirtualCam(fps=out_fps)


def live_loop(
    mod=None,
    on_demand=ON_DEMAND,
    fIn: FrameInput = None,
    fOut: FrameOutput = None,
    interactive_listener=key_listener,
    freeze_on_error=False,
):
    if fIn is None:
        fIn = Webcam(width=IN_WIDTH, height=IN_HEIGHT)

    if fOut is None:
        with fIn as (_, inp_props):
            if inp_props["width"] != IN_WIDTH or inp_props["height"] != IN_HEIGHT:
                logger.error(
                    f"Unexpected input resolution: {inp_props['width']}x{inp_props['height']} is not {IN_WIDTH}x{IN_HEIGHT}"
                )
                return 1
            in_fps = inp_props["fps"]
        fOut = default_frame_output(in_fps)

    logger.info(
        f"begin passing from #{fIn.__class__.__name__} to #{fOut.__class__.__name__}"
    )

    if interactive_listener is not None:
        interactive_listener.start()
    paused = False if not on_demand else True

    inp_props = fIn.setup()
    # This is the loop that reads from the input, edits, and then writes to the loopback
    with fOut as (cam, outp_props):
        logger.info(f"input: {inp_props}, output: {outp_props}")
        paused_frame = resize_and_pad(
            cv2.imread(str(NO_SIGNAL_IMAGE)), sw=fOut.width, sh=fOut.height
        )
        error_frame = resize_and_pad(
            cv2.imread(str(ERROR_IMAGE)), sw=fOut.width, sh=fOut.height
        )

        last_frame = paused_frame

        def handle_empty_frame():
            return last_frame if freeze_on_error else error_frame

        while True:
            if on_demand:
                paused = not cam.is_in_use()
                if paused:
                    fIn.teardown()

            frame = None
            if paused:
                frame = paused_frame
                time.sleep(1)  # lower the fps when paused
            else:
                if not fIn.is_setup():
                    fIn.setup()

                frame = fIn.frame()
                if frame is None:
                    continue
                try:
                    if mod:
                        frame = mod(frame)
                        if frame is not None:
                            frame = resize_and_pad(frame, sw=fOut.width, sh=fOut.height)
                            last_frame = frame
                        else:
                            frame = handle_empty_frame()
                except Exception as e:
                    logger.error(f"failed to process frame. {e}")
                    frame = handle_empty_frame()

            # assert frame.shape[0] == fOut.height
            # assert frame.shape[1] == fOut.width
            # logger.debug('sending frame shape', frame.shape)
            cam.send(frame)
            cam.wait_until_next_frame()


if __name__ == "__main__":
    live_loop()
