from abc import abstractmethod
from webcam_mods.settings import load_settings
from typing import Any, Optional, Dict, Generator, Tuple
import cv2
from webcam_mods.utils.video import Frame
import datetime as dt


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
            else None
        )
        self.width = width if width is not None else settings.out_width
        self.height = height if height is not None else settings.out_height
        self.fps = fps if fps is not None else settings.max_out_fps
        self.device = device if device is not None else settings.video_out

    @abstractmethod
    def setup(self) -> Dict[str, Any]:
        raise NotImplementedError()

    def __enter__(self) -> Tuple["InNOut", Dict[str, Any]]:
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
    def teardown(self, *args, **kwargs):
        raise NotImplementedError()

    def __exit__(self, *args, **kwargs):
        self.teardown(*args, **kwargs)

    @abstractmethod
    def is_setup(self) -> bool:
        raise NotImplementedError()


class FrameInput(InNOut):
    @abstractmethod
    def frame(self) -> Optional[Frame]:
        raise NotImplementedError()

    def frames(self) -> Generator[Frame, None, None]:
        while True:
            yield self.frame()

    def demo(self):
        self.setup()
        start_time = dt.datetime.today().timestamp()
        i = 0
        for frame in self.frames():
            cv2.imshow("screen", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                cv2.destroyAllWindows()
                break
            time_diff = dt.datetime.today().timestamp() - start_time
            i += 1
            if i % 100 == 0:
                print("fps:", int(i / time_diff))

    def __enter__(self) -> Tuple["FrameInput", Dict[str, Any]]:
        return super().__enter__()  # type: ignore


class FrameOutput(InNOut):
    @abstractmethod
    def send(self, frame: Frame):
        raise NotImplementedError()

    @abstractmethod
    def wait_until_next_frame(self):
        raise NotImplementedError()

    def __enter__(self) -> Tuple["FrameOutput", Dict[str, Any]]:
        return super().__enter__()  # type: ignore

    def process_events(self) -> None:
        """Pump output events without waiting for the next frame."""

    def should_stop(self) -> bool:
        """Allow interactive outputs to end a run normally."""
        return False

    def is_in_use(self) -> bool:
        # implement to support on_demand processing feature
        raise NotImplementedError("output does not support consumer detection")
