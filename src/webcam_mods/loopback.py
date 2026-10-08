from webcam_mods.config import ERROR_IMAGE
from webcam_mods.settings import StartupSettings, load_settings
import cv2
import platform
from loguru import logger
from webcam_mods.capture import create_camera
from webcam_mods.input.input import (
    AdapterMetadata,
    FrameInput,
    FrameOutput,
    validate_metadata as _validate_metadata,
)
from webcam_mods.utils.video import Frame
from webcam_mods.timing import FramePacer
from webcam_mods.signals import SignalFrames
from typing import Any, Callable, Optional, TypedDict, cast

from webcam_mods.mods.video_mods import resize_and_pad


class OutputOptions(TypedDict):
    width: int
    height: int
    fps: float
    device: str


_DEFAULT_LISTENER = object()


def default_frame_output(
    in_fps: float,
    backend: str = "virtual-cam",
    *,
    settings: StartupSettings | None = None,
) -> FrameOutput:
    settings = settings or load_settings()
    out_fps = (
        settings.max_out_fps
        if settings.repeat_frames
        else min(settings.max_out_fps, in_fps)
    )
    options: OutputOptions = dict(
        width=settings.out_width,
        height=settings.out_height,
        fps=out_fps,
        device=settings.video_out,
    )
    if backend == "native-preview":
        from webcam_mods.output.native_preview import NativePreviewOutput

        return NativePreviewOutput(settings.out_width, settings.out_height, out_fps)
    if backend == "preview":
        from webcam_mods.output.gui import GUI

        return GUI(**options)
    if backend != "virtual-cam":
        raise ValueError(f"unknown output backend: {backend}")
    if platform.system() == "Linux":
        try:
            from webcam_mods.output.v4l2loopback import V4l2Cam
        except ModuleNotFoundError as error:
            if error.name not in ("v4l2", "inotify_simple"):
                raise
            raise RuntimeError(
                "Linux virtual camera requires uv sync --extra linux"
            ) from error

        return V4l2Cam(**options)
    else:
        from webcam_mods.output.pyvirtcam import PyVirtualCam

        return PyVirtualCam(**options)


