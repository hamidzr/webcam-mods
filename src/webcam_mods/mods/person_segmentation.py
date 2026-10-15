"""Session-owned segmentation with portable and optional macOS backends."""

from functools import lru_cache
import time
from typing import Any, Literal, cast
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame, validate_frame
from webcam_mods.mods.mask_stabilizer import MaskStabilizer
from webcam_mods.macos.vision import Quality, VisionSegmenter
from webcam_mods.macos.core_image import CoreImageProcessor

import cv2
import numpy as np

from webcam_mods.mods.video_mods import Color, ensure_rgb_color
from webcam_mods.models import model_path
from webcam_mods.mediapipe_delegate import select_delegate
from loguru import logger

BG_COLOR = (192, 192, 192)
Mask = NDArray[np.float32]
_SEGMENTATION_KERNEL = np.ones((5, 5), np.uint8)


class MediaPipeSegmenter:
    def __init__(self) -> None:
        self._segmenter: Any = None
        self._timestamp_ms = 0
        self._closed = False
        self._delegate = "cpu"
        self._frame_shape: tuple[int, ...] | None = None

    def predict(self, frame: Frame) -> Mask:
        if self._closed:
            raise RuntimeError("segmenter is closed")
        validate_frame(frame)
        import mediapipe as mp

        if (
            self._segmenter is not None
            and self._frame_shape is not None
            and self._frame_shape != frame.shape
        ):
            self._segmenter.close()
            self._segmenter = None
        if self._segmenter is None:
            self._delegate = select_delegate("segmentation", frame)
            self._frame_shape = frame.shape
            options = mp.tasks.vision.ImageSegmenterOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(model_path("selfie_segmenter")),
                    delegate=getattr(
                        mp.tasks.BaseOptions.Delegate, self._delegate.upper()
                    ),
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                output_confidence_masks=True,
            )
            try:
                self._segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(
                    options
                )
            except RuntimeError, ValueError:
                if self._delegate != "gpu":
                    raise
                logger.warning("Metal segmentation initialization failed; using CPU")
                self._delegate = "cpu"
                options.base_options.delegate = mp.tasks.BaseOptions.Delegate.CPU
                self._segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(
                    options
                )
        image = mp.Image(
            image_format=mp.ImageFormat.SRGBA,
            data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)),
        )
        self._timestamp_ms = max(
            time.monotonic_ns() // 1_000_000, self._timestamp_ms + 1
        )
        results = self._segmenter.segment_for_video(image, self._timestamp_ms)
        return (
            np.asarray(results.confidence_masks[0].numpy_view(), dtype=np.float32)
            .squeeze(axis=-1)
            .copy()
        )

    def close(self) -> None:
        self._closed = True
        if self._segmenter is not None:
            try:
                self._segmenter.close()
            finally:
                self._segmenter = None


