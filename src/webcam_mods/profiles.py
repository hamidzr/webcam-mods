"""Validated, local SQLite profiles shared by CLI and native controls."""

from dataclasses import asdict, dataclass, fields, replace
from contextlib import contextmanager
import json
import math
import numbers
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unicodedata
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
        "source",
        "screen_region",
        "presenter",
    }
)


# keep in step with mods/looks.py BUILTIN_LOOKS; custom reads look_path
LOOKS = ("none", "warm", "cool", "mono", "fade", "vivid", "film", "custom")

# overlay corners and caption length; keep in step with mods/overlay.py
OVERLAY_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
MAX_CAPTION_LENGTH = 80

# camera power line filtering; mapped to UVC values in camera_controls.py
ANTI_FLICKER = ("off", "50hz", "60hz")

NUMBER_RANGES: tuple[tuple[str, float, float], ...] = (
    ("track_face_height", 0.1, 0.9),
    ("track_target_y", 0.2, 0.8),
    ("track_max_zoom", 1, 4),
    ("track_follow_seconds", 0.05, 3),
    ("track_deadzone", 0, 0.4),
    ("exposure", -2, 2),
    ("image_x", 0, 1),
    ("image_y", 0, 1),
)

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")

Point = tuple[float, float]
# (x, y) fractions in 0..1: top-left, top-right, bottom-right, bottom-left
Quad = tuple[Point, Point, Point, Point]
MIN_QUAD_AREA = 0.01


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
    # solid background as #RRGGBB; when absent the gray level above applies
    background_color: str | None = None
    image_path: str = ""
    image_blur: bool = False
    # image backgrounds fill the picture; this point of the image stays in view,
    # as fractions from the left and top
    image_x: float = 0.5
    image_y: float = 0.5
    # spotlight background: percent darker background and percent lifted person
    spotlight_dim: int = 60
    spotlight_lift: int = 20
    track: bool = False
    segmentation: str = "mediapipe"
    # chroma segmentation keys this backdrop color; tolerance and softness widen
    # the keyed range and its edge, spill removes the color reflected onto you
    key_color: str = "#00B140"
    key_tolerance: int = 40
    key_softness: int = 30
    key_spill: int = 50
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
    # desk view: corners of a desk, whiteboard or page seen at an angle, as
    # fractions of the oriented camera frame; the area is straightened to fill the
    # picture and replaces crop and face tracking
    perspective: Quad | None = None
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
    # smooths skin while eyes, brows and lips stay sharp, 0 off
    touchup: int = 0
    # averages camera noise over frames where nothing moves, 0 off
    denoise: int = 0
    # experimental: slides both irises up so eyes on the screen meet a camera
    # above it, 0 off
    eye_contact: int = 0
    # holding thumbs up or down, a peace sign or an I-love-you sign to the camera
    # sets off an animation over the picture; two thumbs up throw confetti
    reactions: bool = False
    # set on the camera itself while the profile runs and put back after: exposure
    # time and focus as percents of the camera's range, and mains flicker
    # filtering; null leaves the camera's own, usually automatic, setting
    camera_exposure: int | None = None
    camera_focus: int | None = None
    anti_flicker: str | None = None
    # final color grade: a built-in look or a .cube LUT file, blended by strength
    look: str = "none"
    look_path: str = ""
    look_strength: int = 100
    # drawn last: a logo or watermark picture, its width a percent of the picture,
    # and a name caption with an optional second line, each in a corner
    logo_path: str = ""
    logo_position: str = "top-right"
    logo_scale: int = 15
    logo_opacity: int = 100
    caption: str = ""
    caption_detail: str = ""
    caption_position: str = "bottom-left"
    # camera, or a screen area as [left, top, width, height] in global screen points
    # from the main display's top-left corner; crop then picks part of it
    source: str = "camera"
    screen_region: tuple[int, int, int, int] | None = None
    # with a screen source, show the camera over it as a round bubble or a person
    # cutout in a corner, sized as a percent of the picture height; orientation and
    # color settings then apply to the camera, never the screen
    presenter: bool = False
    presenter_style: str = "bubble"
    presenter_position: str = "bottom-right"
    presenter_size: int = 30
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
            ("touchup", 0, 100),
            ("denoise", 0, 100),
            ("eye_contact", 0, 100),
            ("spotlight_dim", 0, 100),
            ("spotlight_lift", 0, 100),
            ("look_strength", 0, 100),
            ("key_tolerance", 0, 100),
            ("key_softness", 0, 100),
            ("key_spill", 0, 100),
            ("logo_scale", 5, 60),
            ("logo_opacity", 0, 100),
            ("presenter_size", 10, 80),
        ):
            value = getattr(self, key)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{key} must be an integer in {lower}..{upper}")
        for key in ("camera_exposure", "camera_focus"):
            value = getattr(self, key)
            if value is not None and (type(value) is not int or not 0 <= value <= 100):
                raise ValueError(f"{key} must be an integer in 0..100 or null")
        if self.anti_flicker is not None and self.anti_flicker not in ANTI_FLICKER:
            raise ValueError("anti_flicker must be off, 50hz, 60hz or null")
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
        if self.screen_region is not None:
            object.__setattr__(
                self, "screen_region", _screen_region(self.screen_region)
            )
        if self.perspective is not None:
            object.__setattr__(self, "perspective", validate_quad(self.perspective))
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
            "presenter",
            "reactions",
        ):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be a boolean")
        for key, choices in (
            ("signal_pattern", ("color-bars", "noise")),
            ("effect", ("plain", "blur", "color", "image", "spotlight", "track")),
            ("segmentation", ("mediapipe", "vision", "chroma")),
            ("processing", ("opencv", "coreimage")),
            ("capture", ("auto", "opencv", "avfoundation")),
            ("look", LOOKS),
            ("logo_position", OVERLAY_POSITIONS),
            ("caption_position", OVERLAY_POSITIONS),
            ("source", ("camera", "screen")),
            ("presenter_style", ("bubble", "cutout")),
            ("presenter_position", OVERLAY_POSITIONS),
        ):
            if getattr(self, key) not in choices:
                raise ValueError(f"invalid {key}")
        if self.source == "screen" and self.screen_region is None:
            raise ValueError("screen source requires screen_region")
        if self.background_color is not None:
            if not isinstance(self.background_color, str) or not _HEX_COLOR.fullmatch(
                self.background_color
            ):
                raise ValueError("background_color must be #RRGGBB or null")
            object.__setattr__(self, "background_color", self.background_color.upper())
        if not isinstance(self.key_color, str) or not _HEX_COLOR.fullmatch(
            self.key_color
        ):
            raise ValueError("key_color must be #RRGGBB")
        object.__setattr__(self, "key_color", self.key_color.upper())
        if not isinstance(self.image_path, str) or len(self.image_path) > 4096:
            raise ValueError("image_path must be a path string")
        if self.effect == "image" and not self.image_path:
            raise ValueError("image effect requires image_path")
        if not isinstance(self.look_path, str) or len(self.look_path) > 4096:
            raise ValueError("look_path must be a path string")
        if self.look == "custom" and not self.look_path:
            raise ValueError("custom look requires look_path")
        if not isinstance(self.logo_path, str) or len(self.logo_path) > 4096:
            raise ValueError("logo_path must be a path string")
        for key in ("caption", "caption_detail"):
            text = getattr(self, key)
            if (
                not isinstance(text, str)
                or len(text) > MAX_CAPTION_LENGTH
                or any(unicodedata.category(character) == "Cc" for character in text)
            ):
                raise ValueError(
                    f"{key} must be one line of at most {MAX_CAPTION_LENGTH} characters"
                )

    @property
    def background_bgr(self) -> tuple[int, int, int]:
        """Solid background color as OpenCV BGR."""
        if self.background_color is None:
            return self.color, self.color, self.color
        return _bgr(self.background_color)

    @property
    def key_bgr(self) -> tuple[int, int, int]:
        """Green screen key color as OpenCV BGR."""
        return _bgr(self.key_color)

    @property
    def capture_size(self) -> tuple[int, int]:
        """Captured frame width and height: the camera's, or the screen area's."""
        if self.source == "screen" and self.screen_region is not None:
            return self.screen_region[2], self.screen_region[3]
        return self.width, self.height

    @property
    def presenting(self) -> bool:
        """Screen shared with the camera over it."""
        return self.source == "screen" and self.presenter

    @property
    def oriented_size(self) -> tuple[int, int]:
        """Capture width and height after rotation, which turns cameras only."""
        width, height = self.capture_size
        if self.rotate in (90, 270) and self.source == "camera":
            return height, width
        return width, height

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


