from mss import mss
from mss.base import MSSBase
# from PIL import Image
from src.input.input import FrameInput
from src.types import BoundingBox

bounding_box: BoundingBox = BoundingBox(**{'top': 100, 'left': 0, 'width': 400, 'height': 300})

class Screen(FrameInput):
    sct: MSSBase
    def setup(self):
        self.sct = mss()

    def frames(self):
        bb = bounding_box.__dict__()
        while True:
            yield self.sct.grab(bb)

if __name__ == '__main__':
    s = Screen()
    s.demo()