def live_loop(
    mod: Optional[Callable[[Frame], Optional[Frame]]] = None,
    on_demand: bool | None = None,
    fIn: Optional[FrameInput] = None,
    fOut: Optional[FrameOutput] = None,
    interactive_listener: Any = _DEFAULT_LISTENER,
    freeze_on_error: bool = False,
    max_frames: Optional[int] = None,
    strict_errors: bool = False,
    before_frame: Optional[Callable[[], object]] = None,
    output_backend: str = "virtual-cam",
    pace: bool = True,
    settings: StartupSettings | None = None,
    processing_cleanup: Callable[[], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_ready: Callable[[], None] | None = None,
    on_frame: Callable[[Frame], None] | None = None,
    on_output_ready: Callable[[AdapterMetadata], None] | None = None,
) -> None:
    """Pass frames through a mod; bounded runs raise on missing input."""
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be positive")
    settings = settings or load_settings()
    on_demand = settings.on_demand if on_demand is None else on_demand
    if fIn is None:
        fIn = create_camera(settings)

    from webcam_mods.frame_producer import FrameProducer

    producer: FrameProducer | None = None
    bounded_direct = max_frames is not None and not settings.repeat_frames
    try:
        if interactive_listener is _DEFAULT_LISTENER:
            from webcam_mods.uses.interactive_controls import create_default_listener

            interactive_listener = create_default_listener(settings)
        if before_frame is None and hasattr(interactive_listener, "apply_commands"):
            before_frame = interactive_listener.apply_commands
        if interactive_listener is not None:
            interactive_listener.start()

        inp_props = None
        if bounded_direct:
            inp_props = fIn.setup()
            _validate_metadata(inp_props, "input")
        else:
            producer = FrameProducer(fIn, cleanup=processing_cleanup)
        if fOut is None:
            fOut = default_frame_output(
                inp_props["fps"] if inp_props is not None else fIn.fps,
                backend=output_backend,
                settings=settings,
            )
        with fOut as (cam, outp_props):
            _validate_metadata(outp_props, "output")
            if on_output_ready is not None:
                on_output_ready(outp_props)
            signals = SignalFrames(fOut.width, fOut.height, settings.signal_pattern)
            failure_image = cv2.imread(str(ERROR_IMAGE))
            if failure_image is None:
                raise RuntimeError("bundled error image could not be read")
            error_frame = resize_and_pad(
                cast(Frame, failure_image), sw=fOut.width, sh=fOut.height
            )
            last_frame = signals.frame("Opening camera...")
            ready_reported = False

            def produce(frame: Frame) -> Frame:
                nonlocal last_frame
                try:
                    result = mod(frame) if mod else frame
                    if result is None:
                        if strict_errors:
                            raise RuntimeError("mod returned no frame")
                        return last_frame if freeze_on_error else error_frame
                    normalized = resize_and_pad(result, sw=fOut.width, sh=fOut.height)
                    last_frame = (
                        normalized.copy()
                        if settings.repeat_frames or freeze_on_error
                        else normalized
                    )
                    return last_frame
                except Exception as error:
                    if strict_errors:
                        raise
                    logger.error(f"failed to process frame. {error}")
                    return last_frame if freeze_on_error else error_frame

            # bounded direct runs export only live frames, preserving capture semantics
            if bounded_direct:
                pacer = FramePacer(outp_props["fps"])
                sent_frames = 0
                while sent_frames < cast(int, max_frames) and not (
                    should_stop is not None and should_stop()
                ):
                    if before_frame is not None:
                        before_frame()
                    paused = on_demand and not cam.is_in_use()
                    if paused:
                        fIn.teardown()
                        delivered = signals.frame("Camera paused")
                    else:
                        if not fIn.is_setup():
                            _validate_metadata(fIn.setup(), "input")
                        frame = fIn.frame()
                        if frame is None:
                            raise RuntimeError("input returned no frame")
                        delivered = produce(frame)
                    cam.send(delivered)
                    if on_frame is not None:
                        on_frame(delivered)
                    if not paused and not ready_reported:
                        ready_reported = True
                        if on_ready is not None:
                            on_ready()
                    sent_frames += 1
                    cam.process_events()
                    if cam.should_stop():
                        break
                    if pace:

                        def bounded_events() -> bool:
                            cam.process_events()
                            return not cam.should_stop() and not (
                                should_stop is not None and should_stop()
                            )

                        if not pacer.wait(
                            interval=0.5 if paused else None,
                            process_events=bounded_events,
                        ):
                            break
                return

            assert producer is not None
            producer.configure(
                produce,
                min(settings.processing_fps, outp_props["fps"]),
                before_frame=before_frame,
                strict=strict_errors or max_frames is not None,
                copy_result=False,
                continuous=settings.repeat_frames,
            )
            pacer = FramePacer(outp_props["fps"])

            def process_output_events() -> bool:
                cam.process_events()
                return not cam.should_stop() and not (
                    should_stop is not None and should_stop()
                )

            logger.info(
                "begin passing from #{} to #{}",
                fIn.__class__.__name__,
                fOut.__class__.__name__,
            )
            # output is open before capture or model startup can block
            producer.start()
            inp_props = None
            sent_frames = 0
            requested = False
            while (max_frames is None or sent_frames < max_frames) and not (
                should_stop is not None and should_stop()
            ):
                paused = on_demand and not cam.is_in_use()
                producer.enable(not paused)
                if paused:
                    requested = False
                if settings.repeat_frames:
                    completed = producer.latest()
                else:
                    if not paused and not requested:
                        producer.request_frame()
                        requested = True
                    completed = producer.take(
                        timeout=(
                            (0.1 if ready_reported else 0.01 if not pace else 0)
                            if not paused
                            else 0
                        )
                    )
                    if completed is not None:
                        requested = False
                    elif ready_reported and not paused:
                        if not process_output_events():
                            break
                        continue
                if inp_props is None:
                    inp_props = producer.metadata()
                    if inp_props is not None:
                        logger.info(f"input: {inp_props}, output: {outp_props}")
                        if not settings.repeat_frames:
                            delivered_fps = min(inp_props["fps"], outp_props["fps"])
                            pacer = FramePacer(delivered_fps)
                            if on_output_ready is not None:
                                on_output_ready({**outp_props, "fps": delivered_fps})
                if paused:
                    delivered = signals.frame("Camera paused")
                elif completed is None:
                    delivered = signals.frame(
                        "Opening camera..."
                        if inp_props is None
                        else "Preparing camera and effects..."
                    )
                else:
                    delivered = completed
                cam.send(delivered)
                if on_frame is not None:
                    on_frame(delivered)
                if completed is not None and not paused:
                    if not ready_reported:
                        ready_reported = True
                        if on_ready is not None:
                            on_ready()
                if settings.repeat_frames or completed is not None or paused:
                    sent_frames += 1
                if pace:
                    if not pacer.wait(
                        interval=0.5 if paused else None,
                        process_events=process_output_events,
                    ):
                        break
                elif not process_output_events():
                    break
        assert producer is not None
        producer.close()
        producer.latest()
    finally:
        try:
            if producer is not None:
                producer.close()
            else:
                try:
                    fIn.teardown()
                finally:
                    if processing_cleanup is not None:
                        processing_cleanup()
        finally:
            if (
                interactive_listener is not None
                and interactive_listener is not _DEFAULT_LISTENER
            ):
                interactive_listener.stop()


if __name__ == "__main__":
    live_loop()
