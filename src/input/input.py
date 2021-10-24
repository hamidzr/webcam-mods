from abc import abstractmethod
from typing import Any, Optional, Dict, Generator, TypeVar
import cv2
import numpy as np
import time
import datetime as dt


Frame = Any

class FrameInput:
    def __init__(self,
                 width: Optional[int] = None,
                 height: Optional[int] = None,
                 fps: Optional[int] = None):
        self.width = width
        self.height = height
        self.fps = fps

    @abstractmethod
    def setup(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def teardown(self):
        pass

    @abstractmethod
    def is_setup(self) -> bool:
        pass

    @abstractmethod
    def frame(self) -> Frame:
        pass

    def frames(self) -> Generator[Frame, None, None]:
        while True:
            yield self.frame()

    def demo(self):
        self.setup()
        start_time = dt.datetime.today().timestamp()
        i = 0
        for frame in self.frames():
            cv2.imshow('screen', np.array(frame))
            if (cv2.waitKey(1) & 0xFF) == ord('q'):
                cv2.destroyAllWindows()
                break
            time_diff = dt.datetime.today().timestamp() - start_time
            i += 1
            if i % 100 == 0:
                print('fps:', int(i / time_diff))
