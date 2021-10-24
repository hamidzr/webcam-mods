import cv2
import datetime as dt
from typing import Dict, Any
from src.input.input import FrameOutput, Frame

class GUI(FrameOutput):
    id = 'gui'
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def setup(self) -> Dict[str, Any]:
        self.start_time = dt.datetime.today().timestamp()
        self.i = 0
        return {'width': self.width, 'height': self.height}

    def teardown(self, *args):
        self.start_time = dt.datetime.today().timestamp()
        self.i = 0

    def send(self, frame: Frame):
        cv2.imshow('screen', frame)
        time_diff = dt.datetime.today().timestamp() - self.start_time
        self.i += 1
        if self.i % 100 == 0:
            print('fps:', int(self.i / time_diff))
