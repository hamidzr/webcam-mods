from webcam_mods.input.input import FrameOutput, Frame
from typing import Dict, Any
import pyvirtualcam
from pyvirtualcam import PixelFormat


class PyVirtualCam(FrameOutput):
    id = "virtual-cam"

    def setup(self) -> Dict[str, Any]:
        self.cam = pyvirtualcam.Camera(
            width=self.width,
            height=self.height,
            fps=self.fps,
            fmt=PixelFormat.BGR,
            print_fps=False,
        )
        self.cam.__enter__()
        return {
            "device": self.cam.device,
            "width": self.cam.width,
            "height": self.cam.height,
            "fps": self.cam.fps,
        }

    def teardown(self, *args):
        self.cam.close()

    def send(self, frame: Frame):
        return self.cam.send(frame)

    def wait_until_next_frame(self):
        self.cam.sleep_until_next_frame()

    def is_in_use(self) -> bool:
        return True
