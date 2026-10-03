"""Read lid and camera state without opening devices or requesting permission."""

import plistlib
import subprocess
import sys
from typing import Any

# IOKit/audio/IOAudioTypes.h: kIOAudioDeviceTransportTypeBuiltIn
BUILT_IN_TRANSPORT = int.from_bytes(b"bltn", "big")


def lid_closed() -> bool | None:
    """Return unknown when hardware or OS does not expose a lid switch."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-r", "-c", "IOPMrootDomain", "-a"],
            capture_output=True,
            check=True,
            timeout=2,
        )
        entries = plistlib.loads(result.stdout)
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    state = entry.get("AppleClamshellState")
                    if isinstance(state, bool):
                        return state
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        plistlib.InvalidFileException,
    ):
        pass
    return None


def camera_unavailable_reason(device: Any, closed: bool | None) -> str | None:
    """Apply lid closure only to built-in devices; retain external cameras."""
    if closed is True and device.transportType() == BUILT_IN_TRANSPORT:
        return "laptop lid closed; open lid or choose an external camera"
    if device.isConnected() is False:
        return "camera disconnected; reconnect it or choose another camera"
    if device.isSuspended() is True:
        return "camera suspended; open lid/privacy shutter or choose another camera"
    return None
