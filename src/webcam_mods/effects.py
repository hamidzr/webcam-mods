"""Owned effect composition: tracking, background, color, then overlays."""

from contextlib import ExitStack
import threading
import time
from typing import TYPE_CHECKING, Callable, Protocol, TypedDict, cast

import cv2
from loguru import logger
import numpy as np
from webcam_mods.geometry import Rect
from webcam_mods.mods.color import (
    AutoLight,
    ColorAdjuster,
    ColorSettings,
    neutral_balance,
)
from webcam_mods.mods.denoise import TemporalDenoiser
from webcam_mods.mods.eye_contact import correct_gaze
from webcam_mods.mods.face_landmarks import FaceLandmarks
from webcam_mods.mods.looks import ColorLook, builtin_look, load_cube
from webcam_mods.mods.makeup import Makeup, apply_makeup
from webcam_mods.mods.overlay import Logo, Overlay, OverlaySettings, Position, load_logo
from webcam_mods.mods.perspective import PerspectiveView
from webcam_mods.mods.presenter import Alpha, bubble, cutout, place
from webcam_mods.mods.reactions import Reactions
from webcam_mods.mods.record_replay import Recorder
from webcam_mods.mods.touchup import smooth_skin
from webcam_mods.mods.video_background import LoopingVideo
from webcam_mods.mods.video_mods import brighten, crop_rect, resize_and_pad
from webcam_mods.output.native_preview import Guides
from webcam_mods.profiles import Profile
from webcam_mods.stats import RateMeter
from webcam_mods.utils.video import Frame
from webcam_mods.settings import StartupSettings

if TYPE_CHECKING:
    from webcam_mods.entry import BackgroundEffect, BackgroundMode
    from webcam_mods.mods.person_segmentation import Mask, PersonEffects


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


_ROTATIONS = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def _orient(frame: Frame, profile: Profile) -> Frame:
    """Rotate clockwise, then mirror and flip as the viewer sees the picture."""
    if profile.rotate:
        frame = cast(Frame, cv2.rotate(frame, _ROTATIONS[profile.rotate]))
    if profile.mirror or profile.flip_vertical:
        code = -1 if profile.mirror and profile.flip_vertical else int(profile.mirror)
        frame = cast(Frame, cv2.flip(frame, code))
    return frame


def _color_settings(profile: Profile) -> ColorSettings:
    return ColorSettings(
        exposure=profile.exposure,
        contrast=profile.contrast,
        saturation=profile.saturation,
        temperature=profile.temperature,
        tint=profile.tint,
        sharpness=profile.sharpness,
    )


def _makeup(profile: Profile) -> Makeup:
    return Makeup(
        lip_color=profile.lip_bgr,
        lip_strength=profile.lip_strength,
        blush_color=profile.blush_bgr,
        blush_strength=profile.blush_strength,
    )


