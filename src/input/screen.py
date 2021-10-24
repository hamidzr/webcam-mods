from mss import mss
import numpy as np
from mss.base import MSSBase
from typing import Optional, cast
# from PIL import Image
from src.input.input import FrameInput
from src.types import BoundingBox

class Screen(FrameInput):
    sct: Optional[MSSBase]
    def __init__(self, top: int = 0, left: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.top = top
        self.left = left
        self.bounding_box = BoundingBox(top=top, left=left,
                                        width=self.width, height=self.height)

    def setup(self):
        self.sct = mss()
        return {'fps': 15}

    def frame(self):
        frame = self.sct.grab(self.bounding_box.__dict__())
        return np.array(frame)[:,:,:3] # drop the alpha channel from BGRA

    def teardown(self):
        if not self.is_setup():
            return
        cast(MSSBase, self.sct).close()
        self.sct = None

    def is_setup(self):
        return self.sct == None

if __name__ == '__main__':
    s = Screen()
    s.demo()
