from enum import Enum
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from mss import mss
from mss.base import MSSBase
import numpy as np

from webcam_mods.geometry import Rect
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.utils.video import Frame


class ScreenSelection(str, Enum):
    area = "area"
    screen = "screen"
    visible = "visible"


def sharing_helper() -> str:
    executable = shutil.which("select-region")
    if executable is None:
        raise ValueError(
            "install select-region from ~/scripts/compat with just install"
        )
    try:
        capabilities = subprocess.run(
            [executable, "--capabilities"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(
            "update select-region from ~/scripts/compat with just install"
        ) from error
    if (
        capabilities.returncode != 0
        or "border-points" not in capabilities.stdout.split()
    ):
        raise ValueError("update select-region from ~/scripts/compat with just install")
    return executable


def select_screen_region(
    mode: ScreenSelection, aspect: tuple[int, int] | None = None
) -> Rect:
    """Select global screen points matching MSS's nominal-resolution capture."""
    if sys.platform != "darwin":
        raise ValueError("--select requires macOS; use explicit region coordinates")
    executable = sharing_helper()
    flags = {
        ScreenSelection.area: [],
        ScreenSelection.screen: ["--screen"],
        ScreenSelection.visible: ["--visible"],
    }[mode]
    if mode == ScreenSelection.area:
        flags += ["--show-hints", "--prompt", "Select screen area to share"]
        if aspect is not None:
            flags += ["--aspect-ratio", f"{aspect[0]}:{aspect[1]}"]
    try:
        result = subprocess.run(
            [executable, *flags, "-f", "%X %Y %W %H"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ValueError("could not launch select-region") from error
    if result.returncode != 0:
        raise ValueError(
            "screen selection cancelled or failed; capture was not started"
        )
    try:
        left, top, width, height = map(int, result.stdout.split())
    except ValueError as error:
        raise ValueError("select-region returned invalid geometry") from error
    if width <= 0 or height <= 0:
        raise ValueError("select-region returned non-positive region dimensions")
    return Rect(t=top, l=left, w=width, h=height)


class ScreenBorder:
    """Own a click-through border; geometry always uses global screen points."""

    def __init__(self, region: Rect) -> None:
        self.region = region
        self.process: subprocess.Popen[bytes] | None = None
        self.directory: tempfile.TemporaryDirectory[str] | None = None

    def start(self) -> None:
        executable = sharing_helper()
        self.directory = tempfile.TemporaryDirectory(prefix="webcam-mods-border-")
        self.update(self.region)
        r = self.region
        try:
            self.process = subprocess.Popen(
                [
                    executable,
                    "--border-points",
                    str(r.l),
                    str(r.t),
                    str(r.w),
                    str(r.h),
                    "--geometry-file",
                    str(self.path),
                    "--parent-pid",
                    str(os.getpid()),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.close()
            raise

    @property
    def path(self) -> Path:
        if self.directory is None:
            raise RuntimeError("border is not started")
        return Path(self.directory.name) / "geometry.txt"

    def update(self, region: Rect) -> None:
        if self.directory is None:
            return
        if self.path.exists() and self.region.__dict__() == region.__dict__():
            return
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(f"{region.l} {region.t} {region.w} {region.h}\n")
        temporary.replace(self.path)
        self.region = region

    def close(self) -> None:
        process, self.process = self.process, None
        try:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            if self.directory is not None:
                self.directory.cleanup()
                self.directory = None


class Screen(FrameInput):
    def __init__(
        self,
        top: int = 0,
        left: int = 0,
        width: int | None = None,
        height: int | None = None,
        *,
        fps: float | None = None,
        device: str | None = None,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, device=device)
        self.top = top
        self.left = left
        self.bounding_box = Rect(t=top, l=left, w=self.width, h=self.height)
        self.sct: MSSBase | None = None

    def setup(self) -> AdapterMetadata:
        for name in ("width", "height"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"screen {name} must be a positive integer")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("screen fps must be positive and finite")
        if self.sct is None:
            self.sct = mss()
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def frame(self) -> Frame | None:
        if self.sct is None:
            return None
        frame = self.sct.grab(dict(self.bounding_box.__dict__()))
        # mss pixels are BGRA; removing alpha requires a contiguous copy
        return np.ascontiguousarray(np.asarray(frame)[:, :, :3], dtype=np.uint8)

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        sct = self.sct
        if sct is not None:
            self.sct = None
            sct.close()

    def is_setup(self) -> bool:
        return self.sct is not None


if __name__ == "__main__":
    Screen().demo()
