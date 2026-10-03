#!/usr/bin/env python3
"""Check camera format retention across a startup pause and repeated sessions.

No preview, output camera, models, or saved camera images are involved.
"""

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

from webcam_mods.capture import CaptureBackend, create_camera
from webcam_mods.input.input import FrameInput
from webcam_mods.settings import StartupSettings


def require_authorization(source: FrameInput) -> None:
    """Avoid requesting privacy permission from a headless check process."""
    if sys.platform != "darwin":
        return
    from webcam_mods.input.video_dev import Webcam
    from webcam_mods.macos.capture import AVFoundationCamera

    if isinstance(source, (AVFoundationCamera, Webcam)):
        try:
            import AVFoundation as av
        except ImportError as error:
            raise PermissionError(
                "camera permission preflight requires uv sync --extra macos"
            ) from error

        status = av.AVCaptureDevice.authorizationStatusForMediaType_(
            av.AVMediaTypeVideo
        )
        if status != av.AVAuthorizationStatusAuthorized:
            raise PermissionError(
                "camera check requires existing Camera permission; "
                "run from a camera-authorized Terminal"
            )


def check_capture(
    settings: StartupSettings,
    backend: CaptureBackend = "auto",
    *,
    frames: int = 120,
    cycles: int = 3,
    startup_pause: float = 5,
) -> dict[str, Any]:
    """Retain partial progress and close every attempted capture on failure."""
    if frames < 2 or cycles < 1:
        raise ValueError("frames must be at least two and cycles must be positive")
    if not math.isfinite(startup_pause) or startup_pause < 0:
        raise ValueError("startup pause must be finite and nonnegative")
    report: dict[str, Any] = {
        "status": "running",
        "requested": {
            "backend": backend,
            "input_device": settings.video_in,
            "width": settings.in_width,
            "height": settings.in_height,
            "fps": settings.in_fps,
            "frames_per_cycle": frames,
            "cycles": cycles,
            "startup_pause_seconds": startup_pause,
        },
        "runs": [],
        "scope": "capture format retention and post-pause arrival cadence; no effects/output",
    }
    try:
        for cycle in range(cycles):
            run: dict[str, Any] = {"cycle": cycle + 1, "frames": 0}
            report["runs"].append(run)
            started = time.monotonic()
            source = create_camera(settings, backend)
            try:
                run["adapter"] = type(source).__name__
                require_authorization(source)
                run["negotiated"] = source.setup()
                received: list[float] = []
                for index in range(frames):
                    frame = source.frame()
                    if frame is None:
                        raise RuntimeError("camera returned no frame")
                    actual = (frame.shape[1], frame.shape[0])
                    if actual != (settings.in_width, settings.in_height):
                        raise RuntimeError(
                            f"capture changed resolution: requested "
                            f"{settings.in_width}x{settings.in_height}, "
                            f"received {actual[0]}x{actual[1]}"
                        )
                    run["frames"] += 1
                    if index == 0:
                        # reproduce the pause while delegate calibration runs
                        time.sleep(startup_pause)
                    else:
                        received.append(time.monotonic())
                duration = received[-1] - received[0]
                run["post_pause_fps"] = (
                    (len(received) - 1) / duration if duration > 0 else None
                )
            finally:
                source.teardown()
                run["closed"] = not source.is_setup()
                run["elapsed_seconds"] = time.monotonic() - started
                if not run["closed"]:
                    raise RuntimeError("capture remained open after teardown")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "blocked" if isinstance(error, PermissionError) else "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-backend", choices=("auto", "opencv", "avfoundation"), default="auto"
    )
    parser.add_argument("--input-device", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--startup-pause", type=float, default=5)
    parser.add_argument("--report", type=Path, default=Path("dist/capture-check.json"))
    args = parser.parse_args(argv)
    try:
        settings = StartupSettings(
            video_in=args.input_device,
            in_width=args.width,
            in_height=args.height,
            in_fps=args.fps,
        )
        result = check_capture(
            settings,
            args.capture_backend,
            frames=args.frames,
            cycles=args.cycles,
            startup_pause=args.startup_pause,
        )
    except ValueError as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
