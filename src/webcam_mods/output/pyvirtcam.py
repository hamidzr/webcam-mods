from webcam_mods.utils.file_monitor import MonitorFile
from webcam_mods.input.input import FrameOutput, Frame
from pathlib import Path
from typing import Dict, Any
import pyvirtualcam
from pyvirtualcam import PixelFormat


class PyVirtualCam(FrameOutput):
    id = "vritual-cam"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_demand = MonitorFile(Path(self.device))

    def setup(self) -> Dict[str, Any]:
        self.cam = pyvirtualcam.Camera(
            width=self.width,
            height=self.height,
            fps=self.fps,
            fmt=PixelFormat.BGR,
            print_fps=False,
        )
        self.cam.__enter__()
        self.on_demand.setup()
        return {
            "device": self.cam.device,
            "width": self.cam.width,
            "height": self.cam.height,
            "fps": self.cam.fps,
        }

    def teardown(self, *args):
        self.consumers = 0
        self.on_demand.teardown()
        self.cam.close()

    def send(self, frame: Frame):
        return self.cam.send(frame)

    def wait_until_next_frame(self):
        self.cam.sleep_until_next_frame()

    def is_in_use(self) -> bool:
        return self.on_demand.is_in_use()
