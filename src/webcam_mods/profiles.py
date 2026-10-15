"""Validated, local SQLite profiles shared by CLI and native controls."""

from dataclasses import asdict, dataclass, fields, replace
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Iterator

# fields that shape capture or output; changing them needs a session restart
RESTART_FIELDS = frozenset(
    {
        "input_device",
        "camera_id",
        "width",
        "height",
        "fps",
        "capture",
        "output_width",
        "output_height",
        "output_fps",
        "repeat_frames",
        "processing_fps",
        "signal_pattern",
        "rotate",
    }
)


NUMBER_RANGES: tuple[tuple[str, float, float], ...] = (
    ("track_face_height", 0.1, 0.9),
    ("track_target_y", 0.2, 0.8),
    ("track_max_zoom", 1, 4),
    ("track_follow_seconds", 0.05, 3),
    ("track_deadzone", 0, 0.4),
    ("exposure", -2, 2),
)


@dataclass(frozen=True)
class Profile:
    input_device: int = 0
    width: int = 640
    height: int = 480
    fps: float = 30
    effect: str = "plain"
    brightness: int = 0
    blur_kernel: int = 31
    color: int = 192
    image_path: str = ""
    image_blur: bool = False
    # spotlight background: percent darker background and percent lifted person
    spotlight_dim: int = 60
    spotlight_lift: int = 20
    track: bool = False
    segmentation: str = "mediapipe"
    processing: str = "opencv"
    capture: str = "auto"
    repeat_frames: bool = True
    processing_fps: float = 30
    smoothing: bool = False
    signal_pattern: str = "color-bars"
    mirror: bool = False
    flip_vertical: bool = False
    # clockwise camera rotation in degrees; quarter turns swap default output size
    rotate: int = 0
    # manual crop as [x, y, width, height] fractions of the oriented camera frame
    crop: tuple[float, float, float, float] | None = None
    # auto-framing: face height and head center as output fractions, zoom limit,
    # follow time constant in seconds, and ignored drift as a crop fraction
    track_face_height: float = 0.4
    track_target_y: float = 0.42
    track_max_zoom: float = 2.0
    track_follow_seconds: float = 0.25
    track_deadzone: float = 0.08
    # color after background and brightness: exposure in stops, sharpness 0..100,
    # the rest -100..100 with 0 unchanged
    exposure: float = 0.0
    contrast: int = 0
    saturation: int = 0
    temperature: int = 0
    tint: int = 0
    sharpness: int = 0
    # lifts dark pictures toward a target brightness over about a second, 0 off
    auto_light: int = 0
    camera_id: str | None = None
    output_width: int | None = None
    output_height: int | None = None
    output_fps: float | None = None

    def __post_init__(self) -> None:
        for key, lower, upper in (
            ("input_device", 0, 255),
            ("width", 16, 8192),
            ("height", 16, 8192),
            ("brightness", 0, 255),
            ("color", 0, 255),
            ("blur_kernel", 1, 511),
            ("contrast", -100, 100),
            ("saturation", -100, 100),
            ("temperature", -100, 100),
            ("tint", -100, 100),
            ("sharpness", 0, 100),
            ("auto_light", 0, 100),
            ("spotlight_dim", 0, 100),
            ("spotlight_lift", 0, 100),
        ):
            value = getattr(self, key)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{key} must be an integer in {lower}..{upper}")
        for key in ("output_width", "output_height"):
            value = getattr(self, key)
            if value is not None and (
                type(value) is not int or not 16 <= value <= 8192
            ):
                raise ValueError(f"{key} must be an integer in 16..8192 or null")
        if self.camera_id is not None and (
            not isinstance(self.camera_id, str)
            or not self.camera_id.strip()
            or len(self.camera_id) > 4096
            or any(ord(character) < 32 for character in self.camera_id)
        ):
            raise ValueError("camera_id must be a nonempty identity string or null")
        if self.crop is not None:
            # JSON lists become tuples so profiles stay hashable and comparable
            object.__setattr__(self, "crop", _crop(self.crop))
        if self.blur_kernel % 2 == 0:
            raise ValueError("blur_kernel must be odd")
        if type(self.rotate) is not int or self.rotate not in (0, 90, 180, 270):
            raise ValueError("rotate must be 0, 90, 180 or 270")
        for key in ("fps", "processing_fps", "output_fps"):
            value = getattr(self, key)
            if key == "output_fps" and value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 1 <= value <= 240
                or not math.isfinite(value)
            ):
                raise ValueError(f"{key} must be finite in 1..240")
        for key, low, high in NUMBER_RANGES:
            value = getattr(self, key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"{key} must be a number in {low}..{high}")
        for key in (
            "track",
            "repeat_frames",
            "smoothing",
            "image_blur",
            "mirror",
            "flip_vertical",
        ):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be a boolean")
        for key, choices in (
            ("signal_pattern", ("color-bars", "noise")),
            ("effect", ("plain", "blur", "color", "image", "spotlight", "track")),
            ("segmentation", ("mediapipe", "vision")),
            ("processing", ("opencv", "coreimage")),
            ("capture", ("auto", "opencv", "avfoundation")),
        ):
            if getattr(self, key) not in choices:
                raise ValueError(f"invalid {key}")
        if not isinstance(self.image_path, str) or len(self.image_path) > 4096:
            raise ValueError("image_path must be a path string")
        if self.effect == "image" and not self.image_path:
            raise ValueError("image effect requires image_path")

    @property
    def oriented_size(self) -> tuple[int, int]:
        """Capture width and height after rotation."""
        if self.rotate in (90, 270):
            return self.height, self.width
        return self.width, self.height

    @classmethod
    def parse(cls, config: object) -> "Profile":
        if not isinstance(config, dict) or any(not isinstance(k, str) for k in config):
            raise ValueError("config must be an object")
        unknown = set(config) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
        return cls(**config)


