"""Exposure, contrast, white balance, saturation, sharpness and auto light adjustments."""

from dataclasses import dataclass
import math
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame, validate_frame

# temperature t and tint m (both -100..100) scale the BGR channels as
#   b = 1 - 0.3 * t / 100, g = 1 - 0.2 * m / 100, r = 1 + 0.3 * t / 100
_TEMPERATURE_SWING = 0.3
_TINT_SWING = 0.2

_MID_GRAY = 128.0
_MAX_SHARPEN = 1.5
_SHARPEN_SIGMA = 1.2

_LEVELS = np.arange(256, dtype=np.float64)


def _check_int(name: str, value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int in {low}..{high}, got {value!r}")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in {low}..{high}, got {value}")
    return value


def _check_float(name: str, value: object, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in {low}..{high}, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be finite and in {low}..{high}, got {value}")
    return number


@dataclass(frozen=True)
class ColorSettings:
    exposure: float = 0.0  # ev stops, gain = 2**exposure
    contrast: int = 0  # around mid gray
    saturation: int = 0  # -100 grayscale, +100 doubles chroma
    temperature: int = 0  # positive warmer
    tint: int = 0  # positive magenta, negative green
    sharpness: int = 0  # unsharp mask amount

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exposure", _check_float("exposure", self.exposure, -2.0, 2.0)
        )
        _check_int("contrast", self.contrast, -100, 100)
        _check_int("saturation", self.saturation, -100, 100)
        _check_int("temperature", self.temperature, -100, 100)
        _check_int("tint", self.tint, -100, 100)
        _check_int("sharpness", self.sharpness, 0, 100)

    def is_identity(self) -> bool:
        return self == ColorSettings()


def _balance_gains(temperature: int, tint: int) -> tuple[float, float, float]:
    """BGR channel gains for a temperature and tint pair."""
    warm = _TEMPERATURE_SWING * temperature / 100
    return 1 - warm, 1 - _TINT_SWING * tint / 100, 1 + warm


@dataclass(frozen=True)
class _Plan:
    settings: ColorSettings
    lut: NDArray[np.uint8] | None
    saturation: float
    sharpness: float


def _compile(settings: ColorSettings) -> _Plan:
    lut = None
    if (
        settings.exposure != 0
        or settings.contrast != 0
        or settings.temperature != 0
        or settings.tint != 0
    ):
        gains = np.array(_balance_gains(settings.temperature, settings.tint))
        gains *= 2.0**settings.exposure
        contrast = 1 + settings.contrast / 100
        curves = (_LEVELS[:, None] * gains[None, :] - _MID_GRAY) * contrast + _MID_GRAY
        # cv2.LUT takes a 1x256x3 table for 3 channel input
        lut = np.rint(np.clip(curves, 0, 255)).astype(np.uint8)[None]
    return _Plan(
        settings,
        lut,
        1 + settings.saturation / 100,
        _MAX_SHARPEN * settings.sharpness / 100,
    )


class ColorAdjuster:
    """Apply ColorSettings; rebuild lookup tables only when settings change."""

    def __init__(self, settings: ColorSettings | None = None) -> None:
        self._plan = _compile(settings or ColorSettings())

    def configure(self, settings: ColorSettings) -> None:
        if settings != self._plan.settings:
            # single reference swap keeps concurrent frames on a consistent plan
            self._plan = _compile(settings)

    def __call__(self, frame: Frame) -> Frame:
        validate_frame(frame)
        plan = self._plan
        if plan.settings.is_identity():
            return frame
        out = frame
        if plan.lut is not None:
            out = cast(Frame, cv2.LUT(out, plan.lut))
        if plan.saturation != 1:
            gray = cv2.cvtColor(
                cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR
            )
            out = cast(
                Frame,
                cv2.addWeighted(out, plan.saturation, gray, 1 - plan.saturation, 0),
            )
        if plan.sharpness > 0:
            blurred = cv2.GaussianBlur(out, (0, 0), _SHARPEN_SIGMA)
            out = cast(
                Frame,
                cv2.addWeighted(out, 1 + plan.sharpness, blurred, -plan.sharpness, 0),
            )
        return out


