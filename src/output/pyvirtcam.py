from src.input.input import FrameOutput, Frame
from typing import Dict, Any
import pyvirtualcam
# from .config import IN_HEIGHT, IN_WIDTH, MAX_OUT_FPS, no_signal_img, OUT_HEIGHT, OUT_WIDTH, VIDEO_OUT
from pyvirtualcam import PixelFormat

    # with pyvirtualcam.Camera(width=out_width, height=out_height, fps=out_fps, fmt=PixelFormat.BGR, print_fps=True) as cam:

class VirtualCam(FrameOutput):
    id = 'vritual-cam'
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cam = pyvirtualcam.Camera(width=self.width, height=self.height,
                                       fps=self.fps, fmt=PixelFormat.BGR, print_fps=True)

    def setup(self) -> Dict[str, Any]:
        self.cam.__enter__()
        return {'device': self.cam.device, 'width': self.cam.width,
                'height': self.cam.height, 'fps': self.cam.fps}

    def teardown(self, *args):
        return self.cam.__exit__(*args)

    def send(self, frame: Frame):
        return self.cam.send(frame)

    def wait_until_next_frame(self):
        self.cam.sleep_until_next_frame()
