"""Headless E2E: PNG input -> live loop -> real mods -> PNG output."""

import argparse
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Optional
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from webcam_mods.config import ERROR_IMAGE
from webcam_mods.geometry import Rect
from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.input.video_dev import Webcam
from webcam_mods.loopback import live_loop
from webcam_mods.mods import mp_face, person_segmentation
from webcam_mods.mods.camera_motion import generate_crop
from webcam_mods.mods.video_mods import brighten, crop, crop_rect, resize_and_pad

ARTIFACT_ROOT: Optional[Path] = None
FRAME_COUNT = 8


class ImageSequence(FrameInput):
    def __init__(self, paths: list[Path]) -> None:
        super().__init__(width=320, height=240, fps=30)
        self.paths = paths
        self.index = 0
        self.active = False

    def setup(self) -> dict[str, Any]:
        self.active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any) -> None:
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def frame(self) -> Optional[np.ndarray]:
        if self.index == len(self.paths):
            return None
        frame = cv2.imread(str(self.paths[self.index]))
        self.index += 1
        return frame


class ImageWriter(FrameOutput):
    def __init__(self, directory: Path) -> None:
        super().__init__(width=160, height=120, fps=30)
        self.directory = directory
        self.paths: list[Path] = []
        self.active = False

    def setup(self) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any) -> None:
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def send(self, frame: np.ndarray) -> None:
        if frame.shape != (self.height, self.width, 3) or frame.dtype != np.uint8:
            raise ValueError(f"invalid output frame: {frame.shape}, {frame.dtype}")
        path = self.directory / f"{len(self.paths):03d}.png"
        if not cv2.imwrite(str(path), frame):
            raise OSError(f"failed to write {path}")
        self.paths.append(path)

    def wait_until_next_frame(self) -> None:
        pass


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (ARTIFACT_ROOT or Path(self.temp.name)) / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=True)
        self.frames = []
        self.paths = []
        y, x = np.indices((240, 320))
        for index in range(FRAME_COUNT):
            # moving checkerboard exposes ordering, channel and blur failures
            checks = ((x + index * 8) // 16 + y // 16) % 2
            frame = np.stack(
                (checks * 120 + 20 + index * 2, checks * 80 + 30, checks * 60 + 40),
                axis=-1,
            ).astype(np.uint8)
            path = self.root / f"input-{index:03d}.png"
            self.assertTrue(cv2.imwrite(str(path), frame))
            self.frames.append(frame)
            self.paths.append(path)
        self.source = ImageSequence(self.paths)
        self.sink = ImageWriter(self.root / "output")

    def run_pipeline(
        self,
        mod: Optional[Callable[[np.ndarray], Optional[np.ndarray]]] = None,
        **kwargs: Any,
    ) -> list[np.ndarray]:
        start = time.perf_counter()
        try:
            live_loop(
                pace=False,
                mod=mod,
                fIn=self.source,
                fOut=self.sink,
                interactive_listener=None,
                on_demand=False,
                max_frames=kwargs.pop("max_frames", FRAME_COUNT),
                strict_errors=kwargs.pop("strict_errors", True),
                **kwargs,
            )
        finally:
            self.assertFalse(self.source.is_setup(), "input leaked")
            self.assertFalse(self.sink.is_setup(), "output leaked")
        elapsed = time.perf_counter() - start
        self.assertEqual(len(self.sink.paths), FRAME_COUNT)
        frames = [cv2.imread(str(path)) for path in self.sink.paths]
        for frame in frames:
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, (120, 160, 3))
        self.assertGreater(np.std(frames[0]), 0, "blank output")
        if ARTIFACT_ROOT:
            preview = np.concatenate(
                [cv2.resize(self.frames[0], (160, 120)), frames[0]], axis=1
            )
            self.assertTrue(cv2.imwrite(str(self.root / "preview.png"), preview))
            (self.root / "metrics.json").write_text(
                json.dumps({"frames": len(frames), "seconds": elapsed}, indent=2)
            )
        return frames

    def test_passthrough_resize(self) -> None:
        frames = self.run_pipeline()
        for original, actual in zip(self.frames, frames):
            np.testing.assert_array_equal(actual, resize_and_pad(original, 160, 120))

    def use_person_fixture(self) -> np.ndarray:
        image = cv2.imread(str(Path(__file__).parent / "fixtures" / "astronaut.png"))
        self.assertIsNotNone(image)
        self.frames = [image.copy() for _ in range(FRAME_COUNT)]
        for path, frame in zip(self.paths, self.frames):
            self.assertTrue(cv2.imwrite(str(path), frame))
        self.source.width = self.source.height = 512
        return image

    def test_detect_and_crop_face(self) -> None:
        self.use_person_fixture()

        def effect(frame: np.ndarray) -> np.ndarray:
            box = mp_face.predict(frame)
            self.assertIsNotNone(box, "known face not detected")
            self.assertTrue(150 < box.l < 230 and 40 < box.t < 100)
            cropped = crop_rect(frame, generate_crop(box, (2, 2.5)))
            self.assertIsNotNone(cropped, "face crop outside frame")
            self.assertLess(cropped.shape[0], frame.shape[0])
            return cropped

        self.run_pipeline(effect)

    def test_person_preserved_background_replaced(self) -> None:
        image = self.use_person_fixture()
        frames = self.run_pipeline(
            lambda frame: person_segmentation.color_bg(frame, (0, 255, 0))
        )
        reference = resize_and_pad(cv2.flip(image, 1), 160, 120)
        # mirrored face interior and upper-left background, including letterbox offset
        face = np.s_[18:32, 85:95]
        background = np.s_[5:15, 25:35]
        for frame in frames:
            self.assertLess(
                np.abs(frame[face].astype(float) - reference[face]).mean(),
                25,
                "person removed",
            )
            self.assertLess(
                np.abs(frame[background].astype(float) - (0, 255, 0)).mean(),
                25,
                "background retained",
            )

    def test_crop_brightness(self) -> None:
        def effect(frame: np.ndarray) -> np.ndarray:
            return brighten(crop(frame, 160, 120, 32, 24), 25)

        frames = self.run_pipeline(effect)
        for original, actual in zip(self.frames, frames):
            # independent geometric and color checks, including frame ordering
            expected = original[24:144, 32:192]
            original_value = cv2.cvtColor(expected, cv2.COLOR_BGR2HSV)[:, :, 2]
            actual_value = cv2.cvtColor(actual, cv2.COLOR_BGR2HSV)[:, :, 2]
            np.testing.assert_array_equal(actual_value, original_value + 25)
            self.assertGreater(float(actual.mean()), float(expected.mean()))

    def test_crop_at_edges(self) -> None:
        for left, top in [(-20, -20), (300, 220)]:
            with self.subTest(left=left, top=top):
                frames = self.run_pipeline(
                    lambda frame: crop_rect(frame, Rect(w=160, h=120, l=left, t=top))
                )
                x, y = (0, 0) if left < 0 else (160, 120)
                np.testing.assert_array_equal(
                    frames[0], self.frames[0][y : y + 120, x : x + 160]
                )
                self.source.index = 0
                self.sink.paths.clear()
        oversized = crop_rect(self.frames[0], Rect(w=1000, h=1000, l=-100, t=-100))
        np.testing.assert_array_equal(oversized, self.frames[0])

    def test_background_blur_brightness(self) -> None:
        frames = self.run_pipeline(
            lambda frame: brighten(person_segmentation.blur_bg(frame, 31), 20)
        )
        baseline = resize_and_pad(self.frames[0], 160, 120)
        before = cv2.Laplacian(baseline, cv2.CV_64F).var()
        after = cv2.Laplacian(frames[0], cv2.CV_64F).var()
        self.assertLess(after, before * 0.25, "background was not blurred")
        self.assertGreater(float(frames[0].mean()), float(baseline.mean()))

    def test_background_color(self) -> None:
        frames = self.run_pipeline(
            lambda frame: person_segmentation.color_bg(frame, (40, 100, 180))
        )
        for frame in frames:
            self.assertLess(np.abs(frame.astype(float) - (40, 100, 180)).mean(), 5)

    def test_background_swap(self) -> None:
        background = np.full((240, 320, 3), (160, 50, 80), dtype=np.uint8)
        frames = self.run_pipeline(
            lambda frame: person_segmentation.swap_bg(frame, background)
        )
        for frame in frames:
            self.assertLess(np.abs(frame.astype(float) - (160, 50, 80)).mean(), 5)

    def test_face_absent(self) -> None:
        def effect(frame: np.ndarray) -> np.ndarray:
            self.assertIsNone(mp_face.predict(frame))
            return frame

        frames = self.run_pipeline(effect)
        for original, actual in zip(self.frames, frames):
            np.testing.assert_array_equal(actual, resize_and_pad(original, 160, 120))

    def test_error_image(self) -> None:
        def fail(frame: np.ndarray) -> np.ndarray:
            raise ValueError("intentional E2E failure")

        frames = self.run_pipeline(fail, strict_errors=False)
        expected = resize_and_pad(cv2.imread(str(ERROR_IMAGE)), 160, 120)
        for frame in frames:
            np.testing.assert_array_equal(frame, expected)

    def test_freeze_on_error(self) -> None:
        def effect(frame: np.ndarray) -> np.ndarray:
            if self.source.index > 1:
                raise ValueError("intentional E2E failure")
            return frame

        frames = self.run_pipeline(effect, strict_errors=False, freeze_on_error=True)
        expected = resize_and_pad(self.frames[0], 160, 120)
        for frame in frames:
            np.testing.assert_array_equal(frame, expected)

    def test_strict_error_cleanup(self) -> None:
        def fail(frame: np.ndarray) -> np.ndarray:
            raise ValueError("intentional E2E failure")

        with self.assertRaisesRegex(ValueError, "intentional E2E failure"):
            self.run_pipeline(fail)

    def test_empty_mod_cleanup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "mod returned no frame"):
            self.run_pipeline(lambda frame: None)

    def test_exhausted_input_cleanup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "input returned no frame"):
            self.run_pipeline(lambda frame: frame, max_frames=FRAME_COUNT + 1)

    def test_camera_setup_failure_cleanup(self) -> None:
        camera = Webcam()
        with (
            patch("webcam_mods.input.video_dev.open_video_capture", return_value=None),
            patch("webcam_mods.input.video_dev.time.sleep"),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "failed to open"):
                live_loop(
                    pace=False,
                    fIn=camera,
                    fOut=self.sink,
                    interactive_listener=None,
                    on_demand=False,
                    max_frames=1,
                    strict_errors=True,
                )
        self.assertFalse(camera.is_setup())
        self.assertFalse(self.sink.is_setup())

    def test_output_failure_cleanup(self) -> None:
        def fail(frame: np.ndarray) -> None:
            raise OSError("intentional output failure")

        self.sink.send = fail
        with self.assertRaisesRegex(OSError, "intentional output failure"):
            self.run_pipeline(lambda frame: frame)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    ARTIFACT_ROOT = args.artifacts
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PipelineTest)
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if ARTIFACT_ROOT:
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_ROOT / "report.json").write_text(
            json.dumps(
                {
                    "passed": result.wasSuccessful(),
                    "tests": result.testsRun,
                    "failures": len(result.failures),
                    "errors": len(result.errors),
                    "seconds": time.perf_counter() - started,
                    "scope": "disk input, live_loop, real effects, decoded PNG output",
                },
                indent=2,
            )
        )
    raise SystemExit(0 if result.wasSuccessful() else 1)
