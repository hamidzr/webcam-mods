from time import sleep
import numpy as np
from numpy.typing import NDArray

# OpenCV BGR pixels; shape remains a runtime adapter contract
Frame = NDArray[np.uint8]


def sleep_until_fps(fps: int) -> None:
    # TODO consider time from last call
    sleep(1 / fps)
