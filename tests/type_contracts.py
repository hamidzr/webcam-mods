"""Static regression checks; mypy verifies intended frame/mask separation."""

from typing import assert_type

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
