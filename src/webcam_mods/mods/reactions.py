"""Animated reactions set off by holding a hand gesture up to the camera."""

from collections.abc import Callable
from dataclasses import dataclass
import functools
import math
import os
import random
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from webcam_mods.mods.gestures import HandGestures
from webcam_mods.utils.video import Frame

# recognizer gestures and the reactions they set off
REACTIONS = {
    "Thumb_Up": "thumbs-up",
    "Thumb_Down": "thumbs-down",
    "Victory": "balloons",
    "ILoveYou": "hearts",
}
# thumbs up with both hands
CONFETTI = "confetti"
_GLYPHS = {
    "thumbs-up": "\N{THUMBS UP SIGN}",
    "thumbs-down": "\N{THUMBS DOWN SIGN}",
    "balloons": "\N{BALLOON}",
    "hearts": "\N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16}",
}
_DURATIONS = {
    "thumbs-up": 2.0,
    "thumbs-down": 2.0,
    "balloons": 3.2,
    "hearts": 3.2,
    CONFETTI: 3.0,
}
# a gesture fires once held this long, and again only after it is let go
HOLD_SECONDS = 0.4
# gestures are held, so a few looks a second catch them
DETECT_INTERVAL = 0.1
EMOJI_FONTS = (
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
)
# color bitmap fonts render only at their strike sizes
_EMOJI_SIZES = (160, 109)
# BGR
_CONFETTI_COLORS = (
    (60, 60, 230),
    (40, 210, 250),
    (90, 200, 80),
    (230, 140, 40),
    (180, 90, 240),
    (200, 80, 140),
)
_CONFETTI_PIECES = 180
# confetti fall acceleration as picture heights per second squared
_GRAVITY = 0.25


@dataclass(frozen=True)
class Sprite:
    """Premultiplied float BGR and 0..1 alpha."""

    color: NDArray[np.float32]
    alpha: NDArray[np.float32]


