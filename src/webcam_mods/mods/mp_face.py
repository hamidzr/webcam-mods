"""Face detection with the MediaPipe Tasks API."""

import time
from typing import Optional, Protocol, cast

import cv2
import mediapipe as mp
from mediapipe.tasks.python.vision import FaceDetector as MediaPipeFaceDetector
import numpy as np
from loguru import logger

from webcam_mods.geometry import Rect
from webcam_mods.models import model_path
from webcam_mods.mediapipe_delegate import select_delegate
from webcam_mods.utils.video import Frame


class _FaceBounds(Protocol):
    """Pixel bounds returned by the untyped MediaPipe adapter."""

    width: int
    height: int
    origin_x: int
    origin_y: int


class FaceDetector:
    """Own a lazy MediaPipe handle and monotonic video timestamps for one run."""

    def __init__(self) -> None:
        self._detector: Optional[MediaPipeFaceDetector] = None
        self._last_timestamp_ms = 0
        self._closed = False
        self._delegate = "cpu"
        self._frame_shape: tuple[int, ...] | None = None
        self._needs_selection = False

    def init(self, frame: Frame | None = None) -> MediaPipeFaceDetector:
        if self._closed:
            raise RuntimeError("Face detector is closed")
        if self._detector is not None:
            return self._detector
        if frame is not None:
            self._delegate = select_delegate("face", frame)
            self._frame_shape = frame.shape
        self._needs_selection = frame is None
        options = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(model_path("blaze_face_full_range")),
                delegate=getattr(mp.tasks.BaseOptions.Delegate, self._delegate.upper()),
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            min_detection_confidence=0.6,
        )
        try:
            self._detector = MediaPipeFaceDetector.create_from_options(options)
        except RuntimeError, ValueError:
            if self._delegate != "gpu":
                raise
            logger.warning("Metal face initialization failed; using CPU")
            self._delegate = "cpu"
            options.base_options.delegate = mp.tasks.BaseOptions.Delegate.CPU
            self._detector = MediaPipeFaceDetector.create_from_options(options)
        return self._detector

    def predict(self, frame: Frame) -> Optional[Rect]:
        """Return first detected face as a pixel rectangle."""
        if self._detector is not None and (
            self._needs_selection
            or (self._frame_shape is not None and self._frame_shape != frame.shape)
        ):
            self._detector.close()
            self._detector = None
        detector = self.init(frame)
        image = mp.Image(
            image_format=mp.ImageFormat.SRGBA,
            data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)),
        )
        self._last_timestamp_ms = max(
            time.monotonic_ns() // 1_000_000, self._last_timestamp_ms + 1
        )
        results = detector.detect_for_video(image, self._last_timestamp_ms)
        if not results.detections:
            logger.trace("no face detected")
            return None
        box = cast(_FaceBounds, results.detections[0].bounding_box)
        return Rect(w=box.width, h=box.height, l=box.origin_x, t=box.origin_y)

    def close(self) -> None:
        """Close the native handle; subsequent prediction is an error."""
        if self._detector is not None:
            try:
                self._detector.close()
            finally:
                self._detector = None
                self._closed = True
        else:
            self._closed = True


# legacy helpers retain one lazy instance; CLI sessions use their own detector
_default_detector = FaceDetector()


def init() -> MediaPipeFaceDetector:
    return _default_detector.init()


def predict(frame: Frame) -> Optional[Rect]:
    """Compatibility helper; new runs should own a FaceDetector instance."""
    return _default_detector.predict(frame)
