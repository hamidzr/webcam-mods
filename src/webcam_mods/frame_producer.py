"""One capture/effect worker publishing an owned latest frame, without a queue."""

from collections.abc import Callable
from threading import Condition, Event, Thread
import math

from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.timing import FramePacer
from webcam_mods.utils.video import Frame


class WorkerShutdownTimeout(TimeoutError):
    """Worker still owns processing resources after a bounded shutdown wait."""


class FrameProducer:
    def __init__(
        self,
        source: FrameInput,
        *,
        cleanup: Callable[[], None] | None = None,
        shutdown_timeout: float = 10.0,
    ) -> None:
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise ValueError("shutdown timeout must be finite and positive")
        self.source = source
        self._cleanup = cleanup
        self._shutdown_timeout = shutdown_timeout
        self._condition = Condition()
        self._ready = Event()
        self._stop = Event()
        self._enabled = False
        self._activation_requested = False
        self._close_requested = False
        self._process: Callable[[Frame], Frame] | None = None
        self._before_frame: Callable[[], object] | None = None
        self._fps = 30.0
        self._strict = False
        self._copy_result = True
        self._frame: Frame | None = None
        self._error: BaseException | None = None
        self._metadata: AdapterMetadata | None = None
        self._thread = Thread(
            target=self._run, name="webcam-frame-producer", daemon=True
        )

    def setup(self) -> AdapterMetadata:
        self._thread.start()
        self._ready.wait()
        self.latest()
        if self._metadata is None:
            raise RuntimeError("capture worker did not report metadata")
        return self._metadata

    def configure(
        self,
        process: Callable[[Frame], Frame],
        fps: float,
        *,
        before_frame: Callable[[], object] | None = None,
        strict: bool = False,
        copy_result: bool = True,
    ) -> None:
        """Configure processing; copy_result=False requires an owned, stable result."""
        with self._condition:
            self._process = process
            self._fps = fps
            self._before_frame = before_frame
            self._strict = strict
            self._copy_result = copy_result

    def enable(self, enabled: bool) -> None:
        with self._condition:
            self._activation_requested = True
            self._enabled = enabled
            if not enabled:
                self._frame = None
            self._condition.notify_all()

    def latest(self) -> Frame | None:
        with self._condition:
            if self._error is not None:
                raise self._error
            return self._frame

    def close(self) -> None:
        with self._condition:
            if self._close_requested:
                return
            self._close_requested = True
            self._stop.set()
            self._condition.notify_all()
        self.source.request_stop()
        if self._thread.ident is not None:
            self._thread.join(self._shutdown_timeout)
            if self._thread.is_alive():
                raise WorkerShutdownTimeout(
                    "capture/effect worker is still stopping; "
                    "processing cleanup deferred until it exits"
                )

    def _sleep(self, seconds: float) -> None:
        self._stop.wait(seconds)

    def _continue(self) -> bool:
        with self._condition:
            return not self._stop.is_set() and self._enabled

    def _run(self) -> None:
        try:
            self._metadata = self.source.setup()
            self._ready.set()
            # initial configuration is not an on-demand pause
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stop.is_set() or self._activation_requested
                )
            pacer: FramePacer | None = None
            while not self._stop.is_set():
                with self._condition:
                    paused = not self._enabled
                if paused:
                    if self.source.is_setup():
                        self.source.teardown()
                    pacer = None
                with self._condition:
                    if not self._enabled:
                        self._condition.wait_for(
                            lambda: self._stop.is_set() or self._enabled
                        )
                    if self._stop.is_set():
                        break
                    process = self._process
                if process is None:
                    raise RuntimeError("capture worker was not configured")
                if not self.source.is_setup():
                    self.source.setup()
                if self._stop.is_set():
                    break
                if pacer is None:
                    pacer = FramePacer(self._fps, sleep=self._sleep)
                if self._before_frame is not None:
                    self._before_frame()
                frame = self.source.frame()
                if self._stop.is_set():
                    break
                if frame is None:
                    if self._strict:
                        raise RuntimeError("input returned no frame")
                else:
                    completed = process(frame)
                    if self._stop.is_set():
                        break
                    if self._copy_result:
                        completed = completed.copy()
                    with self._condition:
                        if self._enabled and not self._stop.is_set():
                            self._frame = completed
                pacer.wait(process_events=self._continue)
        except BaseException as error:
            with self._condition:
                self._error = error
        finally:
            try:
                self.source.teardown()
            except BaseException as error:
                with self._condition:
                    if self._error is None:
                        self._error = error
                    else:
                        self._error.add_note(f"capture cleanup failed: {error}")
            try:
                if self._cleanup is not None:
                    self._cleanup()
            except BaseException as error:
                with self._condition:
                    if self._error is None:
                        self._error = error
                    else:
                        self._error.add_note(f"processing cleanup failed: {error}")
            self._ready.set()
