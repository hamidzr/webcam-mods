"""Face detection with the MediaPipe Tasks API."""

import time
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
from loguru import logger

from webcam_mods.geometry import Rect
from webcam_mods.models import model_path

_detector: Optional[mp.tasks.vision.FaceDetector] = None
_last_timestamp_ms = 0


def init() -> mp.tasks.vision.FaceDetector:
    global _detector
    if _detector is None:
        options = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(model_path("blaze_face_full_range")),
                delegate=mp.tasks.BaseOptions.Delegate.CPU,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            min_detection_confidence=0.6,
        )
        _detector = mp.tasks.vision.FaceDetector.create_from_options(options)
    return _detector


def predict(frame: np.ndarray) -> Optional[Rect]:
    """Return first detected face as a pixel rectangle."""
    global _last_timestamp_ms
    image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
    )
    _last_timestamp_ms = max(time.monotonic_ns() // 1_000_000, _last_timestamp_ms + 1)
    results = init().detect_for_video(image, _last_timestamp_ms)
    if not results.detections:
        logger.trace("no face detected")
        return None
    box = results.detections[0].bounding_box
    return Rect(w=box.width, h=box.height, l=box.origin_x, t=box.origin_y)
