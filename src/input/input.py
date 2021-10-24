from abc import abstractmethod
from typing import Any, Optional, Dict, Generator, Tuple
import cv2
import numpy as np
import time
import datetime as dt


Frame = Any

class InNOut:
    id: str

    def __init__(self,
                 width: int = 100,
                 height: int = 100,
                 fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps

    @abstractmethod
    def setup(self) -> Dict[str, Any]:
        raise NotImplementedError()

    def __enter__(self) -> Tuple['InNOut', Dict[str, Any]]:
        return (self, self.setup())

    @abstractmethod
    def teardown(self, *args, **kwargs):
        raise NotImplementedError()

    def __exit__(self, *args, **kwargs):
        self.teardown(*args, **kwargs)

    @abstractmethod
    def is_setup(self) -> bool:
        raise NotImplementedError()

class FrameInput(InNOut):
    @abstractmethod
    def frame(self) -> Optional[Frame]:
        raise NotImplementedError()

    def frames(self) -> Generator[Frame, None, None]:
        while True:
            yield self.frame()

    def demo(self):
        self.setup()
        start_time = dt.datetime.today().timestamp()
        i = 0
        for frame in self.frames():
            cv2.imshow('screen', frame)
            if (cv2.waitKey(1) & 0xFF) == ord('q'):
                cv2.destroyAllWindows()
                break
            time_diff = dt.datetime.today().timestamp() - start_time
            i += 1
            if i % 100 == 0:
                print('fps:', int(i / time_diff))

    def __enter__(self) -> Tuple['FrameInput', Dict[str, Any]]:
        return super().__enter__() # type: ignore

class FrameOutput(InNOut):
    @abstractmethod
    def send(self, frame: Frame):
        raise NotImplementedError()

    @abstractmethod
    def wait_until_next_frame(self):
        raise NotImplementedError()

    def __enter__(self) -> Tuple['FrameOutput', Dict[str, Any]]:
        return super().__enter__() # type: ignore
