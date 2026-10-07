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
from webcam_mods.input.screen import (
    Screen,
    ScreenBorder,
    ScreenSelection,
    select_screen_region,
)
from webcam_mods.utils.config import Config
from webcam_mods.geometry import Rect
from webcam_mods.capture import CaptureBackend as CaptureMode, create_camera
from webcam_mods.cli import SharedOptionsCommand, SharedOptionsGroup
from webcam_mods.macos.vision import Quality

import cv2
import numpy as np
import typer

from webcam_mods.config import DEFAULT_BG_IMAGE
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.loopback import live_loop
from webcam_mods.mods.video_mods import brighten as brighten_mod
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


class SignalPattern(str, Enum):
    color_bars = "color-bars"
    noise = "noise"


class SegmentationBackend(str, Enum):
    mediapipe = "mediapipe"
    vision = "vision"


class ProcessingBackend(str, Enum):
    opencv = "opencv"
    coreimage = "coreimage"


class CaptureBackend(str, Enum):
    auto = "auto"
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
    capture: CaptureMode = "auto"
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
    border: ScreenBorder | None = None,
) -> None:
    settings = common.settings or load_settings()
    with ExitStack() as resources:
        if effect is not None and hasattr(effect, "close"):
            resources.callback(effect.close)
        session = RunSession(
            settings=(
                Config(path=None, width=source.width, height=source.height)
                if isinstance(source, Screen)
                else None
            ),
            recording_limit=common.recording_limit_mb * 1024 * 1024,
            startup=settings,
        )
        resources.callback(session.close)
        controls = (
            ControlAdapters(session, settings=settings)
            if common.controls and prepare
            else None
        )
        if source is None:
            source = create_camera(settings, common.capture)

        if border is not None:
            resources.callback(border.close)
            border.start()

        def process(frame: Frame) -> Frame | None:
            if prepare:
                frame = session.prepare(frame)
                if border is not None and isinstance(source, Screen):
                    crop = session.settings
                    border.update(
                        Rect(
                            l=source.left + crop.crop_pos[0],
                            t=source.top + crop.crop_pos[1],
                            w=crop.crop_dims[0],
                            h=crop.crop_dims[1],
                        )
                    )
            return effect(frame) if effect is not None else frame

        from webcam_mods.frame_producer import WorkerShutdownTimeout

        processing_resources = resources.pop_all()
        try:
            live_loop(
                mod=process,
                fIn=source,
                interactive_listener=controls,
                before_frame=session.apply_commands,
                freeze_on_error=common.freeze_on_error,
                output_backend=common.output,
                settings=settings,
                processing_cleanup=processing_resources.close,
            )
        except WorkerShutdownTimeout:
            # worker retains cleanup ownership until its in-flight call returns
            raise
        except BaseException:
            processing_resources.close()
            raise
        else:
            processing_resources.close()


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
            self.effects.set_background(value)
            self.transform: Callable[[Frame], Frame] = self.effects.swap_bg
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
    x_padding: float | None = typer.Option(
        None,
        min=0.01,
        help="Legacy minimum width context ratio; overrides face-height with y-padding.",
    ),
    y_padding: float | None = typer.Option(
        None,
        min=0.01,
        help="Legacy minimum height context ratio; overrides face-height with x-padding.",
    ),
    face_height: float = typer.Option(
        0.4, min=0.01, max=1, help="Target face height as fraction of output."
    ),
    max_zoom: float = typer.Option(
        2.0, min=1, help="Maximum digital zoom relative to widest fitted view."
    ),
    target_x: float = typer.Option(
        0.5, min=0, max=1, help="Horizontal face position in output."
    ),
    target_y: float = typer.Option(
        0.42, min=0, max=1, help="Vertical face position in output."
    ),
    pan_deadzone: float = typer.Option(
        0.08, min=0, max=0.99, help="Allowed drift per axis as fraction of crop size."
    ),
    zoom_deadzone: float = typer.Option(
        0.08, min=0, max=0.99, help="Ignored relative crop size change."
    ),
    pan_seconds: float = typer.Option(
        0.25, min=0.01, help="Pan response time constant in seconds."
    ),
    zoom_seconds: float = typer.Option(
        0.6, min=0.01, help="Zoom response time constant in seconds."
    ),
    lost_after: float = typer.Option(
        1.0, min=0, help="Hold framing before widening/reselecting after face loss."
    ),
    blur: bool = False,
    blur_kernel_size: int = typer.Option(31, min=1),
) -> None:
    """Follow one face with bounded zoom and stable output proportions."""
    from webcam_mods.effects import TrackingEffect

    if blur_kernel_size % 2 == 0:
        raise typer.BadParameter("blur kernel size must be odd")
    common = _common(ctx)
    settings = common.settings or load_settings()
    background = BackgroundEffect(common, "blur_bg", blur_kernel_size) if blur else None
    padding = (
        (x_padding or 2.0, y_padding or 2.5)
        if x_padding is not None or y_padding is not None
        else None
    )
    effect = TrackingEffect(
        settings,
        background=background,
        padding=padding,
        face_height=face_height,
        max_zoom=max_zoom,
        target_x=target_x,
        target_y=target_y,
        pan_deadzone=pan_deadzone,
        zoom_deadzone=zoom_deadzone,
        pan_seconds=pan_seconds,
        zoom_seconds=zoom_seconds,
        lost_after=lost_after,
    )
    _run(common, effect, prepare=False)


