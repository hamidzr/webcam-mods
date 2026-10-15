"""Exposure, focus and anti-flicker set on the camera itself while a profile runs."""

from collections.abc import Callable
import math
import struct
import sys
import threading
from typing import Any, Protocol

from webcam_mods.profiles import ANTI_FLICKER, Profile

# CoreMediaIO control classes and properties
_CLASSES = {"exposure": "xpsr", "focus": "fcus", "anti_flicker": "pwfq"}
_AUTO, _VALUE, _RANGE = "fcam", "fcnv", "fcnr"
# UVC power line frequency values
FLICKER = {name: value for value, name in enumerate(ANTI_FLICKER)}
_FLICKER_NAMES = {value: name for name, value in FLICKER.items()} | {3: "auto"}


class ControlBackend(Protocol):
    def controls(self, device_uid: str) -> dict[str, int]: ...
    def read(self, target: int, selector: str) -> bytes | None: ...
    def write(self, target: int, selector: str, data: bytes) -> bool: ...


def wanted(profile: Profile) -> dict[str, int | str | None]:
    return {
        "exposure": profile.camera_exposure,
        "focus": profile.camera_focus,
        "anti_flicker": profile.anti_flicker,
    }


def _native(name: str, percent: int, low: float, high: float) -> float:
    # exposure times double per stop, so the slider moves through them evenly
    if name == "exposure":
        return float(round(low - 1 + (high - low + 1) ** (percent / 100)))
    return float(round(low + (high - low) * percent / 100))


def _percent(name: str, value: float, low: float, high: float) -> int:
    if name == "exposure":
        share = math.log(max(1.0, value - low + 1)) / math.log(high - low + 1)
    else:
        share = (value - low) / (high - low)
    return round(min(1.0, max(0.0, share)) * 100)


class CameraControls:
    """Applies a profile's hardware settings and puts the camera back on close."""

    def __init__(
        self,
        device_uid: str | None,
        profile: Profile,
        *,
        on_warning: Callable[[str], None] | None = None,
        backend: ControlBackend | None = None,
    ) -> None:
        self._device_uid = device_uid
        self._profile = profile
        self._on_warning = on_warning
        self._lock = threading.Lock()
        self._started = self._closed = False
        # original auto mode and value of each control this session changed
        self._saved: dict[str, tuple[int | None, float]] = {}
        self._backend = backend
        # found on first use, so profiles without hardware settings never look
        self._controls: dict[str, int] | None = None
        self._unavailable: str | None = None

    def _find(self) -> dict[str, int]:
        if self._controls is not None:
            return self._controls
        self._controls = {}
        if self._device_uid is None:
            self._unavailable = "choose a camera to set its exposure, focus or flicker"
        elif self._backend is None and sys.platform != "darwin":
            self._unavailable = "camera exposure, focus and flicker need macOS"
        else:
            try:
                if self._backend is None:
                    from webcam_mods.macos.cmio import CoreMediaIO

                    self._backend = CoreMediaIO()
                found = self._backend.controls(self._device_uid)
            except OSError as error:
                self._unavailable = f"camera settings are unavailable: {error}"
            else:
                self._controls = {
                    name: found[code]
                    for name, code in _CLASSES.items()
                    if code in found and self._usable(name, found[code])
                }
        return self._controls

    def describe(self) -> dict[str, Any]:
        """Supported controls with the camera's current state, as profile values."""
        with self._lock:
            described: dict[str, Any] = {}
            for name, control in self._find().items():
                value = self._value(control)
                if name == "anti_flicker":
                    described[name] = _FLICKER_NAMES.get(round(value or 0), "other")
                    continue
                low, high = self._range(control) or (0.0, 1.0)
                described[name] = {
                    "auto": self._auto(control) == 1,
                    "value": _percent(name, value or low, low, high),
                }
            return described

    def start(self) -> None:
        """Apply the profile once frames flow, after capture opened the camera."""
        with self._lock:
            if self._closed or self._started:
                return
            self._started = True
            self._apply(wanted(self._profile), {})

    def update(self, profile: Profile) -> None:
        with self._lock:
            previous, self._profile = wanted(self._profile), profile
            if self._started and not self._closed:
                self._apply(wanted(profile), previous)

    def close(self) -> None:
        """Put back every control this session changed."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for name in list(self._saved):
                self._restore(name)

    def _apply(
        self, settings: dict[str, int | str | None], previous: dict[str, Any]
    ) -> None:
        for name, value in settings.items():
            if name in previous and previous[name] == value:
                continue
            if value is None:
                self._restore(name)
                continue
            label = name.replace("_", "-")
            control = self._find().get(name)
            if self._unavailable is not None:
                self._warn(f"Camera {label} not set: {self._unavailable}")
                continue
            if control is None:
                self._warn(f"This camera has no adjustable {label}")
                continue
            if name not in self._saved:
                # anti-flicker has no automatic mode to switch
                auto = None if name == "anti_flicker" else self._auto(control)
                self._saved[name] = (auto, self._value(control) or 0.0)
            if name == "anti_flicker":
                assert isinstance(value, str)
                applied = self._write_value(control, FLICKER[value])
            else:
                assert isinstance(value, int)
                low, high = self._range(control) or (0.0, 0.0)
                applied = self._write_auto(control, 0) and self._write_value(
                    control, _native(name, value, low, high)
                )
            if not applied:
                self._warn(f"The camera did not accept the {label} setting")

    def _restore(self, name: str) -> None:
        saved = self._saved.pop(name, None)
        if saved is None:
            return
        control = self._find()[name]
        auto, value = saved
        if auto == 1:
            restored = self._write_auto(control, 1)
        else:
            restored = (auto is None or self._write_auto(control, 0)) and (
                self._write_value(control, value)
            )
        if not restored:
            self._warn(f"Could not put back the camera's {name.replace('_', '-')}")

    def _usable(self, name: str, control: int) -> bool:
        if self._value(control) is None:
            return False
        if name == "anti_flicker":
            return True
        # manual exposure and focus need auto switching and a value range
        return self._auto(control) is not None and self._range(control) is not None

    def _auto(self, control: int) -> int | None:
        assert self._backend is not None
        data = self._backend.read(control, _AUTO)
        return None if data is None or len(data) != 4 else struct.unpack("=I", data)[0]

    def _value(self, control: int) -> float | None:
        assert self._backend is not None
        data = self._backend.read(control, _VALUE)
        return None if data is None or len(data) != 4 else struct.unpack("=f", data)[0]

    def _range(self, control: int) -> tuple[float, float] | None:
        assert self._backend is not None
        data = self._backend.read(control, _RANGE)
        if data is None or len(data) != 16:
            return None
        low, high = struct.unpack("=2d", data)
        return (low, high) if math.isfinite(low) and low < high < 1e9 else None

    def _write_auto(self, control: int, auto: int) -> bool:
        assert self._backend is not None
        return self._backend.write(control, _AUTO, struct.pack("=I", auto))

    def _write_value(self, control: int, value: float) -> bool:
        assert self._backend is not None
        return self._backend.write(control, _VALUE, struct.pack("=f", value))

    def _warn(self, message: str) -> None:
        if self._on_warning is not None:
            self._on_warning(message)
