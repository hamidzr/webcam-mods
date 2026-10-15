"""Face mesh landmarks, irises included, with the MediaPipe Tasks API."""

import time
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from numpy.typing import NDArray

from webcam_mods.models import model_path
from webcam_mods.utils.video import Frame, validate_frame

# MediaPipe face mesh indices, named from the viewer's side of the picture
LEFT_EYE = (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246)
RIGHT_EYE = (
    263,
    249,
    390,
    373,
    374,
    380,
    381,
    382,
    362,
    398,
    384,
    385,
    386,
    387,
    388,
    466,
)
LEFT_IRIS = (468, 469, 470, 471, 472)
RIGHT_IRIS = (473, 474, 475, 476, 477)
# lip outlines from the left mouth corner, along the lower lip and back
LIPS_OUTER = (
    61,
    146,
    91,
    181,
    84,
    17,
    314,
    405,
    321,
    375,
    291,
    409,
    270,
    269,
    267,
    0,
    37,
    39,
    40,
    185,
)
LIPS_INNER = (
    78,
    95,
    88,
    178,
    87,
    14,
    317,
    402,
    318,
    324,
    308,
    415,
    310,
    311,
    312,
    13,
    82,
    81,
    80,
    191,
)
MOUTH_CORNERS = (61, 291)
# apples of the cheeks, and the face's outer edges at cheekbone height
CHEEKS = (50, 280)
FACE_SIDES = (234, 454)
POINTS = 478

Landmarks = NDArray[np.float32]


class FaceLandmarks:
    """Lazy landmarker for one run; points of the most prominent face in pixels."""

    def __init__(self) -> None:
        self._landmarker: Any = None
        self._last_timestamp_ms = 0
        self._closed = False

    def detect(self, frame: Frame) -> Landmarks | None:
        """478 (x, y) pixel points, or None without a face."""
        if self._closed:
            raise RuntimeError("Face landmarker is closed")
        validate_frame(frame)
        if self._landmarker is None:
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(model_path("face_landmarker"))
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=1,
            )
            self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(
                options
            )
        image = mp.Image(
            image_format=mp.ImageFormat.SRGBA,
            data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)),
        )
        self._last_timestamp_ms = max(
            time.monotonic_ns() // 1_000_000, self._last_timestamp_ms + 1
        )
        result = self._landmarker.detect_for_video(image, self._last_timestamp_ms)
        if not result.face_landmarks:
            return None
        face = result.face_landmarks[0]
        if len(face) != POINTS:
            return None
        height, width = frame.shape[:2]
        points = np.array([(point.x, point.y) for point in face], np.float32)
        points *= (width, height)
        return points

    def close(self) -> None:
        landmarker, self._landmarker = self._landmarker, None
        self._closed = True
        if landmarker is not None:
            landmarker.close()
