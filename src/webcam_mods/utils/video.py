from time import sleep
import numpy as np
from numpy.typing import NDArray

# OpenCV BGR pixels; shape remains a runtime adapter contract
Frame = NDArray[np.uint8]


def validate_frame(frame: Frame) -> None:
    """Reject malformed BGR arrays before native processing or allocation."""
    if (
        not isinstance(frame, np.ndarray)
        or frame.dtype != np.uint8
        or frame.ndim != 3
        or frame.shape[2] != 3
        or not all(frame.shape[:2])
    ):
        raise ValueError("expected a nonempty HxWx3 uint8 BGR frame")


def sleep_until_fps(fps: int) -> None:
    # TODO consider time from last call
    sleep(1 / fps)
