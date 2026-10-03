"""Choose a named camera before acquisition when an interactive terminal is present."""

from dataclasses import replace
import os
import sys

import typer
from typer._click import Context

CAMERA_COMMANDS = {
    "crop-cam",
    "brighten",
    "track-face",
    "bg-color",
    "bg-swap",
    "bg-blur",
    "test-loop",
}


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def prepare_camera_selection(ctx: Context, *, explicit: bool) -> None:
    if (
        ctx.info_name not in CAMERA_COMMANDS
        or explicit
        or "VIDEO_IN" in os.environ
        or not _interactive_terminal()
        or sys.platform != "darwin"
    ):
        return

    from webcam_mods.entry import Common
    from webcam_mods.macos.capture import camera_inventory

    common = ctx.obj
    if not isinstance(common, Common) or common.settings is None:
        raise RuntimeError("camera selection requires resolved startup settings")
    try:
        cameras = camera_inventory(common.capture)
    except ImportError:
        typer.echo(
            "Camera picker unavailable; install macOS extras with "
            "uv sync --extra macos. Using configured camera index.",
            err=True,
        )
        return
    choices = {
        camera.input_index: camera.name
        for camera in cameras
        if camera.input_index is not None and camera.excluded_reason is None
    }
    if not choices:
        raise typer.BadParameter(
            "no input cameras available after excluding OBS output"
        )

    default = common.settings.video_in
    if default not in choices:
        default = next(iter(choices))
    selected = default
    if len(choices) > 1:
        typer.echo(f"Input cameras ({common.capture}):")
        for index, name in choices.items():
            typer.echo(f"  {index}: {name}")
        while True:
            selected = typer.prompt("Camera index", default=default, type=int)
            if selected in choices:
                break
            typer.echo("Choose one of the listed camera indices.", err=True)
    typer.echo(f"Using {choices[selected]} (--input-device {selected}).")
    common.settings = replace(common.settings, video_in=selected)
