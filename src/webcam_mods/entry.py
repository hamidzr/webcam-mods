from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
import importlib.util
import sys
from pathlib import Path
from typing import Callable, Literal, cast
from webcam_mods.utils.video import Frame
from webcam_mods.macos.vision import Quality

import cv2
import numpy as np
import typer

from webcam_mods.config import DEFAULT_BG_IMAGE
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.loopback import live_loop
from webcam_mods.mods.video_mods import brighten as brighten_mod, crop_rect
from webcam_mods.output.gui import GUI
from webcam_mods.session import RunSession
from webcam_mods.uses.interactive_controls import ControlAdapters

app = typer.Typer()


class OutputBackend(str, Enum):
    virtual_cam = "virtual-cam"
    preview = "preview"


class SegmentationBackend(str, Enum):
    mediapipe = "mediapipe"
    vision = "vision"


class ProcessingBackend(str, Enum):
    opencv = "opencv"
    coreimage = "coreimage"


class CaptureBackend(str, Enum):
    opencv = "opencv"
    avfoundation = "avfoundation"


class VisionQuality(str, Enum):
    fast = "fast"
    balanced = "balanced"
    accurate = "accurate"


@dataclass
class Common:
    freeze_on_error: bool = False
    controls: bool = True
    segmentation: Literal["mediapipe", "vision"] = "mediapipe"
    processing: Literal["opencv", "coreimage"] = "opencv"
    capture: str = "opencv"
    quality: Quality = "balanced"
    recording_limit_mb: int = 256
    output: str = "virtual-cam"
    settings: StartupSettings | None = None
    mask_smoothing: bool = False


def _run(
    common: Common,
    effect: Callable[[Frame], Frame | None] | None = None,
    *,
    prepare: bool = True,
) -> None:
    settings = common.settings or load_settings()
    with ExitStack() as resources:
        if effect is not None and hasattr(effect, "close"):
            resources.callback(effect.close)
        session = RunSession(
            recording_limit=common.recording_limit_mb * 1024 * 1024, startup=settings
        )
        resources.callback(session.close)
        controls = (
            ControlAdapters(session, settings=settings)
            if common.controls and prepare
            else None
        )
        source = None
        if common.capture == "avfoundation":
            from webcam_mods.macos.capture import AVFoundationCamera

            source = AVFoundationCamera(
                device_index=settings.video_in,
                width=settings.in_width,
                height=settings.in_height,
                fps=settings.in_fps,
                device=settings.video_out,
            )

        def process(frame: Frame) -> Frame | None:
            if prepare:
                frame = session.prepare(frame)
            return effect(frame) if effect is not None else frame

        live_loop(
            mod=process,
            fIn=source,
            interactive_listener=controls,
            before_frame=session.apply_commands,
            freeze_on_error=common.freeze_on_error,
            output_backend=common.output,
            settings=settings,
        )


def _common(ctx: typer.Context) -> Common:
    if not isinstance(ctx.obj, Common):
        raise RuntimeError("CLI startup settings are unavailable")
    return ctx.obj


class BackgroundEffect:
    def __init__(
        self,
        common: Common,
        mode: Literal["blur_bg", "color_bg", "swap_bg"],
        value: int | Frame,
        brightness: int = 0,
    ) -> None:
        from webcam_mods.mods.person_segmentation import PersonEffects

        self.effects = PersonEffects(
            backend=common.segmentation,
            processing=common.processing,
            quality=common.quality,
            smoothing=common.mask_smoothing,
        )
        if mode == "swap_bg":
            if not isinstance(value, np.ndarray):
                raise TypeError("background replacement requires an image")
            self.transform: Callable[[Frame], Frame] = (
                lambda frame: self.effects.swap_bg(frame, value)
            )
        else:
            if not isinstance(value, int):
                raise TypeError("background color and blur require an integer")
            self.transform = (
                (lambda frame: self.effects.blur_bg(frame, value))
                if mode == "blur_bg"
                else (lambda frame: self.effects.color_bg(frame, value))
            )
        self.brightness = brightness

    def __call__(self, frame: Frame) -> Frame:
        result = self.transform(frame)
        return brighten_mod(result, self.brightness) if self.brightness else result

    def close(self) -> None:
        self.effects.close()


