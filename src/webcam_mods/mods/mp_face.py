"""Face detection with the MediaPipe Tasks API."""

import time
import math
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


class FaceSelector:
    """Keep the same nearby face through detection reordering and short gaps."""

    def __init__(self, lost_after: float = 1.0) -> None:
        if not math.isfinite(lost_after) or lost_after < 0:
            raise ValueError("Face loss timeout must be finite and nonnegative")
        self.lost_after = lost_after
        self._last_time: float | None = None
        self.reset()

    def reset(self) -> None:
        self._last_time = None
        self._previous: Rect | None = None
        self._seen_at: float | None = None

    def select(
        self, faces: list[Rect], frame_size: tuple[int, int], now: float
    ) -> Rect | None:
        if not math.isfinite(now) or (
            self._last_time is not None and now < self._last_time
        ):
            raise ValueError("Face selection time must be finite and monotonic")
        if self._seen_at is not None and now - self._seen_at > self.lost_after:
            self.reset()
        self._last_time = now
        faces = [face for face in faces if face.w > 0 and face.h > 0]
        if not faces:
            return None
        previous = self._previous
        if previous is None:
            width, height = frame_size
            # largest face usually belongs to the webcam user; center breaks ties
            selected = max(
                faces,
                key=lambda face: (
                    face.w * face.h,
                    -math.hypot(face.center.l - width / 2, face.center.t - height / 2),
                ),
            )
        else:

            def distance(face: Rect) -> float:
                return math.hypot(
                    face.center.l - previous.center.l, face.center.t - previous.center.t
                )

            candidates = [
                face
                for face in faces
                if 0.4 <= face.w / previous.w <= 2.5
                and 0.4 <= face.h / previous.h <= 2.5
                and distance(face) <= 1.5 * max(previous.w, previous.h)
            ]
            if not candidates:
                return None
            selected = min(candidates, key=distance)
        self._previous = Rect.from_rect(selected)
        self._seen_at = now
        return Rect.from_rect(selected)


class FaceDetector:
    """Own a lazy MediaPipe handle and monotonic video timestamps for one run."""

    def __init__(self, *, lost_after: float = 1.0) -> None:
        self._selector = FaceSelector(lost_after)
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

    def predict(self, frame: Frame, *, now: float | None = None) -> Optional[Rect]:
        """Return a persistent face as a pixel rectangle."""
        if self._detector is not None and (
            self._needs_selection
            or (self._frame_shape is not None and self._frame_shape != frame.shape)
        ):
            self._detector.close()
            self._detector = None
            self._selector.reset()
        detector = self.init(frame)
        image = mp.Image(
            image_format=mp.ImageFormat.SRGBA,
            data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)),
        )
        self._last_timestamp_ms = max(
            time.monotonic_ns() // 1_000_000, self._last_timestamp_ms + 1
        )
        results = detector.detect_for_video(image, self._last_timestamp_ms)
        faces = []
        for detection in results.detections:
            box = cast(_FaceBounds, detection.bounding_box)
            faces.append(
                Rect(w=box.width, h=box.height, l=box.origin_x, t=box.origin_y)
            )
        height, width = frame.shape[:2]
        return self._selector.select(
            faces, (width, height), time.monotonic() if now is None else now
        )

    def close(self) -> None:
        """Close the native handle; subsequent prediction is an error."""
        self._selector.reset()
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
