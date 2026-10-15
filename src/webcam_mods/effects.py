"""Owned effect composition: tracking, background, then brightness."""

from contextlib import ExitStack
import threading
import time
from typing import TYPE_CHECKING, Callable, Literal, Protocol, cast

import cv2
from loguru import logger
from webcam_mods.mods.video_mods import brighten, crop_rect, resize_and_pad
from webcam_mods.profiles import Profile
from webcam_mods.utils.video import Frame
from webcam_mods.settings import StartupSettings

if TYPE_CHECKING:
    from webcam_mods.entry import BackgroundEffect


class Effect(Protocol):
    def __call__(self, frame: Frame) -> Frame | None: ...
    def close(self) -> None: ...


class TrackingEffect:
    def __init__(
        self,
        settings: StartupSettings,
        background: Effect | None = None,
        padding: tuple[float, float] | None = None,
        *,
        face_height: float = 0.4,
        max_zoom: float = 2.0,
        target_x: float = 0.5,
        target_y: float = 0.42,
        pan_deadzone: float = 0.08,
        zoom_deadzone: float = 0.08,
        pan_seconds: float = 0.25,
        zoom_seconds: float = 0.6,
        lost_after: float = 1.0,
    ) -> None:
        from webcam_mods.mods.camera_motion import CropTracker
        from webcam_mods.mods.mp_face import FaceDetector

        self.resources = ExitStack()
        if background is not None:
            self.resources.callback(background.close)
        try:
            self.detector = FaceDetector(lost_after=lost_after)
            self.resources.callback(self.detector.close)
            self.tracker = CropTracker(
                fps=(
                    min(settings.in_fps, settings.processing_fps, settings.max_out_fps)
                    if settings.repeat_frames
                    else min(settings.in_fps, settings.max_out_fps)
                ),
                aspect_ratio=settings.out_width / settings.out_height,
                face_height=face_height,
                max_zoom=max_zoom,
                target_x=target_x,
                target_y=target_y,
                pan_deadzone=pan_deadzone,
                zoom_deadzone=zoom_deadzone,
                pan_seconds=pan_seconds,
                zoom_seconds=zoom_seconds,
                lost_after=lost_after,
            )
            self.resources.callback(self.tracker.close)
            self.background = background
            self.padding = padding
            self.width, self.height = settings.out_width, settings.out_height
        except BaseException:
            self.resources.close()
            raise

    def __call__(self, frame: Frame) -> Frame | None:
        now = time.monotonic()
        prediction = self.detector.predict(frame, now=now)
        height, width = frame.shape[:2]
        result = crop_rect(
            frame,
            self.tracker.generate_crop(
                prediction, self.padding, frame_size=(width, height), now=now
            ),
        )
        if result is None:
            return None
        # fixed segmentation dimensions avoid rebuilding models on each zoom step
        if self.background is not None:
            result = resize_and_pad(result, sw=self.width, sh=self.height)
            return self.background(result)
        return result

    def close(self) -> None:
        self.resources.close()


def _read_image(path: str) -> Frame:
    image = cv2.imread(path)
    if image is None:
        raise ValueError("background image could not be read")
    return cast(Frame, image)


def _background_key(profile: Profile) -> tuple[object, ...] | None:
    if profile.effect not in ("blur", "color", "image"):
        return None
    return (
        profile.effect,
        profile.blur_kernel,
        profile.color,
        profile.image_path,
        profile.image_blur,
    )


# changing these rebuilds the segmentation model; other settings apply in place
_SEGMENTATION_FIELDS = ("segmentation", "processing", "smoothing")


