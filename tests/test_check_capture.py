"""Capture checks distinguish stable sessions, drift, and permission failures."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from scripts.check_capture import check_capture, main
from webcam_mods.macos.capture import AVFoundationCamera
from webcam_mods.input.video_dev import Webcam
from webcam_mods.settings import StartupSettings


def camera() -> Mock:
    source = Mock()
    source.setup.return_value = {"width": 1280, "height": 720, "fps": 30}
    source.frame.return_value = np.zeros((720, 1280, 3), np.uint8)
    source.is_setup.return_value = False
    return source


class CaptureCheckTests(unittest.TestCase):
    def test_stable_capture_restarts_and_checks_frames_after_pause(self) -> None:
        sources = [camera(), camera()]
        with (
            patch("scripts.check_capture.create_camera", side_effect=sources),
            patch("scripts.check_capture.time.sleep") as sleep,
        ):
            result = check_capture(
                StartupSettings(in_width=1280, in_height=720), frames=3, cycles=2
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual([run["frames"] for run in result["runs"]], [3, 3])
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(5)
        for source in sources:
            source.setup.assert_called_once()
            source.teardown.assert_called_once()

    def test_drift_after_pause_closes_camera_and_retains_partial_progress(self) -> None:
        source = camera()
        source.frame.side_effect = [
            np.zeros((720, 1280, 3), np.uint8),
            np.zeros((480, 864, 3), np.uint8),
        ]
        with (
            patch("scripts.check_capture.create_camera", return_value=source),
            patch("scripts.check_capture.time.sleep"),
        ):
            result = check_capture(
                StartupSettings(in_width=1280, in_height=720), frames=3
            )
        self.assertEqual(result["status"], "failed")
        self.assertIn("received 864x480", result["error"]["message"])
        self.assertEqual(result["runs"][0]["frames"], 1)
        source.teardown.assert_called_once()

    def test_permission_failure_is_blocked_and_closes_partial_setup(self) -> None:
        source = camera()
        source.setup.side_effect = PermissionError("camera access denied")
        with patch("scripts.check_capture.create_camera", return_value=source):
            result = check_capture(StartupSettings())
        self.assertEqual(result["status"], "blocked")
        source.teardown.assert_called_once()
        source.frame.assert_not_called()

    def test_unauthorized_camera_check_does_not_request_permission(self) -> None:
        import sys
        from types import SimpleNamespace

        device = Mock()
        device.authorizationStatusForMediaType_.return_value = 0
        av = SimpleNamespace(
            AVCaptureDevice=device,
            AVMediaTypeVideo="video",
            AVAuthorizationStatusAuthorized=3,
        )
        for source in (AVFoundationCamera(), Webcam()):
            with (
                self.subTest(adapter=type(source).__name__),
                patch("scripts.check_capture.sys.platform", "darwin"),
                patch.dict(sys.modules, {"AVFoundation": av}),
                patch("scripts.check_capture.create_camera", return_value=source),
                patch.object(source, "setup") as setup,
            ):
                result = check_capture(StartupSettings())
            self.assertEqual(result["status"], "blocked")
            setup.assert_not_called()
        device.requestAccessForMediaType_completionHandler_.assert_not_called()

    def test_cleanup_failure_does_not_report_success(self) -> None:
        source = camera()
        source.teardown.side_effect = TimeoutError("still stopping")
        with (
            patch("scripts.check_capture.create_camera", return_value=source),
            patch("scripts.check_capture.time.sleep"),
        ):
            result = check_capture(
                StartupSettings(in_width=1280, in_height=720), frames=2, cycles=1
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["type"], "TimeoutError")

    def test_invalid_workload_fails_before_acquisition(self) -> None:
        with patch("scripts.check_capture.create_camera") as factory:
            for options in (
                {"frames": 1},
                {"cycles": 0},
                {"startup_pause": float("nan")},
                {"startup_pause": -1},
            ):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    check_capture(StartupSettings(), **options)
            factory.assert_not_called()

    def test_cli_writes_report_and_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "check.json"
            with patch(
                "scripts.check_capture.check_capture",
                return_value={"status": "blocked"},
            ):
                self.assertEqual(main(["--report", str(path)]), 1)
            self.assertEqual(json.loads(path.read_text())["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
