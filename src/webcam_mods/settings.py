"""Immutable startup settings, resolved explicitly before resources are opened."""

from dataclasses import dataclass, fields
import math
import os
from typing import Any
from collections.abc import Mapping


@dataclass(frozen=True)
class StartupSettings:
    in_width: int = 640
    in_height: int = 480
    in_format: str = "YUYV"
    in_fps: float = 30
    video_in: int = 0
    video_out: str = "/dev/video10"
    out_width: int = 640
    out_height: int = 480
    max_out_fps: float = 30
    on_demand: bool = False
    pan_control: bool = True
    padding_control: bool = True

    def __post_init__(self) -> None:
        for name in ("in_width", "in_height", "out_width", "out_height"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name.upper()} must be a positive integer")
        if type(self.video_in) is not int or self.video_in < 0:
            raise ValueError("VIDEO_IN must be a nonnegative integer")
        for name in ("in_fps", "max_out_fps"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name.upper()} must be finite and positive")
        if not isinstance(self.in_format, str) or len(self.in_format) != 4:
            raise ValueError("IN_FORMAT must contain exactly four characters")
        if not isinstance(self.video_out, str) or not self.video_out:
            raise ValueError("VIDEO_OUT must not be empty")
        for name in ("on_demand", "pan_control", "padding_control"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name.upper()} must be a boolean")


def load_settings(
    environ: Mapping[str, str] | None = None, **overrides: object
) -> StartupSettings:
    """Resolve explicit overrides > existing environment names > defaults."""
    env = os.environ if environ is None else environ
    defaults = StartupSettings()
    names = {field.name for field in fields(defaults)}
    unknown = overrides.keys() - names
    if unknown:
        raise ValueError(f"unknown startup settings: {', '.join(sorted(unknown))}")
    # field names and value types are validated by the dataclass constructor
    values: dict[str, Any] = {}
    for name in names:
        value = overrides.get(name)
        if value is None:
            raw = env.get(name.upper())
            default = getattr(defaults, name)
            if raw is None:
                value = default
            else:
                try:
                    if isinstance(default, bool):
                        if raw.lower() not in ("true", "false", "1", "0"):
                            raise ValueError("expected true/false or 1/0")
                        value = raw.lower() in ("true", "1")
                    elif name in ("in_fps", "max_out_fps"):
                        value = float(raw)
                    else:
                        value = type(default)(raw)
                except ValueError as error:
                    raise ValueError(f"invalid {name.upper()}: {error}") from error
        values[name] = value
    return StartupSettings(**values)