class PersonEffects:
    def __init__(
        self,
        backend: Literal["mediapipe", "vision"] = "mediapipe",
        processing: Literal["opencv", "coreimage"] = "opencv",
        quality: Quality = "balanced",
        smoothing: bool = False,
    ) -> None:
        self.segmenter: MediaPipeSegmenter | VisionSegmenter
        if backend == "mediapipe":
            self.segmenter = MediaPipeSegmenter()
        elif backend == "vision":
            self.segmenter = VisionSegmenter(quality=quality)
        else:
            raise ValueError(f"unknown segmentation backend: {backend}")
        self.processor: CoreImageProcessor | None = None
        if processing == "coreimage":
            self.processor = CoreImageProcessor()
        elif processing != "opencv":
            raise ValueError(f"unknown processing backend: {processing}")
        self.stabilizer = MaskStabilizer() if smoothing else None
        self.backend = backend
        self._closed = False
        self._background_source: Frame | None = None
        self._background: Frame | None = None
        self._background_blur_kernel = 1
        self._background_anchor: tuple[float, float] | None = None
        # latest mask, aligned with the effect output, for the mask preview
        self.last_mask: Mask | None = None

    def mask(self, frame: Frame) -> tuple[Frame, Mask]:
        if self._closed:
            raise RuntimeError("person effects are closed")
        validate_frame(frame)
        image = cast(Frame, cv2.flip(frame, 1))
        result = self.segmenter.predict(image)
        if self.backend == "mediapipe":
            result = cast(Mask, cv2.dilate(result, _SEGMENTATION_KERNEL, iterations=1))
            result = cast(Mask, cv2.blur(result, (10, 10)))
            result = sigmoid(result)
        if self.stabilizer is not None:
            result = self.stabilizer.apply(image, result)
        self.last_mask = result
        return image, result[:, :, None]

    def color_bg(self, frame: Frame, color: Color = BG_COLOR) -> Frame:
        channels = ensure_rgb_color(color)
        image, mask = self.mask(frame)
        if self.processor is not None:
            return self.processor.process(
                image,
                mask[:, :, 0],
                color=(int(channels[0]), int(channels[1]), int(channels[2])),
            )
        return apply_alpha_mask(image, np.asarray(channels, dtype=np.float32), mask)

    def blur_bg(self, frame: Frame, kernel_size: int) -> Frame:
        if kernel_size <= 0 or kernel_size % 2 == 0:
            raise ValueError("blur kernel size must be a positive odd number")
        image, mask = self.mask(frame)
        if self.processor is not None:
            return self.processor.process(
                image, mask[:, :, 0], blur_radius=(kernel_size - 1) / 2
            )
        return apply_alpha_mask(
            image, cast(Frame, cv2.blur(image, (kernel_size, kernel_size))), mask
        )

    def spotlight(self, frame: Frame, dim: int, lift: int) -> Frame:
        """Darken the background by dim percent and brighten the person by lift."""
        if not 0 <= dim <= 100 or not 0 <= lift <= 100:
            raise ValueError("spotlight dim and lift must be in 0..100")
        image, mask = self.mask(frame)
        background = cast(Frame, cv2.convertScaleAbs(image, alpha=1 - dim / 100))
        foreground = cast(Frame, cv2.LUT(image, _lift_table(lift))) if lift else image
        if self.processor is not None:
            return self.processor.process(
                foreground, mask[:, :, 0], background=background
            )
        return apply_alpha_mask(foreground, background, mask)

    def set_background(
        self,
        bg_image: Frame,
        *,
        blur_kernel: int = 1,
        anchor: tuple[float, float] | None = None,
    ) -> None:
        """Own a background snapshot for repeated calls without a background argument.

        With an anchor, the image fills the frame without distortion and keeps that
        point, as fractions from the left and top, in view; otherwise it stretches.
        """
        if self._closed:
            raise RuntimeError("person effects are closed")
        validate_frame(bg_image)
        if type(blur_kernel) is not int or blur_kernel <= 0 or blur_kernel % 2 == 0:
            raise ValueError("blur kernel size must be a positive odd number")
        if anchor is not None and not all(0 <= value <= 1 for value in anchor):
            raise ValueError("background anchor must be fractions in 0..1")
        self._background_source = bg_image.copy()
        self._background_blur_kernel = blur_kernel
        self._background_anchor = anchor
        self._background = None

    def swap_bg(self, frame: Frame, bg_image: Frame | None = None) -> Frame:
        if bg_image is not None:
            self.set_background(bg_image)
        if self._background_source is None:
            raise ValueError("background image is required")
        image, mask = self.mask(frame)
        # background tracks the prepared crop, padding and replay dimensions
        if self._background is None or self._background.shape != image.shape:
            source = self._background_source
            if self._background_anchor is not None:
                source = _fill_crop(
                    source, image.shape[1], image.shape[0], self._background_anchor
                )
            background = cast(
                Frame, cv2.resize(source, (image.shape[1], image.shape[0]))
            )
            if self._background_blur_kernel > 1:
                background = cast(
                    Frame,
                    cv2.blur(
                        background,
                        (self._background_blur_kernel, self._background_blur_kernel),
                    ),
                )
            self._background = background
        background = self._background
        if self.processor is not None:
            return self.processor.process(image, mask[:, :, 0], background=background)
        return apply_alpha_mask(image, background, mask)

    def close(self) -> None:
        self._closed = True
        self._background_source = self._background = None
        self.last_mask = None
        if self.stabilizer is not None:
            self.stabilizer.reset()
        try:
            self.segmenter.close()
        finally:
            if self.processor is not None:
                self.processor.close()


def _fill_crop(
    image: Frame, width: int, height: int, anchor: tuple[float, float]
) -> Frame:
    """Largest part of image with the target aspect, slid toward anchor."""
    source_height, source_width = image.shape[:2]
    if source_width * height > width * source_height:
        crop_width, crop_height = round(source_height * width / height), source_height
    else:
        crop_width, crop_height = source_width, round(source_width * height / width)
    crop_width, crop_height = max(crop_width, 1), max(crop_height, 1)
    left = round((source_width - crop_width) * anchor[0])
    top = round((source_height - crop_height) * anchor[1])
    return image[top : top + crop_height, left : left + crop_width]


@lru_cache(maxsize=8)
def _lift_table(lift: int) -> NDArray[np.uint8]:
    # gamma curve lifts shadows and mid tones while black and white stay put
    levels = np.arange(256, dtype=np.float64) / 255
    curve = np.power(levels, 1 / (1 + lift / 100))
    return np.rint(curve * 255).astype(np.uint8)


def sigmoid(x: Mask, a: float = 5.0, b: float = -10.0) -> Mask:
    return np.asarray(1 / (1 + np.exp(a + b * x)), dtype=np.float32)


def apply_alpha_mask(fg: Frame, bg: Frame | Mask, mask: Mask) -> Frame:
    # broadcasting keeps masks single-channel and blend intermediates float32
    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.ndim == 2:
        alpha = alpha[:, :, None]
    background = np.asarray(bg, dtype=np.float32)
    result = cast(Mask, np.subtract(fg, background, dtype=np.float32))
    np.multiply(result, alpha, out=result)
    np.add(result, background, out=result)
    return np.clip(result, 0, 255, out=result).astype(np.uint8)


# compatibility helpers for existing Python callers; CLI uses owned instances
_default_effects: PersonEffects | None = None


def _effects() -> PersonEffects:
    global _default_effects
    if _default_effects is None:
        _default_effects = PersonEffects()
    return _default_effects


def mask(frame: Frame) -> tuple[Frame, Mask]:
    image, alpha = _effects().mask(frame)
    return image, np.broadcast_to(alpha, image.shape)


def color_bg(frame: Frame, color: Color = BG_COLOR) -> Frame:
    return _effects().color_bg(frame, color)


def blur_bg(frame: Frame, kernel_size: int) -> Frame:
    return _effects().blur_bg(frame, kernel_size)


def swap_bg(frame: Frame, bg_image: Frame) -> Frame:
    return _effects().swap_bg(frame, bg_image)
