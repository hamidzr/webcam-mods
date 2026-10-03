from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable, Literal, cast
from webcam_mods.utils.video import Frame
from webcam_mods.input.input import FrameInput
from webcam_mods.cli import SharedOptionsCommand, SharedOptionsGroup
from webcam_mods.macos.vision import Quality

import cv2
import numpy as np
import typer

from webcam_mods.config import DEFAULT_BG_IMAGE
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.loopback import live_loop
from webcam_mods.mods.video_mods import brighten as brighten_mod, crop_rect
from webcam_mods.session import RunSession
from webcam_mods.uses.interactive_controls import ControlAdapters

app = typer.Typer(
    cls=SharedOptionsGroup,
    no_args_is_help=True,
    help="Camera effects and screen sharing. Common options work before or after commands.",
    epilog="Run COMMAND --help for all common and command-specific options.\n"
    "Examples: webcam_mods bg-blur --output preview --no-controls\n"
    "webcam_mods share-screen --width 1280 --height 720 --output preview",
)


class OutputBackend(str, Enum):
    virtual_cam = "virtual-cam"
    preview = "preview"
    gui = "gui"


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
    source: FrameInput | None = None,
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
        if source is None and common.capture == "avfoundation":
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


@app.command(cls=SharedOptionsCommand, rich_help_panel="Camera")
def crop_cam(ctx: typer.Context) -> None:
    """Interactive crop, padding and bounded recording/replay."""
    _run(_common(ctx))


@app.command(cls=SharedOptionsCommand, rich_help_panel="Background")
def bg_color(
    ctx: typer.Context, color: int = typer.Option(192, min=0, max=255)
) -> None:
    """Basic controls and a solid color background."""
    _run(_common(ctx), BackgroundEffect(_common(ctx), "color_bg", color))


@app.command(cls=SharedOptionsCommand, rich_help_panel="Background")
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


@app.command(cls=SharedOptionsCommand, rich_help_panel="Background")
def bg_blur(
    ctx: typer.Context,
    kernel_size: int = typer.Option(31, min=1),
    brighten: int = typer.Option(0, min=0, max=255),
) -> None:
    """Blur background; kernel size must be odd. Core Image uses Gaussian blur."""
    if kernel_size % 2 == 0:
        raise typer.BadParameter("kernel size must be odd", param_hint="kernel-size")
    _run(_common(ctx), BackgroundEffect(_common(ctx), "blur_bg", kernel_size, brighten))


@app.command(cls=SharedOptionsCommand, rich_help_panel="Camera")
def brighten(ctx: typer.Context, level: int = typer.Option(30, min=0, max=255)) -> None:
    """Increase HSV brightness by LEVEL."""
    _run(_common(ctx), lambda frame: brighten_mod(frame, level))


@app.command(cls=SharedOptionsCommand, rich_help_panel="Camera")
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
        tracker = CropTracker(
            fps=(
                min(settings.in_fps, settings.processing_fps, settings.max_out_fps)
                if settings.repeat_frames
                else min(settings.in_fps, settings.max_out_fps)
            )
        )
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


@app.command(cls=SharedOptionsCommand, rich_help_panel="Screen")
def share_screen(
    ctx: typer.Context,
    top: int = typer.Option(
        0, help="Capture region's top edge; negative values allowed."
    ),
    left: int = typer.Option(
        0, help="Capture region's left edge; negative values allowed."
    ),
    width: int | None = typer.Option(
        None, min=1, help="Region width; defaults to input width."
    ),
    height: int | None = typer.Option(
        None, min=1, help="Region height; defaults to input height."
    ),
) -> None:
    """Share a screen region with the same output and controls as camera commands."""
    from webcam_mods.input.screen import Screen

    common = _common(ctx)
    settings = common.settings or load_settings()
    if common.capture != "opencv":
        raise typer.BadParameter(
            "--capture-backend selects cameras, not screen capture"
        )
    screen = Screen(
        top=top,
        left=left,
        width=width if width is not None else settings.in_width,
        height=height if height is not None else settings.in_height,
        fps=settings.in_fps,
        device=settings.video_out,
    )
    _run(common, source=screen)


@app.command(cls=SharedOptionsCommand, rich_help_panel="Utilities")
def test_loop(ctx: typer.Context) -> None:
    """Camera pass-through for delivery checks."""
    _run(_common(ctx), prepare=False)


