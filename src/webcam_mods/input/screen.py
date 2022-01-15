from mss import mss
import numpy as np
from mss.base import MSSBase
from typing import cast

# from PIL import Image
from webcam_mods.input.input import FrameInput
from webcam_mods.geometry import Rect


class Screen(FrameInput):
    sct: MSSBase

    def __init__(self, top: int = 0, left: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.top = top
        self.left = left
        self.bounding_box = Rect(t=top, l=left, w=self.width, h=self.height)
        self._is_setup = False  # is there a better way?

    def setup(self):
        self.sct = mss()
        self._is_setup = True
        return {"fps": 15}

    def frame(self):
        frame = self.sct.grab(self.bounding_box.__dict__())
        return np.array(frame)[:, :, :3]  # drop the alpha channel from BGRA

    def teardown(self):
        if not self.is_setup():
            return
        self._is_setup = False
        cast(MSSBase, self.sct).close()

    def is_setup(self):
        return self._is_setup


if __name__ == "__main__":
    s = Screen()
    s.demo()