@functools.cache
def emoji_sprite(glyph: str) -> Sprite | None:
    """A color emoji from the first installed emoji font, or None without one."""
    for path in EMOJI_FONTS:
        if not os.path.isfile(path):
            continue
        for size in _EMOJI_SIZES:
            try:
                font = ImageFont.truetype(path, size)
            except OSError:
                continue
            image = Image.new("RGBA", (size * 2, size * 2))
            ImageDraw.Draw(image).text(
                (size // 2, size // 2), glyph, font=font, embedded_color=True
            )
            box = image.getbbox()
            if box is None:
                continue
            rgba = np.asarray(image.crop(box), np.float32)
            alpha = rgba[:, :, 3] / 255
            color = rgba[:, :, 2::-1] * alpha[:, :, None]
            return Sprite(np.ascontiguousarray(color), np.ascontiguousarray(alpha))
    return None


def reaction_for(gestures: list[str]) -> str | None:
    """The reaction for one frame's hand gestures; mixed gestures choose none."""
    if gestures.count("Thumb_Up") >= 2:
        return CONFETTI
    found = {REACTIONS[gesture] for gesture in gestures if gesture in REACTIONS}
    return found.pop() if len(found) == 1 else None


class GestureTrigger:
    """Fires a reaction once its gesture is held, then waits for a release."""

    def __init__(self, hold: float = HOLD_SECONDS) -> None:
        self._hold = hold
        self._current: str | None = None
        self._since = 0.0
        self._fired = False

    def observe(self, reaction: str | None, now: float) -> str | None:
        if reaction != self._current:
            self._current, self._since, self._fired = reaction, now, False
        if reaction is None or self._fired or now - self._since < self._hold:
            return None
        self._fired = True
        return reaction


@dataclass(frozen=True)
class _Rising:
    """Balloon or heart: start share of the width, delay and crossing seconds."""

    x: float
    delay: float
    rise: float
    size: float
    phase: float


@dataclass(frozen=True)
class _Piece:
    """Confetti: start position and fall speed in picture shares, spin in rad/s."""

    x: float
    y: float
    fall: float
    size: float
    phase: float
    spin: float
    color: tuple[int, int, int]


@dataclass(frozen=True)
class _Animation:
    reaction: str
    start: float
    sprite: Sprite | None
    rising: tuple[_Rising, ...] = ()
    pieces: tuple[_Piece, ...] = ()

    @property
    def duration(self) -> float:
        return _DURATIONS[self.reaction]


class GestureSource(Protocol):
    def detect(self, frame: Frame) -> list[str]: ...
    def close(self) -> None: ...


def _paste(
    frame: Frame, sprite: Sprite, x: float, y: float, size: float, opacity: float
) -> None:
    """Blend a sprite, size pixels tall and centered on x, y, into the frame."""
    height = max(1, round(size))
    width = max(1, round(size * sprite.alpha.shape[1] / sprite.alpha.shape[0]))
    left, top = round(x - width / 2), round(y - height / 2)
    frame_height, frame_width = frame.shape[:2]
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(frame_width, left + width), min(frame_height, top + height)
    if x0 >= x1 or y0 >= y1 or opacity <= 0:
        return
    inside = slice(y0 - top, y1 - top), slice(x0 - left, x1 - left)
    color = cv2.resize(sprite.color, (width, height), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(sprite.alpha, (width, height), interpolation=cv2.INTER_AREA)
    cover = alpha[inside][:, :, None] * opacity
    region = frame[y0:y1, x0:x1].astype(np.float32)
    region *= 1 - cover
    region += color[inside] * opacity
    frame[y0:y1, x0:x1] = cv2.convertScaleAbs(region)


def _ease_out_back(progress: float) -> float:
    overshoot = 1.70158
    step = progress - 1
    return 1 + (overshoot + 1) * step**3 + overshoot * step**2


class Reactions:
    """Watches the camera picture for held gestures and animates their reactions."""

    def __init__(
        self,
        gestures: GestureSource | None = None,
        *,
        on_warning: Callable[[str], None] | None = None,
        seed: int | None = None,
    ) -> None:
        self._gestures = gestures if gestures is not None else HandGestures()
        self._on_warning = on_warning
        self._trigger = GestureTrigger()
        self._random = random.Random(seed)
        self._playing: _Animation | None = None
        self._looked: float | None = None
        self._warned = False

    @property
    def playing(self) -> str | None:
        return None if self._playing is None else self._playing.reaction

    def detect(self, camera: Frame, now: float) -> None:
        """Look for gestures in the camera picture a few times a second."""
        if self._looked is not None and now - self._looked < DETECT_INTERVAL:
            return
        self._looked = now
        reaction = self._trigger.observe(
            reaction_for(self._gestures.detect(camera)), now
        )
        if reaction is not None:
            self.start(reaction, now)

    def start(self, reaction: str, now: float) -> bool:
        """Begin a reaction unless another one still plays."""
        playing = self._playing
        if playing is not None and now - playing.start < playing.duration:
            return False
        sprite = None if reaction == CONFETTI else emoji_sprite(_GLYPHS[reaction])
        if reaction != CONFETTI and sprite is None:
            if not self._warned and self._on_warning is not None:
                self._on_warning(
                    "Gesture reactions need a color emoji font; only two thumbs up"
                    " confetti can show"
                )
            self._warned = True
            return False
        rng = self._random
        rising: tuple[_Rising, ...] = ()
        pieces: tuple[_Piece, ...] = ()
        if reaction in ("balloons", "hearts"):
            large = reaction == "balloons"
            rising = tuple(
                _Rising(
                    x=rng.uniform(0.06, 0.94),
                    delay=rng.uniform(0, 1.0),
                    rise=rng.uniform(1.6, 2.2),
                    size=rng.uniform(0.1, 0.18) if large else rng.uniform(0.07, 0.13),
                    phase=rng.random(),
                )
                for _ in range(14)
            )
        elif reaction == CONFETTI:
            pieces = tuple(
                _Piece(
                    x=rng.random(),
                    y=rng.uniform(-0.6, -0.02),
                    fall=rng.uniform(0.3, 0.6),
                    size=rng.uniform(0.014, 0.026),
                    phase=rng.random(),
                    spin=rng.uniform(-8, 8),
                    color=rng.choice(_CONFETTI_COLORS),
                )
                for _ in range(_CONFETTI_PIECES)
            )
        self._playing = _Animation(reaction, now, sprite, rising, pieces)
        return True

    def draw(self, frame: Frame, now: float) -> Frame:
        """The frame with the playing reaction on top; unchanged when none plays."""
        playing = self._playing
        if playing is None:
            return frame
        elapsed = now - playing.start
        if elapsed >= playing.duration:
            self._playing = None
            return frame
        out = frame.copy()
        height, width = out.shape[:2]
        if playing.sprite is not None and not playing.rising:
            # a bubble pops in at the upper right, drifts up and fades
            size = 0.32 * height * (0.3 + 0.7 * _ease_out_back(min(1, elapsed / 0.3)))
            x = max(size / 2, min(0.8 * width, width - 0.6 * size))
            y = 0.32 * height - 0.04 * height * elapsed / playing.duration
            opacity = min(1.0, (playing.duration - elapsed) / 0.4)
            _paste(out, playing.sprite, x, y, size, opacity)
        for item in playing.rising:
            assert playing.sprite is not None
            progress = (elapsed - item.delay) / item.rise
            if not 0 <= progress <= 1:
                continue
            size = item.size * height
            x = (
                item.x + 0.03 * math.sin(2 * math.pi * (progress + item.phase))
            ) * width
            y = height + size / 2 - (height + size) * progress
            _paste(out, playing.sprite, x, y, size, 1.0)
        for piece in playing.pieces:
            y = (piece.y + piece.fall * elapsed + _GRAVITY * elapsed**2 / 2) * height
            size = piece.size * height
            if not -size < y < height + size:
                continue
            x = (
                piece.x + 0.02 * math.sin(2 * math.pi * (1.5 * elapsed + piece.phase))
            ) * width
            angle = piece.spin * elapsed + piece.phase * 2 * math.pi
            along = np.array([math.cos(angle), math.sin(angle)]) * size / 2
            across = np.array([-math.sin(angle), math.cos(angle)]) * size / 4
            center = np.array([x, y])
            corners = np.array(
                [
                    center - along - across,
                    center + along - across,
                    center + along + across,
                    center - along + across,
                ]
            )
            cv2.fillPoly(
                out, [np.round(corners).astype(np.int32)], piece.color, cv2.LINE_AA
            )
        return out

    def close(self) -> None:
        self._playing = None
        self._gestures.close()
