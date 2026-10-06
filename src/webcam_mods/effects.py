"""Owned effect composition: tracking, background, then brightness."""

from contextlib import ExitStack
import time
from typing import Protocol, cast

import cv2
from webcam_mods.mods.video_mods import brighten, crop_rect, resize_and_pad
from webcam_mods.profiles import Profile
from webcam_mods.utils.video import Frame
from webcam_mods.settings import StartupSettings


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


class ProfileEffect:
    def __init__(self, profile: Profile, settings: StartupSettings) -> None:
        from webcam_mods.entry import BackgroundEffect, Common

        self.resources = ExitStack()
        self.brightness = profile.brightness
        common = Common(segmentation=profile.segmentation, processing=profile.processing, mask_smoothing=profile.smoothing)  # type: ignore[arg-type]
        background = None
        try:
            if profile.effect == "blur":
                background = BackgroundEffect(common, "blur_bg", profile.blur_kernel)
            elif profile.effect == "color":
                background = BackgroundEffect(common, "color_bg", profile.color)
            elif profile.effect == "image":
                image = cv2.imread(profile.image_path)
                if image is None:
                    raise ValueError("background image could not be read")
                background = BackgroundEffect(common, "swap_bg", cast(Frame, image))
            if background is not None and not (
                profile.track or profile.effect == "track"
            ):
                self.resources.callback(background.close)
            self.transform: Effect | None = (
                TrackingEffect(settings, background=background)
                if profile.track or profile.effect == "track"
                else background
            )
            if isinstance(self.transform, TrackingEffect):
                self.resources.callback(self.transform.close)
        except BaseException:
            self.resources.close()
            raise

    def __call__(self, frame: Frame) -> Frame | None:
        result = self.transform(frame) if self.transform is not None else frame
        return (
            brighten(result, self.brightness)
            if result is not None and self.brightness
            else result
        )

    def close(self) -> None:
        self.resources.close()
