from abc import abstractmethod
from webcam_mods.settings import StartupSettings, load_settings
from typing import Any, Optional, Generator, Self, TypedDict, NotRequired
import cv2
from webcam_mods.utils.video import Frame
import datetime as dt


class AdapterMetadata(TypedDict):
    """Negotiated adapter dimensions and cadence, plus optional device identity."""

    width: int
    height: int
    fps: float
    device: NotRequired[str]


class InNOut:
    id: str

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        device: str | None = None,
    ) -> None:
        settings = (
            load_settings()
            if any(value is None for value in (width, height, fps, device))
            else StartupSettings()
        )
        self.width = width if width is not None else settings.out_width
        self.height = height if height is not None else settings.out_height
        self.fps = fps if fps is not None else settings.max_out_fps
        self.device = device if device is not None else settings.video_out

    @abstractmethod
    def setup(self) -> AdapterMetadata:
        raise NotImplementedError()

    def __enter__(self) -> tuple[Self, AdapterMetadata]:
        try:
            return (self, self.setup())
        except BaseException as error:
            # __exit__ is not called when setup fails
            try:
                self.teardown()
            except Exception as cleanup_error:
                error.add_note(f"adapter cleanup failed: {cleanup_error}")
            raise

    @abstractmethod
    def teardown(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    def __exit__(self, *args: Any, **kwargs: Any) -> None:
        self.teardown(*args, **kwargs)

    @abstractmethod
    def is_setup(self) -> bool:
        raise NotImplementedError()


class FrameInput(InNOut):
    def request_stop(self) -> None:
        """Request read cancellation without blocking; callable from another thread.

        Resource teardown remains on the capture thread.
        """

    @abstractmethod
    def frame(self) -> Optional[Frame]:
        raise NotImplementedError()

    def frames(self) -> Generator[Optional[Frame], None, None]:
        while True:
            yield self.frame()

    def demo(self) -> None:
        self.setup()
        start_time = dt.datetime.today().timestamp()
        i = 0
        for frame in self.frames():
            if frame is None:
                continue
            cv2.imshow("screen", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                cv2.destroyAllWindows()
                break
            time_diff = dt.datetime.today().timestamp() - start_time
            i += 1
            if i % 100 == 0:
                print("fps:", int(i / time_diff))


class FrameOutput(InNOut):
    @abstractmethod
    def send(self, frame: Frame) -> None:
        raise NotImplementedError()

    @abstractmethod
    def wait_until_next_frame(self) -> None:
        raise NotImplementedError()

    def process_events(self) -> None:
        """Pump output events without waiting for the next frame."""

    def should_stop(self) -> bool:
        """Allow interactive outputs to end a run normally."""
        return False

    def is_in_use(self) -> bool:
        # implement to support on_demand processing feature
        raise NotImplementedError("output does not support consumer detection")