def neutral_balance(sample: Frame) -> tuple[int, int]:
    """Return (temperature, tint) that make the sample's average color neutral gray with ColorAdjuster."""
    validate_frame(sample)
    blue, green, red, _ = cv2.mean(sample)
    # invert the gains in _balance_gains: equalize r and b first, then match g
    total = blue + red
    warm = (blue - red) / (_TEMPERATURE_SWING * total) if total > 0 else 0.0
    temperature = max(-100, min(100, round(100 * warm)))
    gain_b, _, gain_r = _balance_gains(temperature, 0)
    if green <= 0:
        return temperature, 0
    green_gain = (blue * gain_b + red * gain_r) / 2 / green
    tint = round(100 * (1 - green_gain) / _TINT_SWING)
    return temperature, max(-100, min(100, tint))


_LUMA_BGR = (0.114, 0.587, 0.299)
_SAMPLE_WIDTH = 64
# below this the lift is under one level at mid tones, skip the pass
_MIN_APPLIED_GAIN = 1.005


class AutoLight:
    """Gradually lift dark frames toward a target brightness; protects highlights."""

    def __init__(
        self,
        strength: int = 50,
        *,
        target: float = 0.45,
        seconds: float = 1.0,
        max_gain: float = 3.0,
    ) -> None:
        self._strength = _check_int("strength", strength, 0, 100)
        self._target = _check_float("target", target, 0.0, 1.0)
        if not 0 < self._target < 1:
            raise ValueError(f"target must be between 0 and 1 exclusive, got {target}")
        self._seconds = _check_float("seconds", seconds, 0.0, math.inf)
        if self._seconds <= 0:
            raise ValueError(f"seconds must be positive, got {seconds}")
        self._max_gain = _check_float("max_gain", max_gain, 1.0, 100.0)
        self._gain: float | None = None
        self._last: float | None = None

    def configure(self, strength: int) -> None:
        self._strength = _check_int("strength", strength, 0, 100)
        if self._strength == 0:
            self.reset()

    def reset(self) -> None:
        self._gain = None
        self._last = None

    def __call__(self, frame: Frame, now: float) -> Frame:
        validate_frame(frame)
        if not math.isfinite(now):
            raise ValueError(f"now must be finite, got {now}")
        if self._strength == 0:
            return frame
        desired = self._desired_gain(frame)
        if self._gain is None or self._last is None:
            gain = desired
        else:
            dt = max(0.0, now - self._last)
            gain = self._gain + (desired - self._gain) * (
                1 - math.exp(-dt / self._seconds)
            )
        self._gain, self._last = gain, now
        if gain < _MIN_APPLIED_GAIN:
            return frame
        return cast(Frame, cv2.LUT(frame, self._lut(gain)))

    def _desired_gain(self, frame: Frame) -> float:
        height, width = frame.shape[:2]
        if width > _SAMPLE_WIDTH:
            height = max(1, round(height * _SAMPLE_WIDTH / width))
            frame = cast(
                Frame,
                cv2.resize(
                    frame, (_SAMPLE_WIDTH, height), interpolation=cv2.INTER_AREA
                ),
            )
        blue, green, red, _ = cv2.mean(frame)
        luma = _LUMA_BGR[0] * blue + _LUMA_BGR[1] * green + _LUMA_BGR[2] * red
        wanted = min(self._max_gain, max(1.0, self._target * 255 / max(luma, 1e-3)))
        return 1 + (wanted - 1) * self._strength / 100

    def _lut(self, gain: float) -> NDArray[np.uint8]:
        # straight gain up to the pivot (the level that lands on target), then a
        # hyperbolic shoulder that is slope-continuous and ends exactly at 255,
        # so highlights roll off instead of clipping and 255 never moves
        target = self._target
        pivot = target / gain
        span = 1 - pivot
        shoulder = (gain * span / (1 - target) - 1) / span
        x = _LEVELS / 255
        above = np.maximum(x - pivot, 0.0)
        curve = np.where(
            x <= pivot,
            gain * x,
            target + gain * above / (1 + shoulder * above),
        )
        lut = np.rint(np.clip(curve * 255, 0, 255))
        return cast(NDArray[np.uint8], np.maximum(lut, _LEVELS).astype(np.uint8))
