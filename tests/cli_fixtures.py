"""Synthetic camera discovery for CLI tests unrelated to camera selection."""

import unittest
from unittest.mock import patch

from webcam_mods.macos.capture import CameraInfo


class HeadlessCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch(
                "webcam_mods.macos.capture.camera_inventory",
                return_value=[CameraInfo(0, "Test camera", ())],
            )
        )
        self.enterContext(
            patch(
                "webcam_mods.input.selection._interactive_terminal", return_value=False
            )
        )
        # native capture construction maps real device identities even before setup
        self.enterContext(
            patch("webcam_mods.capture.resolve_backend", return_value="opencv")
        )
