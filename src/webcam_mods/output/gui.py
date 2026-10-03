"""Bare, paced preview of the final output frame."""

from typing import Any

import cv2

from webcam_mods.input.input import FrameOutput
from webcam_mods.timing import FramePacer
from webcam_mods.utils.video import Frame


class GUI(FrameOutput):
    id = "gui"
    window_name = "Webcam Mods"

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        device: str | None = None,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, device=device)
        self._active = False
        self._closed = False
        self._pacer: FramePacer | None = None

    def setup(self) -> dict[str, Any]:
        self._closed = False
        self._active = True
        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)
        self._pacer = FramePacer(self.fps)
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

    def process_events(self) -> None:
        if self._closed:
            return
        key = cv2.waitKey(1) & 0xFF
        try:
            visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE)
        except cv2.error:
            visible = 0
        if key == 27 or visible < 1:
            self._closed = True

    def wait_until_next_frame(self) -> None:
        """Compatibility pacing for callers outside live_loop."""
        if self._pacer is not None:
            self._pacer.wait(process_events=self._process_and_continue)

    def _process_and_continue(self) -> bool:
        self.process_events()
        return not self.should_stop()

    def should_stop(self) -> bool:
        return self._closed

    def is_in_use(self) -> bool:
        return not self._closed