class ProfileEffect:
    """Profile pipeline whose settings can change between frames.

    Order: orientation, tracking, fixed-size background, brightness. Updates are
    queued by any thread and applied on the processing thread before a frame.
    """

    def __init__(
        self,
        profile: Profile,
        settings: StartupSettings,
        *,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._profile, self._settings = profile, settings
        self._on_warning = on_warning
        self._lock = threading.Lock()
        self._pending: Profile | None = None
        self._image: tuple[str, Frame] | None = None
        self._initialized = False
        self._closed = False
        self.background: "BackgroundEffect | None" = None
        self.tracking: TrackingEffect | None = None

    @property
    def profile(self) -> Profile:
        return self._profile

    def update(self, profile: Profile) -> None:
        """Queue settings for the next frame; unreadable images fail here."""
        if self._closed:
            raise RuntimeError("profile effect is closed")
        if profile.effect == "image":
            self._load_image(profile.image_path)
        with self._lock:
            self._pending = profile

    def _load_image(self, path: str) -> Frame:
        with self._lock:
            cached = self._image
        if cached is not None and cached[0] == path:
            return cached[1]
        image = _read_image(path)
        with self._lock:
            self._image = (path, image)
        return image

    def _apply(self, profile: Profile, previous: Profile | None) -> None:
        from webcam_mods.entry import Common, BackgroundEffect

        key = _background_key(profile)
        if self.background is not None and (
            key is None
            or previous is None
            or any(
                getattr(previous, name) != getattr(profile, name)
                for name in _SEGMENTATION_FIELDS
            )
        ):
            background, self.background = self.background, None
            background.close()
        if key is not None:
            mode: Literal["blur_bg", "color_bg", "swap_bg"]
            value: int | Frame
            if profile.effect == "image":
                mode, value = "swap_bg", self._load_image(profile.image_path)
            elif profile.effect == "blur":
                mode, value = "blur_bg", profile.blur_kernel
            else:
                mode, value = "color_bg", profile.color
            kernel = profile.blur_kernel if profile.image_blur else 1
            if self.background is None:
                common = Common(
                    segmentation=profile.segmentation,  # type: ignore[arg-type]
                    processing=profile.processing,  # type: ignore[arg-type]
                    mask_smoothing=profile.smoothing,
                )
                self.background = BackgroundEffect(
                    common, mode, value, image_blur_kernel=kernel
                )
            elif previous is not None and _background_key(previous) != key:
                self.background.configure(mode, value, image_blur_kernel=kernel)
        tracked = profile.track or profile.effect == "track"
        if self.tracking is not None and not tracked:
            tracking, self.tracking = self.tracking, None
            tracking.close()
        if tracked and self.tracking is None:
            self.tracking = TrackingEffect(self._settings)
        self._profile = profile

    def _apply_pending(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None:
            return
        try:
            self._apply(pending, self._profile)
        except Exception as error:
            # keep the session running on the components that still work
            logger.error(f"failed to apply settings: {error}")
            if self._on_warning is not None:
                self._on_warning(f"Could not apply settings: {error}")

    def __call__(self, frame: Frame) -> Frame | None:
        if self._closed:
            raise RuntimeError("profile effect is closed")
        if not self._initialized:
            try:
                self._apply(self._profile, None)
            except BaseException:
                self._close_components()
                raise
            self._initialized = True
        self._apply_pending()
        profile = self._profile
        if profile.mirror:
            frame = cast(Frame, cv2.flip(frame, 1))
        if self.tracking is not None:
            tracked = self.tracking(frame)
            if tracked is None:
                return None
            frame = tracked
        if self.background is not None:
            # fixed segmentation dimensions avoid rebuilding models on crop changes
            frame = resize_and_pad(
                frame, sw=self._settings.out_width, sh=self._settings.out_height
            )
            frame = self.background(frame)
        return brighten(frame, profile.brightness) if profile.brightness else frame

    def _close_components(self) -> None:
        tracking, self.tracking = self.tracking, None
        background, self.background = self.background, None
        try:
            if tracking is not None:
                tracking.close()
        finally:
            if background is not None:
                background.close()

    def close(self) -> None:
        self._closed = True
        self._close_components()
