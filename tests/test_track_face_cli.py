"""Framing options and face loss reach the bounded tracker through the CLI."""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from typer.testing import CliRunner

from webcam_mods import entry
from webcam_mods.geometry import Rect


class TrackFaceCliTests(unittest.TestCase):
    def test_options_and_missing_predictions_reach_tracker(self) -> None:
        detector = MagicMock()
        detector.predict.side_effect = [Rect(w=80, h=80), None]
        tracker = MagicMock()
        tracker.generate_crop.return_value = Rect(w=640, h=480)
        frame = np.zeros((480, 640, 3), np.uint8)

        def run(**kwargs: object) -> None:
            process = kwargs["mod"]
            for _ in range(2):
                self.assertEqual(process(frame).shape, frame.shape)

        with (
            patch(
                "webcam_mods.mods.mp_face.FaceDetector", return_value=detector
            ) as detect,
            patch(
                "webcam_mods.mods.camera_motion.CropTracker", return_value=tracker
            ) as track,
            patch.object(entry, "live_loop", side_effect=run),
        ):
            result = CliRunner().invoke(
                entry.app,
                [
                    "--no-controls",
                    "--output-width",
                    "1280",
                    "--output-height",
                    "720",
                    "track-face",
                    "--face-height",
                    "0.35",
                    "--max-zoom",
                    "1.5",
                    "--target-x",
                    "0.45",
                    "--target-y",
                    "0.4",
                    "--lost-after",
                    "2",
                    "--pan-seconds",
                    "0.3",
                    "--zoom-seconds",
                    "0.8",
                ],
            )
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        options = track.call_args.kwargs
        self.assertAlmostEqual(options["aspect_ratio"], 16 / 9)
        for name, value in dict(
            face_height=0.35,
            max_zoom=1.5,
            target_x=0.45,
            target_y=0.4,
            lost_after=2,
            pan_seconds=0.3,
            zoom_seconds=0.8,
        ).items():
            self.assertEqual(options[name], value)
        detect.assert_called_once_with(lost_after=2)
        self.assertIsNone(tracker.generate_crop.call_args_list[1].args[0])
        self.assertEqual(
            tracker.generate_crop.call_args.kwargs["frame_size"], (640, 480)
        )
        self.assertEqual(
            detector.predict.call_args.kwargs["now"],
            tracker.generate_crop.call_args.kwargs["now"],
        )
        tracker.close.assert_called_once()
        detector.close.assert_called_once()

    def test_legacy_padding_fills_omitted_ratio(self) -> None:
        tracker = MagicMock()
        tracker.generate_crop.return_value = Rect(w=640, h=480)
        with (
            patch("webcam_mods.mods.mp_face.FaceDetector") as detect,
            patch("webcam_mods.mods.camera_motion.CropTracker", return_value=tracker),
            patch.object(
                entry,
                "live_loop",
                side_effect=lambda **kw: kw["mod"](np.zeros((480, 640, 3), np.uint8)),
            ),
        ):
            detect.return_value.predict.return_value = Rect(w=80, h=80)
            result = CliRunner().invoke(
                entry.app, ["--no-controls", "track-face", "--x-padding", "3"]
            )
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        self.assertEqual(tracker.generate_crop.call_args.args[1], (3, 2.5))

    def test_invalid_options_rejected_before_capture(self) -> None:
        for name, value in (
            ("max-zoom", "0.5"),
            ("face-height", "0"),
            ("target-y", "1.1"),
            ("pan-seconds", "0"),
            ("zoom-deadzone", "1"),
            ("lost-after", "-1"),
        ):
            with (
                self.subTest(name=name),
                patch.object(entry, "create_camera") as capture,
            ):
                result = CliRunner().invoke(
                    entry.app, ["track-face", "--" + name, value]
                )
                self.assertNotEqual(result.exit_code, 0)
                capture.assert_not_called()
