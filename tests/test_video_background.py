"""Looping video backgrounds: timing, looping and profile playback."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.video_background import LoopingVideo
from webcam_mods.profiles import Profile
from webcam_mods.settings import StartupSettings

LEVELS = (0, 60, 120, 180, 240)


def write_video(path: Path, fps: float = 10) -> None:
    """Five uniform frames whose gray level identifies them."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), fps, (32, 24))
    for level in LEVELS:
        writer.write(np.full((24, 32, 3), level, np.uint8))
    writer.release()


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class LoopingVideoTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "loop.avi"
        write_video(self.path)

    def level(self, frame: np.ndarray) -> int:
        return min(LEVELS, key=lambda level: abs(level - float(frame.mean())))

    def test_frames_follow_the_clock_and_loop(self) -> None:
        clock = Clock()
        video = LoopingVideo(str(self.path), clock=clock)
        self.addCleanup(video.close)
        self.assertEqual(video.fps, 10)
        first = video.frame()
        self.assertEqual(self.level(first), 0)
        clock.now += 0.05
        # faster processing repeats the same frame object
        self.assertIs(video.frame(), first)
        clock.now += 0.05
        self.assertEqual(self.level(video.frame()), 60)
        clock.now += 0.3
        self.assertEqual(self.level(video.frame()), 240)
        clock.now += 0.1
        self.assertEqual(self.level(video.frame()), 0)
        clock.now += 0.1
        self.assertEqual(self.level(video.frame()), 60)

    def test_long_stall_moves_one_frame_instead_of_catching_up(self) -> None:
        clock = Clock()
        video = LoopingVideo(str(self.path), clock=clock)
        self.addCleanup(video.close)
        video.frame()
        clock.now += 30
        self.assertEqual(self.level(video.frame()), 60)
        clock.now += 0.1
        self.assertEqual(self.level(video.frame()), 120)

    def test_unreadable_files_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "could not be read"):
            LoopingVideo(str(self.path.with_name("missing.avi")))
        text = self.path.with_name("notes.txt")
        text.write_text("not a video")
        with self.assertRaises(ValueError):
            LoopingVideo(str(text))


class ProfileVideoBackgroundTests(unittest.TestCase):
    def test_image_effect_plays_video_and_releases_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.avi"
            write_video(path)
            still = Path(directory) / "still.png"
            cv2.imwrite(str(still), np.full((24, 32, 3), 200, np.uint8))
            segmenter = Mock()
            segmenter.predict.side_effect = lambda image: np.zeros(
                image.shape[:2], np.float32
            )
            clock = Clock()
            with (
                patch(
                    "webcam_mods.mods.person_segmentation.MediaPipeSegmenter",
                    return_value=segmenter,
                ),
                patch("time.monotonic", clock),
            ):
                effect = ProfileEffect(
                    Profile(effect="image", image_path=str(path)),
                    StartupSettings(out_width=32, out_height=24),
                )
                self.addCleanup(effect.close)
                frame = np.full((24, 32, 3), 90, np.uint8)
                levels = []
                for _ in range(3):
                    result = effect(frame)
                    assert result is not None
                    levels.append(round(float(result.mean())))
                    clock.now += 0.1
                self.assertEqual(
                    [min(LEVELS, key=lambda x: abs(x - v)) for v in levels],
                    [0, 60, 120],
                )
                video = effect._video
                assert video is not None
                effect.update(Profile(effect="image", image_path=str(still)))
                result = effect(frame)
                assert result is not None
                self.assertAlmostEqual(float(result.mean()), 200, delta=3)
                self.assertIsNone(effect._video)
                self.assertFalse(video._capture.isOpened())


if __name__ == "__main__":
    unittest.main()
