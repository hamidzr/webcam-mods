"""Logo watermark and name caption composited onto frames from cached layers."""

import functools
import math
import os
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from webcam_mods.utils.video import Frame

Position = Literal["top-left", "top-right", "bottom-left", "bottom-right"]
POSITIONS: tuple[Position, ...] = get_args(Position)

MAX_CAPTION_LENGTH = 80
MIN_LOGO_SCALE, MAX_LOGO_SCALE = 5, 60
MAX_LOGO_SIDE = 8192
MAX_CACHED_SIZES = 4

MARGIN_RATIO = 0.03
NAME_HEIGHT_RATIO = 0.055
DETAIL_HEIGHT_RATIO = 0.038
MIN_FONT_PX = 10
PANEL_ALPHA = 0.6
DETAIL_TEXT_LEVEL = 220
PANEL_SUPERSAMPLE = 4

FONT_CANDIDATES = (
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont
FloatPlane = NDArray[np.floating[Any]]


@dataclass(frozen=True)
class OverlaySettings:
    logo_path: str = ""
    logo_position: Position = "top-right"
    # logo width as a percent of the frame width
    logo_scale: int = 15
    logo_opacity: int = 100
    caption: str = ""
    caption_detail: str = ""
    caption_position: Position = "bottom-left"

    def __post_init__(self) -> None:
        for name in ("logo_position", "caption_position"):
            if getattr(self, name) not in POSITIONS:
                raise ValueError(f"{name} must be one of {', '.join(POSITIONS)}")
        for name in ("logo_path", "caption", "caption_detail"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        _check_int("logo_scale", self.logo_scale, MIN_LOGO_SCALE, MAX_LOGO_SCALE)
        _check_int("logo_opacity", self.logo_opacity, 0, 100)
        for name in ("caption", "caption_detail"):
            text = getattr(self, name)
            if len(text) > MAX_CAPTION_LENGTH:
                raise ValueError(f"{name} must be at most {MAX_CAPTION_LENGTH} chars")
            if has_control_characters(text):
                raise ValueError(f"{name} must not contain control characters")

    def is_empty(self) -> bool:
        return not self.logo_path and not self.caption.strip()


def has_control_characters(text: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in text)


def _check_int(name: str, value: object, low: int, high: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not low <= value <= high
    ):
        raise ValueError(f"{name} must be an integer in {low}..{high}")


@dataclass(frozen=True)
class Patch:
    """Premultiplied BGR pixels plus inverse alpha for one frame region."""

    x: int
    y: int
    color: Frame
    inverse: Frame

    @property
    def width(self) -> int:
        return int(self.color.shape[1])

    @property
    def height(self) -> int:
        return int(self.color.shape[0])


@dataclass(frozen=True)
class OverlayLayer:
    width: int
    height: int
    patches: tuple[Patch, ...]


@dataclass(frozen=True)
class Logo:
    """Premultiplied float BGR and alpha planes at source resolution."""

    color: FloatPlane
    alpha: FloatPlane


@dataclass
class _Source:
    settings: OverlaySettings
    logo: Logo | None = None
    layers: dict[tuple[int, int], OverlayLayer] = field(default_factory=dict)


class Overlay:
    """Composite cached overlay layers onto frames of any size."""

    def __init__(
        self, settings: OverlaySettings | None = None, logo: Logo | None = None
    ) -> None:
        self._source = _Source(OverlaySettings())
        if settings is not None:
            self.configure(settings, logo)

    @property
    def settings(self) -> OverlaySettings:
        return self._source.settings

    def configure(self, settings: OverlaySettings, logo: Logo | None = None) -> None:
        """Use new settings; a preloaded logo for settings.logo_path skips the read."""
        # load first so a bad image keeps the previous overlay
        if logo is None and settings.logo_path:
            logo = load_logo(settings.logo_path)
        self._source = _Source(settings, logo if settings.logo_path else None)

    def layer_for(self, width: int, height: int) -> OverlayLayer:
        return _layer_for(self._source, width, height)

    def __call__(self, frame: Frame) -> Frame:
        height, width = frame.shape[:2]
        layer = _layer_for(self._source, width, height)
        if not layer.patches:
            return frame
        out = frame.copy()
        for patch in layer.patches:
            region = out[
                patch.y : patch.y + patch.height, patch.x : patch.x + patch.width
            ]
            cv2.multiply(region, patch.inverse, dst=region, scale=1 / 255)
            cv2.add(region, patch.color, dst=region)
        return out


def _layer_for(source: _Source, width: int, height: int) -> OverlayLayer:
    key = (width, height)
    layer = source.layers.get(key)
    if layer is None:
        layer = _build_layer(source.settings, source.logo, width, height)
        if len(source.layers) >= MAX_CACHED_SIZES:
            source.layers.pop(next(iter(source.layers)))
        source.layers[key] = layer
    return layer


def load_logo(path: str) -> Logo:
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED) if os.path.isfile(path) else None
    if image is None or image.ndim not in (2, 3) or image.size == 0:
        raise ValueError(f"cannot read image: {path}")
    if max(image.shape[:2]) > MAX_LOGO_SIDE:
        raise ValueError(f"image larger than {MAX_LOGO_SIDE}px per side: {path}")
    if image.dtype == np.uint16:
        image = (image / 257).round().astype(np.uint8)
    if image.dtype != np.uint8:
        raise ValueError(f"unsupported image depth: {path}")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    channels = image.shape[2]
    if channels == 4:
        alpha = image[:, :, 3].astype(np.float32) / 255
        bgr = image[:, :, :3]
    elif channels == 3:
        alpha = np.ones(image.shape[:2], np.float32)
        bgr = image
    else:
        raise ValueError(f"unsupported channel count: {path}")
    # premultiply so resizing does not bleed color from transparent pixels
    color = bgr.astype(np.float32) * alpha[:, :, None]
    return Logo(color, alpha)


def _build_layer(
    settings: OverlaySettings, logo: Logo | None, width: int, height: int
) -> OverlayLayer:
    margin = max(1, round(MARGIN_RATIO * min(width, height)))
    gap = max(1, margin // 2)
    patches: list[Patch] = []
    # extra offset pushing the caption inward when the logo shares its corner
    stacked = 0

    if logo is not None and settings.logo_opacity > 0:
        rendered = _render_logo(logo, settings, width, height, margin)
        patch = _place(rendered, settings.logo_position, margin, 0, width, height)
        if patch is not None:
            patches.append(patch)
            if settings.caption_position == settings.logo_position:
                stacked = patch.height + gap

    if settings.caption.strip():
        panel = _render_caption(
            settings.caption, settings.caption_detail, width, height, margin
        )
        patch = _place(panel, settings.caption_position, margin, stacked, width, height)
        if patch is not None:
            patches.append(patch)

    return OverlayLayer(width, height, tuple(patches))


def _render_logo(
    logo: Logo, settings: OverlaySettings, width: int, height: int, margin: int
) -> tuple[FloatPlane, FloatPlane]:
    src_h, src_w = logo.alpha.shape
    target_w = max(1, round(width * settings.logo_scale / 100))
    target_h = max(1, round(target_w * src_h / src_w))
    # keep tall logos inside the frame
    fit = min(1.0, (width - 2 * margin) / target_w, (height - 2 * margin) / target_h)
    target_w, target_h = max(1, int(target_w * fit)), max(1, int(target_h * fit))
    interp = cv2.INTER_AREA if target_w <= src_w else cv2.INTER_LINEAR
    size = (target_w, target_h)
    color = cv2.resize(logo.color, size, interpolation=interp)
    alpha = cv2.resize(logo.alpha, size, interpolation=interp)
    opacity = settings.logo_opacity / 100
    return color * opacity, alpha * opacity


def _place(
    rendered: tuple[FloatPlane, FloatPlane],
    position: Position,
    margin: int,
    inward: int,
    frame_w: int,
    frame_h: int,
) -> Patch | None:
    """Quantize float planes into a patch anchored at a corner, clipped to the frame."""
    color, alpha = rendered
    h, w = alpha.shape
    x = margin if position.endswith("left") else frame_w - margin - w
    y = margin + inward if position.startswith("top") else frame_h - margin - inward - h
    # clip to the frame
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame_w, x + w), min(frame_h, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    window = (slice(y0 - y, y1 - y), slice(x0 - x, x1 - x))
    color, alpha = color[window], alpha[window]
    if not alpha.any():
        return None
    premult = np.clip(np.rint(color), 0, 255).astype(np.uint8)
    inverse = (255 - np.clip(np.rint(alpha * 255), 0, 255)).astype(np.uint8)
    return Patch(
        x0,
        y0,
        np.ascontiguousarray(premult),
        np.ascontiguousarray(np.repeat(inverse[:, :, None], 3, axis=2)),
    )


@functools.cache
def _font_path() -> str | None:
    return next((path for path in FONT_CANDIDATES if os.path.isfile(path)), None)


@functools.cache
def _font(size: int) -> Font:
    path = _font_path()
    if path is not None:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _line_metrics(font: Font) -> tuple[int, int]:
    if isinstance(font, ImageFont.FreeTypeFont):
        return font.getmetrics()
    return font.getbbox("Ag")[3], 0


def _ellipsize(text: str, font: Font, room: float) -> str:
    if font.getlength(text) <= room:
        return text
    while text and font.getlength(text + "...") > room:
        text = text[:-1]
    return text.rstrip() + "..."


def _render_caption(
    caption: str, detail: str, frame_w: int, frame_h: int, margin: int
) -> tuple[FloatPlane, FloatPlane]:
    """Render a lower-third panel as premultiplied float color and alpha planes."""
    detail = detail if detail.strip() else ""
    name_px = max(MIN_FONT_PX, round(NAME_HEIGHT_RATIO * frame_h))
    detail_px = max(MIN_FONT_PX, round(DETAIL_HEIGHT_RATIO * frame_h))

    def pad_x(px: int) -> int:
        return round(px * 0.6)

    # shrink fonts until the widest line fits between the margins
    while True:
        name_font, detail_font = _font(name_px), _font(detail_px)
        text_w = max(
            name_font.getlength(caption), detail_font.getlength(detail) if detail else 0
        )
        room = frame_w - 2 * margin - 2 * pad_x(name_px)
        if text_w <= room or name_px <= MIN_FONT_PX:
            break
        shrink = min(room / text_w, 0.95)
        name_px = max(MIN_FONT_PX, int(name_px * shrink))
        detail_px = max(MIN_FONT_PX, int(detail_px * shrink))

    # still too wide at the smallest font: trim with an ellipsis
    caption = _ellipsize(caption, name_font, room)
    detail = _ellipsize(detail, detail_font, room) if detail else ""
    text_w = max(
        name_font.getlength(caption), detail_font.getlength(detail) if detail else 0
    )

    px, py = pad_x(name_px), round(name_px * 0.4)
    name_ascent, name_descent = _line_metrics(name_font)
    detail_ascent, detail_descent = _line_metrics(detail_font)
    line_gap = round(name_px * 0.1)
    panel_w = math.ceil(text_w) + 2 * px
    panel_h = 2 * py + name_ascent + name_descent
    if detail:
        panel_h += line_gap + detail_ascent + detail_descent

    text = Image.new("L", (panel_w, panel_h), 0)
    draw = ImageDraw.Draw(text)
    baseline = py + name_ascent
    draw.text((px, baseline), caption, font=name_font, fill=255, anchor="ls")
    if detail:
        baseline += name_descent + line_gap + detail_ascent
        draw.text(
            (px, baseline),
            detail,
            font=detail_font,
            fill=DETAIL_TEXT_LEVEL,
            anchor="ls",
        )

    # supersample the rounded rectangle for smooth corners
    big = PANEL_SUPERSAMPLE
    panel = Image.new("L", (panel_w * big, panel_h * big), 0)
    ImageDraw.Draw(panel).rounded_rectangle(
        (0, 0, panel_w * big - 1, panel_h * big - 1),
        radius=round(name_px * 0.35) * big,
        fill=round(PANEL_ALPHA * 255),
    )
    panel = panel.reduce(big)

    text_cover = np.asarray(text, dtype=np.float32) / 255
    panel_alpha = np.asarray(panel, dtype=np.float32) / 255
    # white text over a black panel: premultiplied color is the text coverage
    alpha = text_cover + panel_alpha * (1 - text_cover)
    color = np.repeat((text_cover * 255)[:, :, None], 3, axis=2)
    return color, alpha
