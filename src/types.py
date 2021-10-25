from typing import Optional

class Point:
    def __init__(self, t: int = 0, l: int = 0):
        self.top = t
        self.left = l

    @property
    def t(self):
        return self.top

    @property
    def l(self):
        return self.left

    @property
    def tuple(self):
        return (self.l, self.t)

    def __repr__(self) -> str:
        return f'(l:{self.l}, t:{self.t})'

class Rect:
    def __init__(self, w: int = 100, h: int = 100,
                 t: int = 0, l: int = 0):
        self.width = w
        self.height = h
        self.top = t
        self.left = l

    @classmethod
    def from_rect(cls, rect: 'Rect') -> 'Rect':
        return cls(w=rect.w, h=rect.h, t=rect.t, l=rect.l)

    def move_to(self, top_left: Point):
        self.left = top_left.left
        self.top = top_left.top

    @property
    def h(self):
        return self.height

    @property
    def w(self):
        return self.width

    @property
    def t(self):
        return self.top

    @property
    def l(self):
        return self.left

    @property
    def start_point(self) -> Point:
        return Point(t=self.t, l=self.l)

    @property
    def end_point(self) -> Point:
        # bottom right
        return Point(t=self.t+self.h, l=self.l+self.w)

    def __repr__(self) -> str:
      return f'{self.start_point} => {self.end_point}'

    def __dict__(self):
        return {'top': self.top, 'left': self.left,
                'width': self.width, 'height': self.height}

# TODO replace with Rect
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

