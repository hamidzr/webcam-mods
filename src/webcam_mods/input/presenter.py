"""Screen capture with a camera read alongside it, for the presenter overlay."""

import threading
from typing import Any

from webcam_mods.frame_producer import WorkerShutdownTimeout
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.utils.video import Frame

_STOP_SECONDS = 10.0


class CameraFeed:
    """Newest frame of a camera read on its own thread.

    The thread owns the camera from setup to teardown, so a camera that blocks
    between frames never slows the screen.
    """

    def __init__(self, camera: FrameInput) -> None:
        self.camera = camera
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._error: BaseException | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Open the camera; setup failures raise here."""
        if self._thread is not None:
            return
        self._stop = threading.Event()
        with self._lock:
            self._frame, self._error = None, None
        ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(ready, self._stop),
            name="webcam-presenter-camera",
            daemon=True,
        )
        self._thread.start()
        ready.wait()
        with self._lock:
            error = self._error
        if error is not None:
            self.stop()
            raise error

    def _run(self, ready: threading.Event, stop: threading.Event) -> None:
        try:
            self.camera.setup()
            ready.set()
            while not stop.is_set():
                frame = self.camera.frame()
                if frame is not None:
                    with self._lock:
                        self._frame = frame
        except BaseException as error:
            # reads interrupted by stop are not failures
            if not stop.is_set() or not ready.is_set():
                with self._lock:
                    self._error = error
        finally:
            try:
                self.camera.teardown()
            except Exception as error:
                with self._lock:
                    self._error = self._error or error
            ready.set()

    def latest(self) -> Frame | None:
        """Newest camera frame, None before the first; a failed camera raises."""
        with self._lock:
            if self._error is not None:
                raise RuntimeError(
                    f"presenter camera failed: {self._error}"
                ) from self._error
            return self._frame

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stop.set()
        self.camera.request_stop()
        thread.join(_STOP_SECONDS)
        if thread.is_alive():
            raise WorkerShutdownTimeout("presenter camera is still stopping")


class PresenterInput(FrameInput):
    """Screen frames while the presenter camera runs; both open and close together,
    so pausing turns the camera off."""

    def __init__(self, screen: FrameInput, feed: CameraFeed) -> None:
        super().__init__(
            width=screen.width, height=screen.height, fps=screen.fps, device="screen"
        )
        self.screen, self.feed = screen, feed

    def setup(self) -> AdapterMetadata:
        metadata = self.screen.setup()
        try:
            self.feed.start()
        except BaseException:
            self.screen.teardown()
            raise
        return metadata

    def frame(self) -> Frame | None:
        return self.screen.frame()

    def request_stop(self) -> None:
        self.screen.request_stop()
        self.feed.camera.request_stop()

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        try:
            self.feed.stop()
        finally:
            self.screen.teardown(*args, **kwargs)

    def is_setup(self) -> bool:
        return self.screen.is_setup()
