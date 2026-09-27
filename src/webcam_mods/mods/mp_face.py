"""Face detection with OpenCV YuNet."""

from typing import Optional

import cv2
import numpy as np
from loguru import logger

from webcam_mods.geometry import Rect
from webcam_mods.models import model_path

_detector: Optional[cv2.FaceDetectorYN] = None


def init() -> cv2.FaceDetectorYN:
    global _detector
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(
            str(model_path("yunet_face")), "", (320, 320), score_threshold=0.6
        )
    return _detector


def predict(frame: np.ndarray) -> Optional[Rect]:
    """Return first detected face as a pixel rectangle."""
    detector = init()
    detector.setInputSize((frame.shape[1], frame.shape[0]))
    _, faces = detector.detect(frame)
    if faces is None:
        logger.trace("no face detected")
        return None
    x, y, width, height = faces[0, :4]
    return Rect(w=int(width), h=int(height), l=int(x), t=int(y))
