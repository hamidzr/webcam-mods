from typing import Literal, Optional, Union, Type

Number = Union[int, float]

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

    def copy(self) -> 'Point':
        return self.__class__(t=self.t, l=self.l)

    def __add__(self, other: 'Point') -> 'Point':
        new_p = self.copy()
        new_p.top += other.t
        new_p.left += other.l
        return new_p

    def __sub__(self, other: 'Point') -> 'Point':
        new_p = self.copy()
        new_p.top -= other.t
        new_p.left -= other.l
        return new_p

    def __eq__(self, other: 'Point') -> bool:
        return self.t == other.t and self.l == other.l

    def __truediv__(self, num: Number) -> 'Point':
        pt = self.copy()
        pt.left = pt.left // num
        pt.top = pt.top // num
        return pt

    def __mul__(self, num: Number) -> 'Point':
        pt = self.copy()
        pt.left = int(pt.left * num)
        pt.top = int(pt.top * num)
        return pt



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

    def center_on(self, pt: Point):
        """
        center the rectangle on a point
        """
        dl, dt = self.w // 2, self.h // 2
        new_pos = Point(t=pt.top-dt, l=pt.left-dl)
        self.move_to(new_pos)

    @property
    def center(self) -> Point:
        """
        Compute center poitn of the rectangle
        """
        return (self.start_point + self.end_point) / 2
