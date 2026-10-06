"""Validated, local SQLite profiles shared by CLI and native controls."""

from dataclasses import asdict, dataclass, fields, replace
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator


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
    track: bool = False
    segmentation: str = "mediapipe"
    processing: str = "opencv"
    capture: str = "auto"
    repeat_frames: bool = True
    processing_fps: float = 30
    smoothing: bool = False

    def __post_init__(self) -> None:
        for key, lower, upper in (
            ("input_device", 0, 255),
            ("width", 16, 8192),
            ("height", 16, 8192),
            ("brightness", 0, 255),
            ("color", 0, 255),
            ("blur_kernel", 1, 511),
        ):
            value = getattr(self, key)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{key} must be an integer in {lower}..{upper}")
        if self.blur_kernel % 2 == 0:
            raise ValueError("blur_kernel must be odd")
        for key in ("fps", "processing_fps"):
            value = getattr(self, key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 1 <= value <= 240
            ):
                raise ValueError(f"{key} must be finite in 1..240")
        for key in ("track", "repeat_frames", "smoothing"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be a boolean")
        for key, choices in (
            ("effect", ("plain", "blur", "color", "image", "track")),
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

    @classmethod
    def parse(cls, config: object) -> "Profile":
        if not isinstance(config, dict) or any(not isinstance(k, str) for k in config):
            raise ValueError("config must be an object")
        unknown = set(config) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
        return cls(**config)


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

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [
                {"name": name, "config": asdict(Profile.parse(json.loads(config)))}
                for name, config in db.execute(
                    "SELECT name, config FROM profiles ORDER BY name"
                )
            ]

    def get(self, name: object) -> Profile:
        with self._connect() as db:
            row = db.execute(
                "SELECT config FROM profiles WHERE name=?", (validate_name(name),)
            ).fetchone()
        if row is None:
            raise ValueError("profile not found")
        return Profile.parse(json.loads(row[0]))

    def delete(self, name: object) -> None:
        with self._connect() as db:
            if not db.execute(
                "DELETE FROM profiles WHERE name=?", (validate_name(name),)
            ).rowcount:
                raise ValueError("profile not found")