def _crop(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("crop must be [x, y, width, height] or null")
    numbers = []
    for number in value:
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise ValueError("crop values must be finite numbers")
        numbers.append(float(number))
    x, y, width, height = numbers
    if (
        not 0.02 <= width <= 1
        or not 0.02 <= height <= 1
        or x < 0
        or y < 0
        or x + width > 1.0001
        or y + height > 1.0001
    ):
        raise ValueError("crop must be fractions inside the frame, at least 0.02 wide")
    return x, y, width, height


MAX_STORED_CONFIG_BYTES = 65536


def _stored_profile(config: object) -> Profile:
    if not isinstance(config, str):
        raise ValueError("invalid profile JSON")
    if (
        len(config) > MAX_STORED_CONFIG_BYTES
        or len(config.encode("utf-8")) > MAX_STORED_CONFIG_BYTES
    ):
        raise ValueError("profile config exceeds 64 KiB limit")
    try:
        parsed = json.loads(config)
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid profile JSON") from error
    try:
        return Profile.parse(parsed)
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid profile settings") from error


def validate_name(name: object) -> str:
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 80
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("profile name must contain 1..80 printable characters")
    return name.strip()


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        config_root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.path = path or config_root / "webcam_mods" / "profiles.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            schema = db.execute("PRAGMA user_version").fetchone()[0]
            if schema not in (0, 1):
                raise RuntimeError("unsupported profiles database schema")
            db.execute(
                "CREATE TABLE IF NOT EXISTS profiles (name TEXT PRIMARY KEY, config TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, name: object, config: object) -> None:
        name = validate_name(name)
        profile = Profile.parse(config)
        if profile.image_path:
            profile = replace(
                profile, image_path=str(Path(profile.image_path).expanduser().resolve())
            )
        with self._connect() as db:
            db.execute(
                "INSERT INTO profiles VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET config=excluded.config",
                (name, json.dumps(asdict(profile))),
            )

    def seed_defaults(self) -> None:
        """Add starter profiles once; preserve edits, collisions and deletions."""
        base = Profile(capture="avfoundation" if sys.platform == "darwin" else "auto")
        defaults = {
            "Natural": base,
            "Soft Background Blur": replace(base, effect="blur"),
            "Auto Framing": replace(base, track=True),
            "Blur + Auto Framing": replace(base, effect="blur", track=True),
            "Studio Gray": replace(base, effect="color", color=192),
        }
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS profile_seeds (name TEXT PRIMARY KEY)"
            )
            if not db.execute(
                "INSERT OR IGNORE INTO profile_seeds VALUES ('desktop-v1')"
            ).rowcount:
                return
            db.executemany(
                "INSERT OR IGNORE INTO profiles VALUES (?, ?)",
                [
                    (name, json.dumps(asdict(profile)))
                    for name, profile in defaults.items()
                ],
            )

    def list_with_errors(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        profiles: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        with self._connect() as db:
            for name, config in db.execute(
                "SELECT name, config FROM profiles ORDER BY name"
            ):
                try:
                    profile = _stored_profile(config)
                except ValueError as error:
                    errors.append({"name": name, "error": str(error)})
                    continue
                profiles.append({"name": name, "config": asdict(profile)})
        return profiles, errors

    def errors(self) -> list[dict[str, str]]:
        return self.list_with_errors()[1]

    def list(self) -> list[dict[str, Any]]:
        return self.list_with_errors()[0]

    def export(self, name: object, path: Path, *, overwrite: bool = False) -> None:
        """Write validated config atomically, preserving existing files by default."""
        payload = json.dumps(asdict(self.get(name)), indent=2, allow_nan=False) + "\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                # hard link publishes the complete file with exclusive-create semantics
                os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get(self, name: object) -> Profile:
        with self._connect() as db:
            row = db.execute(
                "SELECT config FROM profiles WHERE name=?", (validate_name(name),)
            ).fetchone()
        if row is None:
            raise ValueError("profile not found")
        return _stored_profile(row[0])

    def delete(self, name: object) -> None:
        with self._connect() as db:
            if not db.execute(
                "DELETE FROM profiles WHERE name=?", (validate_name(name),)
            ).rowcount:
                raise ValueError("profile not found")
