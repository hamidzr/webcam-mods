from enum import Enum
import math
import shutil
import subprocess
import sys
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


def select_screen_region(mode: ScreenSelection) -> Rect:
    """Select global screen points matching MSS's nominal-resolution capture."""
    if sys.platform != "darwin":
        raise ValueError("--select requires macOS; use explicit region coordinates")
    executable = shutil.which("select-region")
    if executable is None:
        raise ValueError(
            "--select requires select-region on PATH; "
            "install from ~/scripts/compat with just install or use explicit coordinates"
        )
    flags = {
        ScreenSelection.area: [],
        ScreenSelection.screen: ["--screen"],
        ScreenSelection.visible: ["--visible"],
    }[mode]
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
