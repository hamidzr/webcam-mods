"""Hand gestures, such as thumbs up, with the MediaPipe Tasks API."""

import time
from typing import Any

import cv2
import mediapipe as mp
import numpy as np

from webcam_mods.models import model_path
from webcam_mods.utils.video import Frame, validate_frame

# a hand's top gesture counts from this confidence
MIN_SCORE = 0.6


class HandGestures:
    """Lazy recognizer for one run; gesture names of up to two hands."""

    def __init__(self) -> None:
        self._recognizer: Any = None
        self._last_timestamp_ms = 0
        self._closed = False

    def detect(self, frame: Frame) -> list[str]:
        """Names such as Thumb_Up, Victory or ILoveYou, one per confident hand."""
        if self._closed:
            raise RuntimeError("Gesture recognizer is closed")
        validate_frame(frame)
        if self._recognizer is None:
            options = mp.tasks.vision.GestureRecognizerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(model_path("gesture_recognizer"))
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_hands=2,
            )
            self._recognizer = mp.tasks.vision.GestureRecognizer.create_from_options(
                options
            )
        image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
        )
        self._last_timestamp_ms = max(
            time.monotonic_ns() // 1_000_000, self._last_timestamp_ms + 1
        )
        result = self._recognizer.recognize_for_video(image, self._last_timestamp_ms)
        return [
            hand[0].category_name
            for hand in result.gestures
            if hand and hand[0].score >= MIN_SCORE and hand[0].category_name != "None"
        ]

    def close(self) -> None:
        recognizer, self._recognizer = self._recognizer, None
        self._closed = True
        if recognizer is not None:
            recognizer.close()
