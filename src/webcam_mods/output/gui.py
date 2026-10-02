"""Bare, paced preview of the final output frame."""

import time
from typing import Any

import cv2

from webcam_mods.input.input import FrameOutput, Frame


class GUI(FrameOutput):
    id = "gui"
    window_name = "Webcam Mods"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._active = False
        self._closed = False
        self._deadline = 0.0

    def setup(self) -> dict[str, Any]:
        self._closed = False
        self._active = True
        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)
        self._deadline = time.monotonic()
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any) -> None:
        if self._active:
            try:
                cv2.destroyWindow(self.window_name)
                cv2.waitKey(1)
            except cv2.error:
                # user may already have destroyed the window
                pass
            finally:
                self._active = False
        self._closed = True

    def is_setup(self) -> bool:
        return self._active

    def send(self, frame: Frame) -> None:
        if not self._closed:
            cv2.imshow(self.window_name, frame)

    def wait_until_next_frame(self) -> None:
        self._deadline = max(self._deadline + 1 / self.fps, time.monotonic())
        while not self._closed:
            key = cv2.waitKey(1) & 0xFF
            try:
                visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE)
            except cv2.error:
                visible = 0
            if key == 27 or visible < 1:
                self._closed = True
                break
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.02))

    def should_stop(self) -> bool:
        return self._closed

    def is_in_use(self) -> bool:
        return not self._closed
