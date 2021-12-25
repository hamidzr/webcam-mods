from src.input.input import FrameOutput, Frame
from inotify_simple import INotify, flags
from typing import Dict, Any
import pyvirtualcam
from pyvirtualcam import PixelFormat

class PyVirtualCam(FrameOutput):
    id = 'vritual-cam'

    def _setup_inotify(self):
        self.consumers = 0
        inotify = INotify(nonblocking=True)
        self.inotify = inotify
        watch_flags = flags.CREATE | flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE
        inotify.add_watch(self.cam.device, watch_flags)

    def _check_inotify(self):
        for event in self.inotify.read(0):
            for flag in flags.from_mask(event.mask):
                if flag == flags.CLOSE_NOWRITE or flag == flags.CLOSE_WRITE:
                    self.consumers = max(0, self.consumers - 1)
                if flag == flags.OPEN:
                    self.consumers += 1
                print("Consumers:", self.consumers)

    def setup(self) -> Dict[str, Any]:
        self.cam = pyvirtualcam.Camera(width=self.width, height=self.height,
                                       fps=self.fps, fmt=PixelFormat.BGR, print_fps=False)
        self.cam.__enter__()
        self._setup_inotify()
        return {'device': self.cam.device, 'width': self.cam.width,
                'height': self.cam.height, 'fps': self.cam.fps}

    def teardown(self, *args):
        self.consumers = 0
        self.inotify.close()
        self.cam.close()

    def send(self, frame: Frame):
        return self.cam.send(frame)

    def wait_until_next_frame(self):
        self.cam.sleep_until_next_frame()

    def is_in_use(self) -> bool:
        self._check_inotify()
        return self.consumers > 0
