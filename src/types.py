from typing import Optional

class BoundingBox:
    def __init__(self, top: int = 0, left: int = 0,
                 width: int = 0, height: int = 0):
        self.top = top
        self.left = left
        self.height = height
        self.width = width

    def __dict__(self):
        return {'top': self.top, 'left': self.left,
                'width': self.width, 'height': self.height}
