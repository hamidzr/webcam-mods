import fcntl
from pathlib import Path
from webcam_mods.utils.file_monitor import MonitorFile
import os
from webcam_mods.input.input import FrameOutput
from webcam_mods.utils.video import Frame
from typing import Any, BinaryIO
import cv2
import v4l2


def prep_v4l2_descriptor(width: int, height: int, channels: int) -> tuple[int, Any]:
    # Set up the formatting of our loopback device
    format = v4l2.v4l2_format()
    format.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT
    format.fmt.pix.field = v4l2.V4L2_FIELD_NONE
    format.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_YUV420
    format.fmt.pix.width = width
    format.fmt.pix.height = height
    format.fmt.pix.bytesperline = width * channels
    format.fmt.pix.sizeimage = width * height * channels
    return (v4l2.VIDIOC_S_FMT, format)


class V4l2Cam(FrameOutput):
    id = "v4l2-cam"

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        device: str | None = None,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, device=device)
        self.dev: BinaryIO | None = None
        self.on_demand = MonitorFile(Path(self.device))

    def setup(self) -> dict[str, Any]:
        if not os.path.exists(self.device):
            raise FileNotFoundError(
                "error: v4l2loopback device does not exist at", self.device
            )
        self.dev = open(self.device, "wb")
        req, format = prep_v4l2_descriptor(self.width, self.height, 3)
        fcntl.ioctl(self.dev, req, format)
        self.on_demand.setup()
        return {
            "device": self.device,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
        }

    def teardown(self, *args: Any) -> None:
        self.consumers = 0
        try:
            if getattr(self.on_demand, "inotify", None) is not None:
                self.on_demand.teardown()
                self.on_demand.inotify = None
        finally:
            dev = self.dev
            if dev is not None:
                self.dev = None
                dev.close()

    def is_setup(self) -> bool:
        return self.dev is not None

    def send(self, frame: Frame) -> None:
        if self.dev is None:
            raise RuntimeError("V4L2 camera is not open")
        self.dev.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420))

    def wait_until_next_frame(self) -> None:
        pass

    def is_in_use(self) -> bool:
        return self.on_demand.is_in_use()
