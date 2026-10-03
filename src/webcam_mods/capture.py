"""Resolve capture backends without changing an explicitly selected camera."""

import importlib.util
import sys
from typing import Literal

from loguru import logger

from webcam_mods.input.input import FrameInput
from webcam_mods.settings import StartupSettings

CaptureBackend = Literal["auto", "opencv", "avfoundation"]
ResolvedBackend = Literal["opencv", "avfoundation"]
NATIVE_MODULES = (
    "AVFoundation",
    "CoreMedia",
    "Quartz",
    "libdispatch",
    "objc",
    "Foundation",
)


def resolve_backend(backend: CaptureBackend = "auto") -> ResolvedBackend:
    """Prefer native macOS capture in auto mode; explicit choices never fall back."""
    if backend not in ("auto", "opencv", "avfoundation"):
        raise ValueError(f"unknown capture backend: {backend}")
    if backend == "opencv":
        return "opencv"
    if sys.platform != "darwin":
        if backend == "avfoundation":
            raise ValueError("AVFoundation capture requires macOS")
        return "opencv"
    if any(importlib.util.find_spec(name) is None for name in NATIVE_MODULES):
        if backend == "avfoundation":
            raise ValueError("AVFoundation capture requires uv sync --extra macos")
        logger.warning(
            "Native camera bindings unavailable; auto capture uses OpenCV. "
            "Install with uv sync --extra macos for stable native capture."
        )
        return "opencv"
    return "avfoundation"


def opencv_device_id(index: int) -> str:
    """Map OpenCV's sorted video/muxed index to a native video camera identity."""
    import AVFoundation as av

    from webcam_mods.macos.capture import is_obs_output_device

    videos = list(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo))
    muxed = list(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeMuxed))
    devices = sorted([*videos, *muxed], key=lambda device: str(device.uniqueID()))
    if type(index) is not int or not 0 <= index < len(devices):
        raise ValueError(
            f"OpenCV camera index {index} unavailable; use list-cameras to inspect inputs"
        )
    selected = devices[index]
    if is_obs_output_device(selected):
        raise ValueError(
            f"camera index {index} is OBS output; choose an input with list-cameras"
        )
    identity = str(selected.uniqueID())
    if not any(str(device.uniqueID()) == identity for device in videos):
        raise ValueError(
            f"camera index {index} is not a native video input; "
            "use --capture-backend opencv or choose another input"
        )
    return identity


def create_camera(
    settings: StartupSettings, backend: CaptureBackend = "auto"
) -> FrameInput:
    """Construct one selected backend; acquisition failures propagate unchanged."""
    resolved = resolve_backend(backend)
    logger.info(
        "capture {} -> {}, camera #{}, requested {}x{} at {:g} FPS",
        backend,
        resolved,
        settings.video_in,
        settings.in_width,
        settings.in_height,
        settings.in_fps,
    )
    if resolved == "opencv":
        from webcam_mods.input.video_dev import Webcam

        return Webcam(settings=settings)
    from webcam_mods.macos.capture import AVFoundationCamera

    if backend == "auto":
        return AVFoundationCamera(
            device_index=settings.video_in,
            device_id=opencv_device_id(settings.video_in),
            width=settings.in_width,
            height=settings.in_height,
            fps=settings.in_fps,
            device=settings.video_out,
        )
    return AVFoundationCamera(
        device_index=settings.video_in,
        width=settings.in_width,
        height=settings.in_height,
        fps=settings.in_fps,
        device=settings.video_out,
    )