@app.command(cls=SharedOptionsCommand, rich_help_panel="Screen")
def share_screen(
    ctx: typer.Context,
    top: int | None = typer.Option(
        None, help="Capture region's top edge; negative values allowed."
    ),
    left: int | None = typer.Option(
        None, help="Capture region's left edge; negative values allowed."
    ),
    width: int | None = typer.Option(
        None, min=1, help="Region width; defaults to input width."
    ),
    height: int | None = typer.Option(
        None, min=1, help="Region height; defaults to input height."
    ),
    border: bool | None = typer.Option(
        None,
        "--border/--no-border",
        help="Show captured region border; enabled with --select.",
    ),
    select: ScreenSelection | None = typer.Option(
        None, "--select", help="macOS picker: area, full screen, or visible screen."
    ),
) -> None:
    """Share a screen region with the same output and controls as camera commands."""
    from webcam_mods.input.screen import Screen

    common = _common(ctx)
    settings = common.settings or load_settings()
    if common.capture not in ("auto", "opencv"):
        raise typer.BadParameter(
            "--capture-backend selects cameras, not screen capture"
        )
    if select is not None:
        if any(value is not None for value in (top, left, width, height)):
            raise typer.BadParameter(
                "--select cannot be combined with region coordinates"
            )
        try:
            region = select_screen_region(
                select, aspect=(settings.out_width, settings.out_height)
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        top, left, width, height = region.t, region.l, region.w, region.h
    screen = Screen(
        top=top if top is not None else 0,
        left=left if left is not None else 0,
        width=width if width is not None else settings.in_width,
        height=height if height is not None else settings.in_height,
        fps=settings.in_fps,
        device=settings.video_out,
    )
    show_border = select is not None if border is None else border
    if show_border and sys.platform != "darwin":
        raise typer.BadParameter("--border requires macOS")
    indicator = (
        ScreenBorder(Rect(l=screen.left, t=screen.top, w=screen.width, h=screen.height))
        if show_border
        else None
    )
    _run(common, source=screen, border=indicator)


@app.command(cls=SharedOptionsCommand, rich_help_panel="Utilities")
def test_loop(ctx: typer.Context) -> None:
    """Camera pass-through for delivery checks."""
    _run(_common(ctx), prepare=False)


@app.command(cls=SharedOptionsCommand, rich_help_panel="Utilities")
def list_cameras(ctx: typer.Context) -> None:
    """List camera indices/formats for the selected backend without opening capture."""
    if sys.platform != "darwin":
        raise typer.BadParameter("list-cameras requires macOS")
    try:
        from webcam_mods.macos.capture import camera_inventory

        cameras = camera_inventory(_common(ctx).capture)
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


@app.command(cls=SharedOptionsCommand, rich_help_panel="Profiles")
def profiles_list() -> None:
    """List saved profile names and validated settings as JSON."""
    import json
    from webcam_mods.profiles import ProfileStore

    profiles, errors = ProfileStore().list_with_errors()
    typer.echo(json.dumps(profiles, indent=2))
    for error in errors:
        typer.echo(f"Profile {error['name']}: {error['error']}", err=True)


@app.command(cls=SharedOptionsCommand, rich_help_panel="Profiles")
def profile_save(name: str, config: Path) -> None:
    """Save a named profile from a JSON config file."""
    import json
    from webcam_mods.profiles import ProfileStore

    try:
        ProfileStore().save(name, json.loads(config.read_text()))
    except (OSError, ValueError, TypeError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Saved {name}")


@app.command(cls=SharedOptionsCommand, rich_help_panel="Profiles")
def profile_delete(name: str) -> None:
    """Delete one named profile, including a damaged profile."""
    from webcam_mods.profiles import ProfileStore

    try:
        ProfileStore().delete(name)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Deleted {name}")


@app.command(cls=SharedOptionsCommand, rich_help_panel="Profiles")
def profile_export(
    name: str,
    path: Path,
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace an existing export file."
    ),
) -> None:
    """Export validated profile config for backup or editing."""
    from webcam_mods.profiles import ProfileStore

    try:
        ProfileStore().export(name, path, overwrite=overwrite)
    except (OSError, ValueError, TypeError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Exported {name} to {path}")


@app.command(cls=SharedOptionsCommand, rich_help_panel="Profiles")
def profile_run(ctx: typer.Context, name: str) -> None:
    """Run a saved effect profile without interactive crop controls."""
    import threading

    for parameter in ctx.parent.command.params if ctx.parent is not None else []:
        key = parameter.name
        if key is None:
            continue
        for context in (ctx, ctx.parent):
            if context is None:
                continue
            source = context.get_parameter_source(key)
            if source is not None and source.name == "COMMANDLINE":
                raise typer.BadParameter(
                    "profile-run uses saved settings; edit the profile instead of supplying common flags"
                )
    from webcam_mods.control import run_profile
    from webcam_mods.profiles import ProfileStore

    try:
        profile = ProfileStore().get(name)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run_profile(profile, threading.Event(), lambda: None, lambda source: None)


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
        CaptureBackend.auto,
        help="auto prefers native macOS capture; opencv/avfoundation force a backend. Screen uses MSS.",
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
    signal_pattern: SignalPattern | None = typer.Option(
        None,
        help="Loading/paused frames: color-bars or noise; shared by all outputs.",
        rich_help_panel="Output",
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
            signal_pattern=signal_pattern.value if signal_pattern is not None else None,
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
