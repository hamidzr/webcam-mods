import math
from typing import Any

from mss import mss
from mss.base import MSSBase
import numpy as np

from webcam_mods.geometry import Rect
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.utils.video import Frame


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
