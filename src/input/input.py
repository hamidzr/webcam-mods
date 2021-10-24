from typing import Any, Optional
import cv2
import numpy as np
import time
import datetime as dt

class FrameInput:
    def __init__(self,
                 width: Optional[int] = None,
                 height: Optional[int] = None,
                 fps: Optional[int] = None):
        pass

    def setup(self):
        pass

    def teardown(self):
        pass

    def frames(self) -> Any:
        # while True:
        #     yield 0
        pass

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