def _overlay_settings(profile: Profile) -> OverlaySettings:
    return OverlaySettings(
        logo_path=profile.logo_path,
        logo_position=cast(Position, profile.logo_position),
        logo_scale=profile.logo_scale,
        logo_opacity=profile.logo_opacity,
        caption=profile.caption,
        caption_detail=profile.caption_detail,
        caption_position=cast(Position, profile.caption_position),
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


def _read_background(path: str) -> Frame | None:
    """Still image at path, or None when it is a playable video."""
    image = cv2.imread(path)
    if image is not None:
        return cast(Frame, image)
    LoopingVideo(path).close()
    return None


def _background_key(profile: Profile) -> tuple[object, ...] | None:
    # screens get no background effect; a presenter cutout segments the camera
    if profile.source != "camera" or profile.effect not in (
        "blur",
        "color",
        "image",
        "spotlight",
    ):
        return None
    return (
        profile.effect,
        profile.blur_kernel,
        profile.background_bgr,
        profile.image_path,
        profile.image_blur,
        profile.image_x,
        profile.image_y,
        profile.spotlight_dim,
        profile.spotlight_lift,
    )


# changing these rebuilds the segmentation model; other settings apply in place
_SEGMENTATION_FIELDS = ("segmentation", "processing", "smoothing")


class ProfileEffect:
    """Profile pipeline whose settings can change between frames.

    Order: orientation, noise reduction, desk view straightening or manual crop
    with optional tracking inside it, auto light, eye contact, skin touch-up,
    makeup, fixed-size background, brightness, color, look, overlays, gesture
    reactions. Gestures are read from the lit camera picture. A screen source
    skips orientation, noise reduction, tracking and background; with the
    presenter on, the camera picture is oriented, cleaned, lit and graded, then
    placed over the output-sized screen before overlays. The recorder keeps finished frames; while
    it replays, they replace the whole pipeline. Updates are queued by any thread
    and applied on the processing thread before a frame. Source, original and mask
    preview frames are encoded only while the app shows them.
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
        self._image: tuple[str, Frame | None] | None = None
        # looping video background, opened and closed on the processing thread
        self._video: LoopingVideo | None = None
        self._cube: tuple[str, ColorLook] | None = None
        self.look: ColorLook | None = None
        self._logo: tuple[str, Logo] | None = None
        self.overlay: Overlay | None = None
        # newest presenter camera frame, wired by the session for screen sources
        self.camera_feed: Callable[[], Frame | None] | None = None
        # person segmentation for the presenter cutout
        self.presenter_effects: "PersonEffects | None" = None
        # camera frame and profile behind the last presenter layer
        self._presented: tuple[Frame, Profile, Frame, Alpha] | None = None
        self._initialized = False
        self._closed = False
        self.background: "BackgroundEffect | None" = None
        self.tracking: TrackingEffect | None = None
        self.perspective: PerspectiveView | None = None
        self.color = ColorAdjuster()
        self.auto_light = AutoLight(0)
        self.denoiser = TemporalDenoiser(0)
        # face mesh for eye contact and makeup, made while a profile uses either
        self.landmarks: FaceLandmarks | None = None
        # gesture reactions, made while a profile uses them
        self.reactions: Reactions | None = None
        # latest oriented camera frame, sampled for click-to-white-balance
        self._source: Frame | None = None
        # output loop for stepping away; commands arrive from the control thread
        self.recorder = Recorder(compress=True)
        self._record_lock = threading.Lock()

    @property
    def profile(self) -> Profile:
        return self._profile

    def update(self, profile: Profile) -> None:
        """Queue settings for the next frame; unreadable images fail here."""
        if self._closed:
            raise RuntimeError("profile effect is closed")
        if profile.effect == "image":
            self._load_image(profile.image_path)
        if profile.look == "custom":
            self._load_cube(profile.look_path)
        if profile.logo_path:
            self._load_logo(profile.logo_path)
        with self._lock:
            self._pending = profile

    def _load_image(self, path: str) -> Frame | None:
        with self._lock:
            cached = self._image
        if cached is not None and cached[0] == path:
            return cached[1]
        image = _read_background(path)
        with self._lock:
            self._image = (path, image)
        return image

    def _load_cube(self, path: str) -> ColorLook:
        with self._lock:
            cached = self._cube
        if cached is not None and cached[0] == path:
            return cached[1]
        try:
            look = load_cube(path)
        except OSError as error:
            raise ValueError(
                f"look file could not be read: {error.strerror}"
            ) from error
        with self._lock:
            self._cube = (path, look)
        return look

    def _load_logo(self, path: str) -> Logo:
        with self._lock:
            cached = self._logo
        if cached is not None and cached[0] == path:
            return cached[1]
        logo = load_logo(path)
        with self._lock:
            self._logo = (path, logo)
        return logo

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
        video: LoopingVideo | None = None
        if key is not None:
            mode: "BackgroundMode"
            value: int | Frame | tuple[int, int, int] | LoopingVideo
            if profile.effect == "image":
                image = self._load_image(profile.image_path)
                if image is not None:
                    mode, value = "swap_bg", image
                else:
                    video = (
                        self._video
                        if self._video is not None
                        and self._video.path == profile.image_path
                        else LoopingVideo(profile.image_path)
                    )
                    mode, value = "swap_bg", video
            elif profile.effect == "blur":
                mode, value = "blur_bg", profile.blur_kernel
            elif profile.effect == "spotlight":
                mode, value = "spotlight_bg", profile.spotlight_dim
            else:
                mode, value = "color_bg", profile.background_bgr
            kernel = profile.blur_kernel if profile.image_blur else 1
            anchor = (profile.image_x, profile.image_y)
            try:
                if self.background is None:
                    common = Common(
                        segmentation=profile.segmentation,  # type: ignore[arg-type]
                        processing=profile.processing,  # type: ignore[arg-type]
                        mask_smoothing=profile.smoothing,
                    )
                    self.background = BackgroundEffect(
                        common,
                        mode,
                        value,
                        image_blur_kernel=kernel,
                        image_anchor=anchor,
                        lift=profile.spotlight_lift,
                    )
                elif previous is not None and _background_key(previous) != key:
                    self.background.configure(
                        mode,
                        value,
                        image_blur_kernel=kernel,
                        image_anchor=anchor,
                        lift=profile.spotlight_lift,
                    )
            except BaseException:
                if video is not None and video is not self._video:
                    video.close()
                raise
            if profile.segmentation == "chroma":
                self.background.effects.configure_key(
                    profile.key_bgr,
                    profile.key_tolerance,
                    profile.key_softness,
                    profile.key_spill,
                )
        # the background now plays the new video, or none
        if self._video is not video:
            if self._video is not None:
                self._video.close()
            self._video = video
        cutout_on = profile.presenting and profile.presenter_style == "cutout"
        if self.presenter_effects is not None and (
            not cutout_on
            or previous is None
            or any(
                getattr(previous, name) != getattr(profile, name)
                for name in _SEGMENTATION_FIELDS
            )
        ):
            effects, self.presenter_effects = self.presenter_effects, None
            effects.close()
        if cutout_on and self.presenter_effects is None:
            from webcam_mods.mods.person_segmentation import PersonEffects

            self.presenter_effects = PersonEffects(
                backend=profile.segmentation,  # type: ignore[arg-type]
                smoothing=profile.smoothing,
            )
        if self.presenter_effects is not None and profile.segmentation == "chroma":
            self.presenter_effects.configure_key(
                profile.key_bgr,
                profile.key_tolerance,
                profile.key_softness,
                profile.key_spill,
            )
        desk = profile.perspective if profile.source == "camera" else None
        if desk is None:
            self.perspective = None
        elif (
            self.perspective is None
            or previous is None
            or (previous.perspective != desk)
        ):
            self.perspective = PerspectiveView(desk)
        # desk view replaces framing, so tracking closes while it is on
        tracked = (
            profile.source == "camera"
            and desk is None
            and (profile.track or profile.effect == "track")
        )
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
        self.color.configure(_color_settings(profile))
        self.auto_light.configure(profile.auto_light)
        if previous is None or profile.denoise != previous.denoise:
            self.denoiser.configure(profile.denoise)
        # shared screens without the presenter have no camera picture to read
        camera = profile.source == "camera" or profile.presenting
        face = camera and bool(
            profile.eye_contact or profile.lip_strength or profile.blush_strength
        )
        if face and self.landmarks is None:
            self.landmarks = FaceLandmarks()
        elif not face and self.landmarks is not None:
            landmarks, self.landmarks = self.landmarks, None
            landmarks.close()
        if profile.reactions and camera and self.reactions is None:
            self.reactions = Reactions(on_warning=self._on_warning)
        elif not (profile.reactions and camera) and self.reactions is not None:
            reactions, self.reactions = self.reactions, None
            reactions.close()
        if profile.look == "none" or profile.look_strength == 0:
            self.look = None
        elif profile.look == "custom":
            self.look = self._load_cube(profile.look_path)
        else:
            self.look = builtin_look(profile.look)
        overlay = _overlay_settings(profile)
        if overlay.is_empty():
            self.overlay = None
        elif self.overlay is None or self.overlay.settings != overlay:
            logo = self._load_logo(overlay.logo_path) if overlay.logo_path else None
            self.overlay = Overlay(overlay, logo)
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

    def recording(self) -> dict[str, str | float]:
        """Recorder state and recorded seconds."""
        with self._record_lock:
            return {
                "recorder": self.recorder.state,
                "recorded_seconds": round(self.recorder.seconds, 1),
            }

    def record(self, action: str) -> dict[str, str | float]:
        """Record the output, stop, or replay the recording in place of the camera."""
        with self._record_lock:
            if not self.recorder.command(action):
                raise ValueError(
                    "nothing recorded yet"
                    if action == "replay"
                    else "action must be record, stop or replay"
                )
        return self.recording()

    def __call__(self, frame: Frame) -> Frame | None:
        if self._closed:
            raise RuntimeError("profile effect is closed")
        started = time.perf_counter()
        with self._record_lock:
            replaying = self.recorder.replaying
            if replaying:
                # the recording stands in for the camera; nothing else runs
                result: Frame | None = self.recorder.engage(frame)
        if not replaying:
            result = self._process(frame)
            if result is not None:
                with self._record_lock:
                    result = self.recorder.engage(result)
        if result is not None:
            self.stats.tick(time.perf_counter() - started)
        return result

    def _process(self, frame: Frame) -> Frame | None:
        if not self._initialized:
            try:
                self._apply(self._profile, None)
            except BaseException:
                self._close_components()
                raise
            self._initialized = True
        self._apply_pending()
        profile = self._profile
        if profile.source == "camera":
            frame = _orient(frame, profile)
        source = self._source = frame
        if profile.source == "camera":
            # whole frames, so framing changes never restart the averaging
            frame = self._denoise(frame, profile)
        height, width = frame.shape[:2]
        region = (
            None
            if profile.crop is None or self.perspective is not None
            else _crop_region(profile.crop, width, height)
        )
        if self.perspective is not None:
            frame = self.perspective(frame)
        elif self.tracking is not None:
            tracked = self.tracking(frame, region)
            if tracked is None:
                return None
            frame = tracked
        elif region is not None:
            frame = _region_pixels(frame, region)
        preview = self._preview
        if preview is not None and preview.wants("source"):
            preview.publish(source, "source", self._guides(source, region))
        if preview is not None and preview.wants("original"):
            # same framing as output without image effects, for hold-to-compare
            preview.publish(frame, "original")
        if profile.presenting:
            frame = self._present(frame, profile)
            if self.overlay is not None:
                frame = self.overlay(frame)
            return self._react(frame)
        # before segmentation so masks see the lifted picture; images stay as chosen
        frame = self._light(frame, profile)
        if self.reactions is not None:
            self.reactions.detect(frame, time.monotonic())
        if self.background is not None:
            # fixed segmentation dimensions avoid rebuilding models on crop changes
            frame = resize_and_pad(
                frame, sw=self._settings.out_width, sh=self._settings.out_height
            )
            # segmentation flips once for legacy CLI commands; pre-flipping cancels
            # it so only the mirror setting decides orientation, as in plain output
            frame = self.background(cast(Frame, cv2.flip(frame, 1)))
            mask = self.background.mask
            if preview is not None and mask is not None and preview.wants("mask"):
                preview.publish(_mask_frame(mask), "mask")
        frame = self._grade(frame, profile)
        if self.overlay is not None:
            frame = self.overlay(frame)
        return self._react(frame)

    def _react(self, frame: Frame) -> Frame:
        """The playing gesture reaction over the finished picture."""
        if self.reactions is None:
            return frame
        return self.reactions.draw(frame, time.monotonic())

    def _denoise(self, frame: Frame, profile: Profile) -> Frame:
        return self.denoiser(frame) if profile.denoise else frame

    def _light(self, frame: Frame, profile: Profile) -> Frame:
        """Auto light, eye contact, skin touch-up and makeup, on the camera picture."""
        frame = self.auto_light(frame, time.monotonic())
        points = None if self.landmarks is None else self.landmarks.detect(frame)
        if points is not None and profile.eye_contact:
            frame = correct_gaze(frame, points, profile.eye_contact)
        if profile.touchup:
            frame = smooth_skin(frame, profile.touchup)
        makeup = _makeup(profile)
        if points is not None and not makeup.is_empty():
            # the irises moved, but lips and cheeks are where the mesh found them
            frame = apply_makeup(frame, points, makeup)
        return frame

    def _grade(self, frame: Frame, profile: Profile) -> Frame:
        """Brightness, color and look."""
        if profile.brightness:
            frame = brighten(frame, profile.brightness)
        frame = self.color(frame)
        if self.look is not None:
            frame = self.look(frame, profile.look_strength / 100)
        return frame

    def _present(self, screen: Frame, profile: Profile) -> Frame:
        """Output-sized screen with the newest camera picture in a corner."""
        width, height = self._settings.out_width, self._settings.out_height
        frame = resize_and_pad(screen, sw=width, sh=height)
        camera = None if self.camera_feed is None else self.camera_feed()
        if camera is None:
            return frame
        presented = self._presented
        if presented is not None and presented[0] is camera and presented[1] is profile:
            # the camera runs slower than the screen; reuse the graded layer
            layer, alpha = presented[2], presented[3]
        else:
            picture = self._denoise(_orient(camera, profile), profile)
            picture = self._light(picture, profile)
            if self.reactions is not None:
                self.reactions.detect(picture, time.monotonic())
            size = max(2, round(height * profile.presenter_size / 100))
            if self.presenter_effects is not None:
                # segmentation flips once for legacy CLI commands; pre-flip cancels it
                image, mask = self.presenter_effects.mask(
                    cast(Frame, cv2.flip(picture, 1))
                )
                layer, alpha = cutout(image, mask, size)
            else:
                layer, alpha = bubble(picture, size)
            layer = self._grade(layer, profile)
            self._presented = (camera, profile, layer, alpha)
        return place(
            frame,
            layer,
            alpha,
            profile.presenter_position,
            standing=self.presenter_effects is not None,
        )

    def white_balance(self, x: float, y: float) -> tuple[int, int]:
        """Temperature and tint that turn a patch of the camera picture neutral gray.

        x and y are fractions of the oriented camera frame, as in the source view.
        """
        source = self._source
        if source is None:
            raise RuntimeError("no camera picture yet")
        height, width = source.shape[:2]
        radius = max(2, round(min(width, height) * 0.02))
        column = min(max(round(x * width), 0), width - 1)
        row = min(max(round(y * height), 0), height - 1)
        patch = source[
            max(0, row - radius) : row + radius + 1,
            max(0, column - radius) : column + radius + 1,
        ]
        return neutral_balance(patch)

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
        video, self._video = self._video, None
        presenter, self.presenter_effects = self.presenter_effects, None
        landmarks, self.landmarks = self.landmarks, None
        reactions, self.reactions = self.reactions, None
        self._presented = None
        try:
            if tracking is not None:
                tracking.close()
        finally:
            try:
                if background is not None:
                    background.close()
            finally:
                try:
                    if video is not None:
                        video.close()
                finally:
                    try:
                        if presenter is not None:
                            presenter.close()
                    finally:
                        try:
                            if landmarks is not None:
                                landmarks.close()
                        finally:
                            if reactions is not None:
                                reactions.close()

    def close(self) -> None:
        self._closed = True
        self._source = None
        with self._record_lock:
            self.recorder.close()
        self._close_components()
