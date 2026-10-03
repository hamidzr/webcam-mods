"""Repeatable comparison inputs, review artifacts and failure cleanup."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from scripts.compare_segmentation import FIXTURE, compare, frames


class ComparisonTests(unittest.TestCase):
    def test_fixture_phases_include_motion_dim_light_and_departure(self) -> None:
        sequence = list(frames(FIXTURE, 2, 32, 24))
        self.assertEqual(
            [phase for phase, _ in sequence],
            [
                phase
                for phase in ("static", "translation", "dim", "departure")
                for _ in range(2)
            ],
        )
        self.assertFalse(np.array_equal(sequence[2][1], sequence[3][1]))
        self.assertLess(sequence[4][1].mean(), sequence[0][1].mean())
        self.assertEqual(sequence[-1][1].max(), 0)

    def test_comparison_writes_reviewable_artifacts_and_closes(self) -> None:
        effects = Mock()
        effects.mask.side_effect = lambda frame: (
            frame,
            np.full((*frame.shape[:2], 1), 0.5, np.float32),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report = compare(FIXTURE, output, effects, 2, 32, 24)
            self.assertEqual(
                set(report["phases"]), {"static", "translation", "dim", "departure"}
            )
            self.assertEqual(report["warmup_frames"], 10)
            self.assertEqual(
                cv2.imread(str(output / "comparison.jpg")).shape, (24 * 8, 32 * 4, 3)
            )
            with np.load(output / "masks.npz") as masks:
                self.assertEqual(masks["static_raw"].dtype, np.float32)
            self.assertTrue((output / "metrics.json").exists())
        effects.close.assert_called_once()

    def test_inference_failure_closes_without_report(self) -> None:
        effects = Mock()
        effects.mask.side_effect = RuntimeError("inference failed")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                compare(FIXTURE, output, effects, 2, 32, 24)
            self.assertFalse((output / "metrics.json").exists())
        effects.close.assert_called_once()
