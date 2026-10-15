"""Owned effect composition: tracking, background, then brightness."""

from contextlib import ExitStack
import threading
import time
from typing import TYPE_CHECKING, Callable, Literal, Protocol, TypedDict, cast

import cv2
from loguru import logger
import numpy as np
from webcam_mods.geometry import Rect
from webcam_mods.mods.video_mods import brighten, crop_rect, resize_and_pad
from webcam_mods.output.native_preview import Guides
from webcam_mods.profiles import Profile
from webcam_mods.stats import RateMeter
from webcam_mods.utils.video import Frame
from webcam_mods.settings import StartupSettings

if TYPE_CHECKING:
    from webcam_mods.entry import BackgroundEffect
    from webcam_mods.mods.person_segmentation import Mask


class Effect(Protocol):
    def __call__(self, frame: Frame) -> Frame | None: ...
    def close(self) -> None: ...


class PreviewSink(Protocol):
    def wants(self, view: str) -> bool: ...
    def publish(
        self, frame: Frame, view: str = "output", guides: Guides | None = None
    ) -> None: ...


def _normalized(rect: Rect, width: int, height: int) -> list[float]:
    return [
        round(rect.left / width, 4),
        round(rect.top / height, 4),
        round(rect.width / width, 4),
        round(rect.height / height, 4),
    ]


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
            self.face: Rect | None = None
            self.crop: Rect | None = None
            self.width, self.height = settings.out_width, settings.out_height
        except BaseException:
            self.resources.close()
            raise

    def __call__(self, frame: Frame, region: Rect | None = None) -> Frame | None:
        """Frame the face; with a region, framing stays inside that part.

        Detection always sees the whole frame, so region changes never reload it.
        """
        now = time.monotonic()
        prediction = self.detector.predict(frame, now=now)
        left, top = (0, 0) if region is None else (region.left, region.top)
        area = frame if region is None else _region_pixels(frame, region)
        height, width = area.shape[:2]
        local = prediction
        if region is not None and prediction is not None:
            local = Rect(
                w=prediction.w,
                h=prediction.h,
                t=prediction.t - top,
                l=prediction.l - left,
            )
            if (
                local.left + local.width <= 0
                or local.top + local.height <= 0
                or local.left >= width
                or local.top >= height
            ):
                local = None
        crop = self.tracker.generate_crop(
            local, self.padding, frame_size=(width, height), now=now
        )
        # last face and crop in input pixels, for preview guides
        self.face = prediction
        self.crop = Rect(w=crop.w, h=crop.h, t=crop.t + top, l=crop.l + left)
        result = crop_rect(area, crop)
        if result is None:
            return None
        # fixed segmentation dimensions avoid rebuilding models on each zoom step
        if self.background is not None:
            result = resize_and_pad(result, sw=self.width, sh=self.height)
            return self.background(result)
        return result

    def configure(self, **options: float) -> None:
        """Change framing preferences without resetting motion or the detector."""
        self.tracker.configure(**options)

    def close(self) -> None:
        self.resources.close()


class TrackingOptions(TypedDict):
    face_height: float
    target_y: float
    max_zoom: float
    pan_seconds: float
    zoom_seconds: float
    pan_deadzone: float
    zoom_deadzone: float


def _tracking_options(profile: Profile) -> TrackingOptions:
    """Map profile framing fields to CropTracker settings."""
    return {
        "face_height": profile.track_face_height,
        "target_y": profile.track_target_y,
        "max_zoom": profile.track_max_zoom,
        "pan_seconds": profile.track_follow_seconds,
        # keep the CLI's default zoom-to-pan response ratio of 0.6 / 0.25
        "zoom_seconds": profile.track_follow_seconds * 2.4,
        "pan_deadzone": profile.track_deadzone,
        "zoom_deadzone": profile.track_deadzone,
    }


def _crop_region(
    crop: tuple[float, float, float, float], width: int, height: int
) -> Rect:
    """Pixel rectangle for a fractional crop, kept inside the frame."""
    x, y, w, h = crop
    crop_width = max(2, min(width, round(w * width)))
    crop_height = max(2, min(height, round(h * height)))
    return Rect(
        w=crop_width,
        h=crop_height,
        t=min(max(0, round(y * height)), height - crop_height),
        l=min(max(0, round(x * width)), width - crop_width),
    )


def _region_pixels(frame: Frame, region: Rect) -> Frame:
    return frame[
        region.top : region.top + region.height,
        region.left : region.left + region.width,
    ]


def _mask_frame(mask: "Mask") -> Frame:
    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.ndim == 3:
        alpha = alpha[:, :, 0]
    gray = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    return cast(Frame, cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))


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

    Order: orientation, manual crop with optional tracking inside it, fixed-size
    background, brightness. Updates are
    queued by any thread and applied on the processing thread before a frame.
    Source and mask preview frames are encoded only while the app shows them.
    """

    def __init__(
        self,
        profile: Profile,
        settings: StartupSettings,
        *,
        on_warning: Callable[[str], None] | None = None,
        preview: PreviewSink | None = None,
    ) -> None:
        self._profile, self._settings = profile, settings
        self._on_warning = on_warning
        self._preview = preview
        # processed frames per second and effect time
        self.stats = RateMeter()
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
        options = _tracking_options(profile)
        if tracked and self.tracking is None:
            self.tracking = TrackingEffect(self._settings, **options)
        elif (
            self.tracking is not None
            and previous is not None
            and _tracking_options(previous) != options
        ):
            self.tracking.configure(**options)
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
        started = time.perf_counter()
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
        source = frame
        height, width = frame.shape[:2]
        region = (
            None if profile.crop is None else _crop_region(profile.crop, width, height)
        )
        if self.tracking is not None:
            tracked = self.tracking(frame, region)
            if tracked is None:
                return None
            frame = tracked
        elif region is not None:
            frame = _region_pixels(frame, region)
        preview = self._preview
        if preview is not None and preview.wants("source"):
            preview.publish(source, "source", self._guides(source, region))
        if self.background is not None:
            # fixed segmentation dimensions avoid rebuilding models on crop changes
            frame = resize_and_pad(
                frame, sw=self._settings.out_width, sh=self._settings.out_height
            )
            frame = self.background(frame)
            mask = self.background.mask
            if preview is not None and mask is not None and preview.wants("mask"):
                preview.publish(_mask_frame(mask), "mask")
        if profile.brightness:
            frame = brighten(frame, profile.brightness)
        self.stats.tick(time.perf_counter() - started)
        return frame

    def _guides(self, source: Frame, region: Rect | None) -> Guides:
        """Crop, face and framing boxes as fractions of the source frame."""
        height, width = source.shape[:2]
        guides: Guides = {}
        if region is not None:
            guides["crop"] = _normalized(region, width, height)
        if self.tracking is not None:
            if self.tracking.face is not None:
                guides["face"] = _normalized(self.tracking.face, width, height)
            if self.tracking.crop is not None:
                guides["framing"] = _normalized(self.tracking.crop, width, height)
        return guides

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