@app.command()
def crop_cam(ctx: typer.Context) -> None:
    """Interactive crop, padding and bounded recording/replay."""
    _run(_common(ctx))


@app.command()
def bg_color(
    ctx: typer.Context, color: int = typer.Option(192, min=0, max=255)
) -> None:
    """Basic controls and a solid color background."""
    _run(_common(ctx), BackgroundEffect(_common(ctx), "color_bg", color))


@app.command()
def bg_swap(ctx: typer.Context, img_path: str = str(DEFAULT_BG_IMAGE)) -> None:
    """Basic controls and image background replacement."""
    background = cv2.imread(str(Path(img_path)))
    if background is None:
        raise typer.BadParameter(
            "background image could not be read", param_hint="img-path"
        )
    _run(
        _common(ctx), BackgroundEffect(_common(ctx), "swap_bg", cast(Frame, background))
    )


@app.command()
def bg_blur(
    ctx: typer.Context,
    kernel_size: int = typer.Option(31, min=1),
    brighten: int = typer.Option(0, min=0, max=255),
) -> None:
    """Blur background; kernel size must be odd. Core Image uses Gaussian blur."""
    if kernel_size % 2 == 0:
        raise typer.BadParameter("kernel size must be odd", param_hint="kernel-size")
    _run(_common(ctx), BackgroundEffect(_common(ctx), "blur_bg", kernel_size, brighten))


@app.command()
def brighten(ctx: typer.Context, level: int = typer.Option(30, min=0, max=255)) -> None:
    """Increase HSV brightness by LEVEL."""
    _run(_common(ctx), lambda frame: brighten_mod(frame, level))


@app.command()
def track_face(
    ctx: typer.Context,
    x_padding: float = typer.Option(2, min=0.01),
    y_padding: float = typer.Option(2.5, min=0.01),
    blur: bool = False,
    blur_kernel_size: int = typer.Option(31, min=1),
) -> None:
    """Smooth crop around the first detected face; optionally blur background."""
    from webcam_mods.mods.camera_motion import CropTracker
    from webcam_mods.mods.mp_face import FaceDetector

    if blur_kernel_size % 2 == 0:
        raise typer.BadParameter("blur kernel size must be odd")
    with ExitStack() as resources:
        detector = FaceDetector()
        resources.callback(detector.close)
        settings = _common(ctx).settings or load_settings()
        tracker = CropTracker(fps=min(settings.in_fps, settings.max_out_fps))
        resources.callback(tracker.close)
        background = (
            BackgroundEffect(_common(ctx), "blur_bg", blur_kernel_size)
            if blur
            else None
        )
        if background is not None:
            resources.callback(background.close)
        last_prediction = None

        def process(frame: Frame) -> Frame | None:
            nonlocal last_prediction
            prediction = detector.predict(frame)
            if prediction is not None:
                last_prediction = prediction
            elif last_prediction is None:
                return frame
            result = crop_rect(
                frame, tracker.generate_crop(last_prediction, (x_padding, y_padding))
            )
            return background(result) if result is not None and background else result

        _run(_common(ctx), process, prepare=False)


@app.command()
def share_screen(
    top: int = 0,
    left: int = 0,
    width: int = 640,
    height: int = 480,
    output: str = "virtual-cam",
) -> None:
    """Share a portion of the screen."""
    from webcam_mods.input.screen import Screen

    screen = Screen(top=top, left=left, width=width, height=height)
    if output == GUI.id:
        gui = GUI(width=width, height=height)
        live_loop(fIn=screen, fOut=gui)
    else:
        live_loop(fIn=screen)