def validate_quad(quad: object) -> Quad:
    """Return a clean quad or raise ValueError; accepts nested lists from JSON."""
    if not isinstance(quad, (list, tuple)) or len(quad) != 4:
        raise ValueError("perspective must be 4 [x, y] corners or null")
    points: list[Point] = []
    for raw in quad:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError("perspective must be 4 [x, y] corners or null")
        coords: list[float] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ValueError("perspective corners must be numbers in 0..1")
            coord = float(value)
            if not math.isfinite(coord) or not 0 <= coord <= 1:
                raise ValueError("perspective corners must be numbers in 0..1")
            coords.append(coord)
        points.append((coords[0], coords[1]))
    # clockwise on screen (y down) means every turn has a positive cross product
    for i in range(4):
        (ax, ay), (bx, by), (cx, cy) = (
            points[i],
            points[(i + 1) % 4],
            points[(i + 2) % 4],
        )
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) <= 1e-9:
            raise ValueError(
                "perspective must be a convex area, corners clockwise from top-left"
            )
    area = sum(
        ax * by - bx * ay for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1])
    )
    if area / 2 <= MIN_QUAD_AREA:
        raise ValueError("perspective must cover more than 1% of the frame")
    return points[0], points[1], points[2], points[3]


def _screen_region(value: object) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(item) is not int for item in value)
        or not all(-65536 <= item <= 65536 for item in value[:2])
        or not all(16 <= item <= 8192 for item in value[2:])
    ):
        raise ValueError(
            "screen_region must be [left, top, width, height] in screen points,"
            " at least 16 wide and high"
        )
    left, top, width, height = value
    return left, top, width, height


def _bgr(color: str) -> tuple[int, int, int]:
    value = int(color[1:], 16)
    return value & 255, (value >> 8) & 255, value >> 16


def _absolute(path: str) -> str:
    return str(Path(path).expanduser().resolve())


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
            profile = replace(profile, image_path=_absolute(profile.image_path))
        if profile.look_path:
            profile = replace(profile, look_path=_absolute(profile.look_path))
        if profile.logo_path:
            profile = replace(profile, logo_path=_absolute(profile.logo_path))
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
