"""Session-owned segmentation with portable and optional macOS backends."""

import time
from typing import Any, Literal, cast
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame
from webcam_mods.macos.vision import Quality, VisionSegmenter
from webcam_mods.macos.core_image import CoreImageProcessor

import cv2
import numpy as np

from webcam_mods.mods.video_mods import Color, ensure_rgb_color
from webcam_mods.models import model_path

BG_COLOR = (192, 192, 192)
Mask = NDArray[np.float32]


class MediaPipeSegmenter:
    def __init__(self) -> None:
        self._segmenter: Any = None
        self._timestamp_ms = 0
        self._closed = False

    def predict(self, frame: Frame) -> Mask:
        if self._closed:
            raise RuntimeError("segmenter is closed")
        import mediapipe as mp

        if self._segmenter is None:
            self._segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(
                mp.tasks.vision.ImageSegmenterOptions(
                    base_options=mp.tasks.BaseOptions(
                        model_asset_path=str(model_path("selfie_segmenter")),
                        delegate=mp.tasks.BaseOptions.Delegate.CPU,
                    ),
                    running_mode=mp.tasks.vision.RunningMode.VIDEO,
                    output_confidence_masks=True,
                )
            )
        image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
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
        self.backend = backend
        self._closed = False

    def mask(self, frame: Frame) -> tuple[Frame, Mask]:
        if self._closed:
            raise RuntimeError("person effects are closed")
        image = cast(Frame, cv2.flip(frame, 1))
        result = self.segmenter.predict(image)
        if self.backend == "mediapipe":
            result = cast(
                Mask, cv2.dilate(result, np.ones((5, 5), np.uint8), iterations=1)
            )
            result = cast(Mask, cv2.blur(result, (10, 10)))
            result = sigmoid(result)
        return image, result[:, :, None]

    def color_bg(self, frame: Frame, color: Color = BG_COLOR) -> Frame:
        image, mask = self.mask(frame)
        channels = ensure_rgb_color(color)
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

    def swap_bg(self, frame: Frame, bg_image: Frame) -> Frame:
        image, mask = self.mask(frame)
        # background tracks the prepared crop, padding and replay dimensions
        background = cast(Frame, cv2.resize(bg_image, (image.shape[1], image.shape[0])))
        if self.processor is not None:
            return self.processor.process(image, mask[:, :, 0], background=background)
        return apply_alpha_mask(image, background, mask)

    def close(self) -> None:
        self._closed = True
        try:
            self.segmenter.close()
        finally:
            if self.processor is not None:
                self.processor.close()


def sigmoid(x: Mask, a: float = 5.0, b: float = -10.0) -> Mask:
    return np.asarray(1 / (1 + np.exp(a + b * x)), dtype=np.float32)


def apply_alpha_mask(fg: Frame, bg: Frame | Mask, mask: Mask) -> Frame:
    # broadcasting keeps masks single-channel and blend intermediates float32
    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.ndim == 2:
        alpha = alpha[:, :, None]
    foreground = np.asarray(fg, dtype=np.float32)
    background = np.asarray(bg, dtype=np.float32)
    result = background + (foreground - background) * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


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
