import fcntl
from pathlib import Path
from webcam_mods.utils.file_monitor import MonitorFile
import os
from webcam_mods.input.input import FrameOutput
from webcam_mods.utils.video import Frame
from typing import Dict, Any
import cv2
import v4l2


def prep_v4l2_descriptor(width, height, channels):
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

    def __init__(self, *args, **kwargs):
        super(V4l2Cam, self).__init__(*args, **kwargs)
        self.on_demand = MonitorFile(Path(self.device))

    def setup(self) -> Dict[str, Any]:
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

    def teardown(self, *args):
        self.consumers = 0
        self.on_demand.teardown()
        self.dev.close()

    def send(self, frame: Frame):
        self.dev.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420))

    def wait_until_next_frame(self):
        pass

    def is_in_use(self) -> bool:
        return self.on_demand.is_in_use()