@app.command(cls=SharedOptionsCommand, rich_help_panel="Utilities")
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
    freeze_on_error: bool | None = typer.Option(
        None,
        "--freeze-on-error/--no-freeze-on-error",
        rich_help_panel="Output",
        hidden=True,
    ),
    controls: bool = typer.Option(
        True,
        help="Enable keyboard and stdin controls.",
        rich_help_panel="Controls",
        show_default=False,
    ),
    segmentation_backend: SegmentationBackend = typer.Option(
        SegmentationBackend.mediapipe,
        rich_help_panel="Effects",
        metavar="BACKEND",
        help="mediapipe or vision.",
    ),
    processing_backend: ProcessingBackend = typer.Option(
        ProcessingBackend.opencv,
        rich_help_panel="Effects",
        metavar="BACKEND",
        help="opencv or coreimage.",
    ),
    capture_backend: CaptureBackend = typer.Option(
        CaptureBackend.opencv,
        help="Camera capture backend (screen uses MSS).",
        rich_help_panel="Input",
        metavar="BACKEND",
    ),
    vision_quality: VisionQuality = typer.Option(
        VisionQuality.balanced, rich_help_panel="Effects", hidden=True
    ),
    mask_smoothing: bool = typer.Option(
        False,
        help="Stabilize static segmentation edges; reset moving pixels.",
        rich_help_panel="Effects",
        hidden=True,
    ),
    recording_limit_mb: int = typer.Option(
        256, min=1, rich_help_panel="Controls", hidden=True
    ),
    output: OutputBackend = typer.Option(
        OutputBackend.virtual_cam,
        help="Final-frame destination; gui is a legacy alias for preview.",
        rich_help_panel="Output",
        metavar="DESTINATION",
    ),
    input_device: int | None = typer.Option(
        None,
        min=0,
        help="Camera index; omit for terminal picker on macOS. AVFoundation excludes OBS output.",
        rich_help_panel="Input",
    ),
    input_width: int | None = typer.Option(
        None,
        min=1,
        help="Requested capture width; camera must support this resolution/FPS.",
        rich_help_panel="Input",
        hidden=True,
    ),
    input_height: int | None = typer.Option(
        None,
        min=1,
        help="Requested capture height; independent of output height.",
        rich_help_panel="Input",
        hidden=True,
    ),
    input_fps: float | None = typer.Option(
        None,
        min=0.01,
        help="Requested camera FPS; not an output-only processing cap.",
        rich_help_panel="Input",
        hidden=True,
    ),
    input_format: str | None = typer.Option(None, rich_help_panel="Input", hidden=True),
    output_width: int | None = typer.Option(
        None,
        min=1,
        help="Delivered frame width; resize and pad to preserve aspect ratio.",
        rich_help_panel="Output",
        hidden=True,
    ),
    output_height: int | None = typer.Option(
        None,
        min=1,
        help="Delivered frame height; independent of capture height.",
        rich_help_panel="Output",
        hidden=True,
    ),
    output_fps: float | None = typer.Option(
        None,
        min=0.01,
        help="Delivery FPS cap; --repeat-frames keeps cadence independent of processing.",
        rich_help_panel="Output",
        hidden=True,
    ),
    repeat_frames: bool | None = typer.Option(
        None,
        "--repeat-frames/--no-repeat-frames",
        help="Repeat latest completed frame at output FPS while effects run separately.",
        rich_help_panel="Output",
        hidden=True,
    ),
    processing_fps: float | None = typer.Option(
        None,
        min=0.01,
        help="Fresh-frame processing cap in repeat mode; defaults to 30 FPS.",
        rich_help_panel="Output",
        hidden=True,
    ),
    output_device: str | None = typer.Option(
        None, rich_help_panel="Output", hidden=True
    ),
    on_demand: bool | None = typer.Option(
        None, "--on-demand/--no-on-demand", rich_help_panel="Output", hidden=True
    ),
    pan_control: bool | None = typer.Option(
        None, "--pan-control/--no-pan-control", rich_help_panel="Controls", hidden=True
    ),
    padding_control: bool | None = typer.Option(
        None,
        "--padding-control/--no-padding-control",
        rich_help_panel="Controls",
        hidden=True,
    ),
) -> None:
    if freeze_on_error is None:
        raw_freeze = os.environ.get("freeze_on_error", "false").lower()
        if raw_freeze not in ("true", "false", "1", "0"):
            raise typer.BadParameter("freeze_on_error must be true/false or 1/0")
        freeze_on_error = raw_freeze in ("true", "1")
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
            repeat_frames=repeat_frames,
            processing_fps=processing_fps,
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
        "preview" if output == OutputBackend.gui else output.value,
        settings,
        mask_smoothing,
    )


if __name__ == "__main__":
    app()
