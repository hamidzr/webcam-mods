import importlib
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

import cv2

from webcam_mods.geometry import Point
from webcam_mods.uses.track_box import Simulation
from webcam_mods.uses.track_face import main


class LegacyDemoTests(unittest.TestCase):
    def test_imports_do_not_start_runtime_or_load_models(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, threading; "
                "import webcam_mods.uses.track_face; "
                "import webcam_mods.uses.track_box; "
                "assert 'webcam_mods.entry' not in sys.modules; "
                "assert 'mediapipe' not in sys.modules; "
                "assert 'pynput' not in sys.modules; "
                "assert len(threading.enumerate()) == 1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with patch("cv2.namedWindow") as window:
            importlib.reload(sys.modules["webcam_mods.uses.track_box"])
        window.assert_not_called()

    def test_face_demo_delegates_to_supported_cli(self):
        entry = types.ModuleType("webcam_mods.entry")
        entry.app = Mock()
        with patch.dict(sys.modules, {"webcam_mods.entry": entry}):
            main(["--help"])
        entry.app.assert_called_once_with(
            args=["track-face", "--help"],
            prog_name="python -m webcam_mods.uses.track_face",
        )

    def test_simulation_state_is_independent(self):
        first = Simulation()
        second = Simulation()
        first.click_handler(cv2.EVENT_LBUTTONDOWN, 250, 200, 0, None)
        prediction = first.generate_prediction()
        self.assertEqual(prediction.center, Point(t=200, l=250))
        self.assertEqual(prediction.w, 100)
        self.assertEqual(second.generate_prediction().w, 150)
        self.assertEqual(second.clicked, Point())
        first.tracker.generate_crop(prediction, padding=None)
        self.assertIsNone(second.tracker.cur_crop)

    def test_simulation_uses_tracker_and_cleans_up_on_quit(self):
        simulation = Simulation()
        with (
            patch.object(simulation, "visualize") as visualize,
            patch.object(
                simulation.tracker, "close", wraps=simulation.tracker.close
            ) as close,
            patch("cv2.waitKey", return_value=ord("q")),
            patch("cv2.destroyAllWindows") as destroy,
        ):
            simulation.run()
        crop = visualize.call_args.kwargs["crop"]
        self.assertEqual((crop.w, crop.h), (300, 375))
        close.assert_called_once()
        destroy.assert_called_once()
        self.assertIsNone(simulation.tracker.cur_crop)


if __name__ == "__main__":
    unittest.main()
