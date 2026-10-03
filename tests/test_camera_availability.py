"""Lid checks must fail safely and never disable external cameras."""

import plistlib
import subprocess
import unittest
from unittest.mock import Mock, patch

from webcam_mods.macos.availability import (
    BUILT_IN_TRANSPORT,
    camera_unavailable_reason,
    lid_closed,
)


class AvailabilityTests(unittest.TestCase):
    def test_lid_states_and_missing_property(self) -> None:
        for state in (True, False, None, "Yes"):
            with (
                self.subTest(state=state),
                patch("webcam_mods.macos.availability.sys.platform", "darwin"),
                patch("webcam_mods.macos.availability.subprocess.run") as run,
            ):
                entry = {} if state is None else {"AppleClamshellState": state}
                run.return_value.stdout = plistlib.dumps([entry])
                self.assertIs(lid_closed(), state if isinstance(state, bool) else None)
                self.assertEqual(run.call_args.kwargs["timeout"], 2)

    def test_failed_or_malformed_query_is_unknown(self) -> None:
        for failure in (OSError(), subprocess.TimeoutExpired("ioreg", 2)):
            with (
                patch("webcam_mods.macos.availability.sys.platform", "darwin"),
                patch(
                    "webcam_mods.macos.availability.subprocess.run", side_effect=failure
                ),
            ):
                self.assertIsNone(lid_closed())
        with (
            patch("webcam_mods.macos.availability.sys.platform", "darwin"),
            patch("webcam_mods.macos.availability.subprocess.run") as run,
        ):
            run.return_value.stdout = b"invalid plist"
            self.assertIsNone(lid_closed())

    def test_non_macos_skips_query(self) -> None:
        with (
            patch("webcam_mods.macos.availability.sys.platform", "linux"),
            patch("webcam_mods.macos.availability.subprocess.run") as run,
        ):
            self.assertIsNone(lid_closed())
            run.assert_not_called()

    def test_lid_only_excludes_builtin_camera(self) -> None:
        device = Mock()
        device.isConnected.return_value = True
        device.isSuspended.return_value = False
        device.transportType.return_value = BUILT_IN_TRANSPORT
        self.assertIn("lid closed", camera_unavailable_reason(device, True) or "")
        for state in (False, None):
            self.assertIsNone(camera_unavailable_reason(device, state))
        device.transportType.return_value = int.from_bytes(b"usb ", "big")
        self.assertIsNone(camera_unavailable_reason(device, True))
        device.isSuspended.return_value = True
        self.assertIn("suspended", camera_unavailable_reason(device, True) or "")
        device.isConnected.return_value = False
        self.assertIn("disconnected", camera_unavailable_reason(device, True) or "")