@app.command()
def test_loop(ctx: typer.Context) -> None:
    """Camera pass-through for delivery checks."""
    _run(_common(ctx), prepare=False)


@app.command()
def list_cameras() -> None:
    """List macOS native input indices and formats without opening cameras."""
    if sys.platform != "darwin":
        raise typer.BadParameter("list-cameras requires macOS")
    try:
        from webcam_mods.macos.capture import camera_inventory

        cameras = camera_inventory()
    except ImportError as error:
        raise typer.BadParameter(
            "list-cameras requires uv sync --extra macos"
        ) from error
    if not cameras:
        typer.echo("No cameras found.")
    for camera in cameras:
        label = (
            f"excluded ({camera.excluded_reason})"
            if camera.excluded_reason
            else f"--input-device {camera.input_index}"
        )
        typer.echo(f"{label}: {camera.name}")
        for capture_format in camera.formats:
            typer.echo(f"  {capture_format}")


@app.callback()
def common(
    ctx: typer.Context,
    freeze_on_error: bool = typer.Option(False, envvar="freeze_on_error"),
    controls: bool = typer.Option(True, help="Enable keyboard and stdin controls."),
    segmentation_backend: SegmentationBackend = SegmentationBackend.mediapipe,
    processing_backend: ProcessingBackend = ProcessingBackend.opencv,
    capture_backend: CaptureBackend = CaptureBackend.opencv,
    vision_quality: VisionQuality = VisionQuality.balanced,
    mask_smoothing: bool = typer.Option(
        False, help="Stabilize static segmentation edges; reset moving pixels."
    ),
    recording_limit_mb: int = typer.Option(256, min=1),
    output: OutputBackend = typer.Option(
        OutputBackend.virtual_cam, help="Final-frame output destination."
    ),
    input_device: int | None = typer.Option(
        None, min=0, help="Camera index; AVFoundation excludes OBS output devices."
    ),
    input_width: int | None = typer.Option(None, min=1),
    input_height: int | None = typer.Option(None, min=1),
    input_fps: float | None = typer.Option(None, min=0.01),
    input_format: str | None = None,
    output_width: int | None = typer.Option(None, min=1),
    output_height: int | None = typer.Option(None, min=1),
    output_fps: float | None = typer.Option(None, min=0.01),
    output_device: str | None = None,
    on_demand: bool | None = typer.Option(None, "--on-demand/--no-on-demand"),
    pan_control: bool | None = typer.Option(None, "--pan-control/--no-pan-control"),
    padding_control: bool | None = typer.Option(
        None, "--padding-control/--no-padding-control"
    ),
) -> None:
    try:
        settings = load_settings(
            video_in=input_device,
            in_width=input_width,
            in_height=input_height,
            in_fps=input_fps,
            in_format=input_format,
            out_width=output_width,
            out_height=output_height,
            max_out_fps=output_fps,
            video_out=output_device,
            on_demand=on_demand,
            pan_control=pan_control,
            padding_control=padding_control,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    native_modules: set[str] = set()
    if segmentation_backend == SegmentationBackend.vision:
        native_modules.update(("Vision", "Quartz"))
    if processing_backend == ProcessingBackend.coreimage:
        native_modules.add("Quartz")
    if capture_backend == CaptureBackend.avfoundation:
        native_modules.update(("AVFoundation", "CoreMedia", "libdispatch", "Quartz"))
    if native_modules:
        if sys.platform != "darwin":
            raise typer.BadParameter("native backends require macOS")
        if any(importlib.util.find_spec(name) is None for name in native_modules):
            raise typer.BadParameter("native backends require uv sync --extra macos")
    ctx.obj = Common(
        freeze_on_error,
        controls,
        segmentation_backend.value,
        processing_backend.value,
        capture_backend.value,
        vision_quality.value,
        recording_limit_mb,
        output.value,
        settings,
        mask_smoothing,
    )


if __name__ == "__main__":
    app()
