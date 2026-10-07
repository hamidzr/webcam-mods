"""One capture/effect worker publishing an owned latest frame, without a queue."""

from collections.abc import Callable
from threading import Condition, Event, Thread
import math

from webcam_mods.input.input import AdapterMetadata, FrameInput, validate_metadata
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
        self._continuous = True
        self._requested = False
        self._frame: Frame | None = None
        self._error: BaseException | None = None
        self._metadata: AdapterMetadata | None = None
        self._thread = Thread(
            target=self._run, name="webcam-frame-producer", daemon=True
        )

    def start(self) -> None:
        """Begin capture setup without blocking frame delivery."""
        self._thread.start()

    def metadata(self) -> AdapterMetadata | None:
        self.latest()
        return self._metadata if self._ready.is_set() else None

    def setup(self) -> AdapterMetadata:
        self.start()
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
        continuous: bool = True,
    ) -> None:
        """Configure processing; copy_result=False requires an owned, stable result."""
        with self._condition:
            self._process = process
            self._fps = fps
            self._before_frame = before_frame
            self._strict = strict
            self._copy_result = copy_result
            self._continuous = continuous

    def request_frame(self) -> None:
        """Request exactly one fresh frame in direct-delivery mode."""
        with self._condition:
            self._requested = True
            self._condition.notify_all()

    def take(self, timeout: float = 0) -> Frame | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._frame is not None
                or self._error is not None
                or self._stop.is_set(),
                timeout=timeout,
            )
            frame = self.latest()
            self._frame = None
            return frame

    def enable(self, enabled: bool) -> None:
        with self._condition:
            self._activation_requested = True
            self._enabled = enabled
            if not enabled:
                self._frame = None
                self._requested = False
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
        cancellation_error: BaseException | None = None
        try:
            self.source.request_stop()
        except BaseException as error:
            cancellation_error = error
        if self._thread.ident is not None:
            try:
                self._thread.join(self._shutdown_timeout)
            except BaseException as error:
                if self._thread.is_alive():
                    raise WorkerShutdownTimeout(
                        "worker shutdown interrupted; processing cleanup deferred"
                    ) from error
                raise
            if self._thread.is_alive():
                raise WorkerShutdownTimeout(
                    "capture/effect worker is still stopping; "
                    "processing cleanup deferred until it exits"
                ) from cancellation_error
        else:
            try:
                self.source.teardown()
            finally:
                if self._cleanup is not None:
                    self._cleanup()
        if cancellation_error is not None:
            raise cancellation_error

    def _sleep(self, seconds: float) -> None:
        self._stop.wait(seconds)

    def _continue(self) -> bool:
        with self._condition:
            return not self._stop.is_set() and self._enabled

    def _run(self) -> None:
        try:
            self._metadata = self.source.setup()
            validate_metadata(self._metadata, "input")
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
                    self._condition.wait_for(
                        lambda: self._stop.is_set()
                        or not self._enabled
                        or self._continuous
                        or self._requested
                    )
                    if self._stop.is_set():
                        break
                    if not self._enabled:
                        continue
                    self._requested = False
                    process = self._process
                if process is None:
                    raise RuntimeError("capture worker was not configured")
                if not self.source.is_setup():
                    self._metadata = self.source.setup()
                    validate_metadata(self._metadata, "input")
                if self._stop.is_set():
                    break
                if pacer is None and self._continuous:
                    pacer = FramePacer(
                        min(self._fps, self._metadata["fps"]), sleep=self._sleep
                    )
                if self._before_frame is not None:
                    self._before_frame()
                frame = self.source.frame()
                if self._stop.is_set():
                    break
                if frame is None:
                    if self._strict:
                        raise RuntimeError("input returned no frame")
                    if not self._continuous:
                        with self._condition:
                            self._requested = True
                        self._sleep(1 / min(self._fps, self._metadata["fps"]))
                else:
                    completed = process(frame)
                    if self._stop.is_set():
                        break
                    if self._copy_result:
                        completed = completed.copy()
                    with self._condition:
                        if self._enabled and not self._stop.is_set():
                            self._frame = completed
                            self._condition.notify_all()
                if pacer is not None:
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
            with self._condition:
                self._condition.notify_all()
