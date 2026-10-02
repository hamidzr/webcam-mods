from webcam_mods.config import (
    IN_HEIGHT,
    IN_WIDTH,
    MAX_OUT_FPS,
    NO_SIGNAL_IMAGE,
    ON_DEMAND,
    ERROR_IMAGE,
)
import cv2
import platform
import math
from loguru import logger
from webcam_mods.input.video_dev import Webcam
from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.utils.video import Frame
from webcam_mods.timing import FramePacer
from typing import Any, Callable, Optional

from webcam_mods.mods.video_mods import resize_and_pad

_DEFAULT_LISTENER = object()


def default_frame_output(in_fps: float, backend: str = "virtual-cam") -> FrameOutput:
    out_fps = min(MAX_OUT_FPS, in_fps)
    if backend == "preview":
        from webcam_mods.output.gui import GUI

        return GUI(fps=out_fps)
    if backend != "virtual-cam":
        raise ValueError(f"unknown output backend: {backend}")
    if platform.system() == "Linux":
        from webcam_mods.output.v4l2loopback import V4l2Cam

        return V4l2Cam(fps=out_fps)
    else:
        from webcam_mods.output.pyvirtcam import PyVirtualCam

        return PyVirtualCam(fps=out_fps)


def _validate_metadata(properties: dict[str, Any], adapter: str) -> None:
    for name in ("width", "height", "fps"):
        value = properties.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"invalid {adapter} {name}: {value!r}")


def live_loop(
    mod: Optional[Callable[[Frame], Optional[Frame]]] = None,
    on_demand: bool = ON_DEMAND,
    fIn: Optional[FrameInput] = None,
    fOut: Optional[FrameOutput] = None,
    interactive_listener: Any = _DEFAULT_LISTENER,
    freeze_on_error: bool = False,
    max_frames: Optional[int] = None,
    strict_errors: bool = False,
    before_frame: Optional[Callable[[], None]] = None,
    output_backend: str = "virtual-cam",
    pace: bool = True,
) -> Optional[int]:
    """Pass frames through a mod; bounded runs raise on missing input."""
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be positive")
    if fIn is None:
        fIn = Webcam(width=IN_WIDTH, height=IN_HEIGHT)

    try:
        if interactive_listener is _DEFAULT_LISTENER:
            from webcam_mods.uses.interactive_controls import create_default_listener

            interactive_listener = create_default_listener()
        if before_frame is None and hasattr(interactive_listener, "apply_commands"):
            before_frame = interactive_listener.apply_commands
        if interactive_listener is not None:
            interactive_listener.start()
        paused = False if not on_demand else True

        inp_props = fIn.setup()
        _validate_metadata(inp_props, "input")
        if fOut is None:
            fOut = (
                default_frame_output(inp_props["fps"])
                if output_backend == "virtual-cam"
                else default_frame_output(inp_props["fps"], backend=output_backend)
            )
        logger.info(
            f"begin passing from #{fIn.__class__.__name__} to #{fOut.__class__.__name__}"
        )
        # This is the loop that reads from the input, edits, and then writes to the loopback
        with fOut as (cam, outp_props):
            _validate_metadata(outp_props, "output")
            logger.info(f"input: {inp_props}, output: {outp_props}")
            paused_frame = resize_and_pad(
                cv2.imread(str(NO_SIGNAL_IMAGE)), sw=fOut.width, sh=fOut.height
            )
            error_frame = resize_and_pad(
                cv2.imread(str(ERROR_IMAGE)), sw=fOut.width, sh=fOut.height
            )

            last_frame = paused_frame

            def handle_empty_frame() -> Frame:
                return last_frame if freeze_on_error else error_frame

            pacer = FramePacer(outp_props["fps"])

            def process_output_events() -> bool:
                cam.process_events()
                return not cam.should_stop()

            sent_frames = 0
            while max_frames is None or sent_frames < max_frames:
                if before_frame is not None:
                    before_frame()
                if on_demand:
                    paused = not cam.is_in_use()
                    if paused:
                        fIn.teardown()

                frame = None
                if paused:
                    frame = paused_frame
                else:
                    if not fIn.is_setup():
                        _validate_metadata(fIn.setup(), "input")

                    frame = fIn.frame()
                    if frame is None:
                        if max_frames is not None or strict_errors:
                            raise RuntimeError("input returned no frame")
                        if pace:
                            if not pacer.wait(process_events=process_output_events):
                                break
                        elif not process_output_events():
                            break
                        continue
                    try:
                        if mod:
                            frame = mod(frame)
                        if frame is not None:
                            frame = resize_and_pad(frame, sw=fOut.width, sh=fOut.height)
                            last_frame = frame
                        else:
                            if strict_errors:
                                raise RuntimeError("mod returned no frame")
                            frame = handle_empty_frame()
                    except Exception as e:
                        if strict_errors:
                            raise
                        logger.error(f"failed to process frame. {e}")
                        frame = handle_empty_frame()

                # assert frame.shape[0] == fOut.height
                # assert frame.shape[1] == fOut.width
                # logger.debug('sending frame shape', frame.shape)
                cam.send(frame)
                sent_frames += 1
                if pace:
                    if not pacer.wait(
                        interval=0.5 if paused else None,
                        process_events=process_output_events,
                    ):
                        break
                elif not process_output_events():
                    break
    finally:
        try:
            fIn.teardown()
        finally:
            if (
                interactive_listener is not None
                and interactive_listener is not _DEFAULT_LISTENER
            ):
                interactive_listener.stop()


if __name__ == "__main__":
    live_loop()
