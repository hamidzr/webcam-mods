"""Session-owned segmentation with portable and optional macOS backends."""

import time
from typing import Literal

import cv2
import numpy as np

from webcam_mods.mods.video_mods import ensure_rgb_color
from webcam_mods.models import model_path

BG_COLOR = (192, 192, 192)


class MediaPipeSegmenter:
    def __init__(self) -> None:
        self._segmenter = None
        self._timestamp_ms = 0
        self._closed = False

    def predict(self, frame: np.ndarray) -> np.ndarray:
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
        return results.confidence_masks[0].numpy_view().squeeze(axis=-1).copy()

    def close(self) -> None:
        self._closed = True
        if self._segmenter is not None:
            self._segmenter.close()
            self._segmenter = None


class PersonEffects:
    def __init__(
        self,
        backend: Literal["mediapipe", "vision"] = "mediapipe",
        processing: Literal["opencv", "coreimage"] = "opencv",
        quality: str = "balanced",
    ) -> None:
        if backend == "mediapipe":
            self.segmenter = MediaPipeSegmenter()
        elif backend == "vision":
            from webcam_mods.macos.vision import VisionSegmenter

            self.segmenter = VisionSegmenter(quality=quality)
        else:
            raise ValueError(f"unknown segmentation backend: {backend}")
        self.processor = None
        if processing == "coreimage":
            from webcam_mods.macos.core_image import CoreImageProcessor

            self.processor = CoreImageProcessor()
        elif processing != "opencv":
            raise ValueError(f"unknown processing backend: {processing}")
        self.backend = backend
        self._closed = False

    def mask(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self._closed:
            raise RuntimeError("person effects are closed")
        image = cv2.flip(frame, 1)
        result = self.segmenter.predict(image)
        if self.backend == "mediapipe":
            result = cv2.dilate(result, np.ones((5, 5), np.uint8), iterations=1)
            result = cv2.blur(result, (10, 10))
            result = sigmoid(result)
        return image, result[:, :, None]

    def color_bg(self, frame: np.ndarray, color=BG_COLOR) -> np.ndarray:
        image, mask = self.mask(frame)
        color = ensure_rgb_color(color)
        if self.processor is not None:
            return self.processor.process(image, mask[:, :, 0], color=tuple(color))
        return apply_alpha_mask(image, np.asarray(color, dtype=np.float32), mask)

    def blur_bg(self, frame: np.ndarray, kernel_size: int) -> np.ndarray:
        if kernel_size <= 0 or kernel_size % 2 == 0:
            raise ValueError("blur kernel size must be a positive odd number")
        image, mask = self.mask(frame)
        if self.processor is not None:
            return self.processor.process(
                image, mask[:, :, 0], blur_radius=(kernel_size - 1) / 2
            )
        return apply_alpha_mask(
            image, cv2.blur(image, (kernel_size, kernel_size)), mask
        )

    def swap_bg(self, frame: np.ndarray, bg_image: np.ndarray) -> np.ndarray:
        image, mask = self.mask(frame)
        # background tracks the prepared crop, padding and replay dimensions
        background = cv2.resize(bg_image, (image.shape[1], image.shape[0]))
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


def sigmoid(x: np.ndarray, a: float = 5.0, b: float = -10.0) -> np.ndarray:
    return 1 / (1 + np.exp(a + b * x))


def apply_alpha_mask(fg: np.ndarray, bg: np.ndarray, mask: np.ndarray) -> np.ndarray:
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


def mask(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    image, alpha = _effects().mask(frame)
    return image, np.broadcast_to(alpha, image.shape)


def color_bg(frame: np.ndarray, color=BG_COLOR) -> np.ndarray:
    return _effects().color_bg(frame, color)


def blur_bg(frame: np.ndarray, kernel_size: int) -> np.ndarray:
    return _effects().blur_bg(frame, kernel_size)


def swap_bg(frame: np.ndarray, bg_image: np.ndarray) -> np.ndarray:
    return _effects().swap_bg(frame, bg_image)
