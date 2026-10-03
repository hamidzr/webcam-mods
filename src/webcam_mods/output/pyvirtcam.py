from typing import Any

import pyvirtualcam
from pyvirtualcam import PixelFormat

from webcam_mods.input.input import FrameOutput
from webcam_mods.utils.video import Frame


class PyVirtualCam(FrameOutput):
    id = "virtual-cam"

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        device: str | None = None,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, device=device)
        self.cam: pyvirtualcam.Camera | None = None

    def setup(self) -> dict[str, Any]:
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

    def teardown(self, *args: Any) -> None:
        cam = self.cam
        if cam is not None:
            self.cam = None
            cam.close()

    def is_setup(self) -> bool:
        return self.cam is not None

    def send(self, frame: Frame) -> None:
        if self.cam is None:
            raise RuntimeError("virtual camera is not open")
        self.cam.send(frame)

    def wait_until_next_frame(self) -> None:
        if self.cam is None:
            raise RuntimeError("virtual camera is not open")
        self.cam.sleep_until_next_frame()

    def is_in_use(self) -> bool:
        return True
