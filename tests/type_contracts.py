"""Static regression checks; mypy verifies intended frame/mask separation."""

from typing import assert_type

from webcam_mods.geometry import Point, Rect
from webcam_mods.input.input import AdapterMetadata, FrameInput, FrameOutput
from webcam_mods.mods.mp_face import FaceDetector
from webcam_mods.mods.camera_motion import CropTracker
from webcam_mods.mods.record_replay import Recorder
from webcam_mods.mods.video_mods import crop, resize_and_pad
from webcam_mods.mods.person_segmentation import Mask, PersonEffects
from webcam_mods.utils.video import Frame


def frame_contracts(frame: Frame, confidence: Mask, effects: PersonEffects) -> None:
    recorder = Recorder()
    assert_type(recorder.engage(frame), Frame)
    assert_type(crop(frame, 2, 2), Frame | None)
    assert_type(resize_and_pad(frame, 2, 2), Frame)
    assert_type(effects.mask(frame), tuple[Frame, Mask])
    # unused-ignore checks fail if Frame regresses to Any
    recorder.engage(confidence)  # type: ignore[arg-type]


def face_geometry_metadata_contracts(
    frame: Frame,
    confidence: Mask,
    detector: FaceDetector,
    tracker: CropTracker,
    source: FrameInput,
    output: FrameOutput,
) -> None:
    assert_type(detector.predict(frame), Rect | None)
    assert_type(Point(t=5, l=9).tuple, tuple[int, int])
    assert_type((Point(t=5, l=9) / 2.5).t, int)
    assert_type(Rect().center, Point)
    assert_type(tracker.generate_crop(Rect(), None), Rect)
    assert_type(source.setup(), AdapterMetadata)
    assert_type(output.setup()["width"], int)
    assert_type(output.setup()["fps"], float)
    detector.predict(confidence)  # type: ignore[arg-type]
    invalid: AdapterMetadata = {"width": "640", "height": 480, "fps": 30.0}  # type: ignore[typeddict-item]
    missing: AdapterMetadata = {"fps": 30.0}  # type: ignore[typeddict-item]
