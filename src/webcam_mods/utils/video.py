from time import sleep
from typing import Any

Frame = Any

def sleep_until_fps(fps: int):
    # TODO consider time from last call
    sleep(1/fps)
