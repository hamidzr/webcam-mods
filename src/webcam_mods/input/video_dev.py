from webcam_mods.settings import StartupSettings, load_settings
import cv2
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.utils.video import Frame, validate_frame
from loguru import logger
from typing import cast, Any, Iterator, Optional
import math
from threading import Event


def available_camera_indices(end: int = 3) -> Iterator[int]:
    """
    Check up to `end` video devices to find available ones.
    """
    index = 0
    i = end
    while i > 0:
        cap = cv2.VideoCapture(index)
        try:
            available = cap.read()[0]
        finally:
            cap.release()
        if available:
            yield index
        index += 1
        i -= 1


def open_video_capture(
    width: Optional[int] = None,
    height: Optional[int] = None,
    input_dev: int = 0,
    *,
    fps: float | None = None,
    pixel_format: str | None = None,
) -> Optional[tuple[cv2.VideoCapture, int, int, float]]:
    # Grab the webcam feed and get the dimensions of a frame
    settings = (
        load_settings() if fps is None or pixel_format is None else StartupSettings()
    )
    fps = settings.in_fps if fps is None else fps
    pixel_format = settings.in_format if pixel_format is None else pixel_format
    if len(pixel_format) != 4:
        raise ValueError("input format must contain exactly four characters")
    videoIn = cv2.VideoCapture(input_dev)

    try:
        videoIn.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*pixel_format.upper()))

        if width is not None and height is not None:
            videoIn.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            videoIn.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # changing format or resolution may reset the device's frame rate
        videoIn.set(cv2.CAP_PROP_FPS, fps)

        if not videoIn.isOpened():
            logger.error(f"failed to open video input device #{input_dev}")
            videoIn.release()
            return None
        in_width = int(videoIn.get(cv2.CAP_PROP_FRAME_WIDTH))
        in_height = int(videoIn.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = videoIn.get(cv2.CAP_PROP_FPS)
        return (videoIn, in_width, in_height, fps)
    except BaseException as error:
        try:
            videoIn.release()
        except Exception as cleanup_error:
            error.add_note(f"capture cleanup failed: {cleanup_error}")
        raise


# @contextmanager
# def video_capture(width=None, height=None, input_dev=0):
#     videoIn, in_width, in_height, fps = open_video_capture(width, height, input_dev)
#     try:
#         yield (videoIn, in_width, in_height, fps)
#     finally:
#         videoIn.release()


class Webcam(FrameInput):
    def __init__(
        self,
        device_index: int | None = None,
        *,
        settings: StartupSettings | None = None,
        **kwargs: Any,
    ) -> None:
        self.settings = settings or load_settings()
        kwargs.setdefault("width", self.settings.in_width)
        kwargs.setdefault("height", self.settings.in_height)
        kwargs.setdefault("fps", self.settings.in_fps)
        kwargs.setdefault("device", self.settings.video_out)
        super().__init__(**kwargs)
        device_index = self.settings.video_in if device_index is None else device_index
        self.cap: cv2.VideoCapture | None = None
        self._stop = Event()
        self._pending: Frame | None = None
        self.device_index = (
            device_index
            if device_index is not None
            else next(available_camera_indices(end=5))
        )

    def setup(self) -> AdapterMetadata:
        if self.is_setup():
            return {"width": self.width, "height": self.height, "fps": self.fps}
        self.teardown()
        self._stop.clear()
        open_rv = None
        for c in range(5):
            if self._stop.is_set():
                raise RuntimeError("camera startup cancelled")
            open_rv = open_video_capture(
                width=self.width,
                height=self.height,
                input_dev=self.device_index,
                fps=self.fps,
                pixel_format=self.settings.in_format,
            )
            if open_rv is not None:
                break
            if c == 4:
                break
            logger.error(
                f"retrying ({c + 1}) to open video input device #{self.device_index}"
            )
            if self._stop.wait(2):
                raise RuntimeError("camera startup cancelled")
        if open_rv is None:
            raise FileNotFoundError("failed to open video input device")
        cap, _, _, _ = open_rv
        self.cap = cap
        try:
            # some drivers finalize negotiation only after the first frame
            ret, frame = cap.read()
            if not ret or frame is None:
                raise RuntimeError("camera produced no frame during startup")
            self._validate_frame(cast(Frame, frame), startup=True)
            fps = cap.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps <= 0:
                raise ValueError(
                    "camera did not report a valid input FPS; cannot verify --input-fps"
                )
            if not math.isclose(fps, self.fps, rel_tol=0.01, abs_tol=0.1):
                raise ValueError(
                    f"camera #{self.device_index} returned {fps:g} FPS; "
                    f"requested {self.fps:g}. Choose a supported --input-fps. "
                    "On macOS, list-cameras shows native formats; use "
                    "--capture-backend avfoundation for those formats."
                )
            self._pending = cast(Frame, frame)
            self.fps = fps
            return {"width": self.width, "height": self.height, "fps": fps}
        except BaseException as error:
            try:
                self.teardown()
            except Exception as cleanup_error:
                error.add_note(f"capture cleanup failed: {cleanup_error}")
            raise

    def _validate_frame(self, frame: Frame, *, startup: bool = False) -> None:
        validate_frame(frame)
        height, width = frame.shape[:2]
        if (width, height) != (self.width, self.height):
            if not startup:
                raise RuntimeError(
                    f"OpenCV camera #{self.device_index} changed resolution during "
                    f"capture: {self.width}x{self.height} -> {width}x{height}. "
                    "The requested mode passed startup validation, but capture "
                    "did not retain it. On macOS use --capture-backend avfoundation "
                    "to select and retain an exact camera format."
                )
            raise ValueError(
                f"camera #{self.device_index} returned {width}x{height}; "
                f"requested {self.width}x{self.height}. Choose supported "
                "--input-width and --input-height. On macOS, list-cameras "
                "shows native formats; use --capture-backend avfoundation "
                "for those formats."
            )

    def request_stop(self) -> None:
        self._stop.set()

    def teardown(self, *args: Any) -> None:
        self._pending = None
        cap, self.cap = self.cap, None
        if cap is not None:
            cap.release()

    def is_setup(self) -> bool:
        if self.cap is None:
            return False
        return self.cap.isOpened()

    def frame(self) -> Optional[Frame]:
        if self.cap is None:
            return None
        if self._pending is not None:
            pending, self._pending = self._pending, None
            return pending
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return None
        self._validate_frame(cast(Frame, frame))
        return cast(Frame, frame)
