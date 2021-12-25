from ctypes import ArgumentError
import fcntl
from inotify_simple import INotify, flags
import os
from src.input.input import FrameOutput
from src.utils.video import Frame
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
    id = 'v4l2-cam'

    def _setup_inotify(self):
        self.consumers = 0
        inotify = INotify(nonblocking=True)
        self.inotify = inotify
        watch_flags = flags.CREATE | flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE
        inotify.add_watch(self.device, watch_flags)

    def _check_inotify(self):
        for event in self.inotify.read(0):
            for flag in flags.from_mask(event.mask):
                if flag == flags.CLOSE_NOWRITE or flag == flags.CLOSE_WRITE:
                    self.consumers = max(0, self.consumers - 1)
                if flag == flags.OPEN:
                    self.consumers += 1
                print("Consumers:", self.consumers)

    def setup(self) -> Dict[str, Any]:
        if not os.path.exists(self.device):
            raise ArgumentError("warning: device does not exist", self.device)
        self.dev = open(self.device, 'wb')
        req, format = prep_v4l2_descriptor(self.width, self.height, 3)
        fcntl.ioctl(self.dev, req, format)
        self._setup_inotify()
        return {'device': self.device, 'width': self.width,
                'height': self.height, 'fps': self.fps}

    def teardown(self, *args):
        self.consumers = 0
        self.inotify.close()
        self.dev.close()

    def send(self, frame: Frame):
        self.dev.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420))

    def wait_until_next_frame(self):
        pass

    def is_in_use(self) -> bool:
        self._check_inotify()
        return self.consumers > 0
