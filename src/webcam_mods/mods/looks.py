"""Color looks (filters) applied to BGR frames through 3D LUTs."""

from functools import cache
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame, validate_frame

MAX_CUBE_BYTES = 16 * 1024 * 1024
MAX_CUBE_SIZE = 65
BUILTIN_LOOKS: tuple[str, ...] = ("warm", "cool", "mono", "fade", "vivid", "film")

Table = NDArray[np.float32]

_DENSE = 128  # 7 bits per channel
_BUILTIN_GRID = 33

# per-channel bucket index (v >> 1) pre-shifted into a flat [b7, g7, r7] index
_BUCKETS = np.arange(256, dtype=np.int32) >> 1
_INDEX_LUT = np.stack([_BUCKETS << 14, _BUCKETS << 7, _BUCKETS], axis=1)[:, None, :]
_INDEX_SUM = np.ones((1, 3), np.float32)


def _lerp_axis(table: Table, axis: int, positions: NDArray[np.float64]) -> Table:
    """Linearly resample `table` along `axis` at fractional grid `positions`."""
    last = table.shape[axis] - 1
    low = positions.astype(np.intp)
    np.minimum(low, last - 1, out=low)
    frac = (positions - low).astype(np.float32)
    shape = [1] * table.ndim
    shape[axis] = -1
    a = np.take(table, low, axis=axis)
    b = np.take(table, low + 1, axis=axis)
    lerped: Table = a + (b - a) * frac.reshape(shape)
    return lerped


def _parse_floats(parts: list[str], count: int) -> NDArray[np.float64]:
    """Parse the `count` values after a header keyword."""
    name = parts[0].upper()
    if len(parts) != count + 1:
        raise ValueError(f"{name} needs {count} values")
    try:
        values = np.array([float(p) for p in parts[1:]], np.float64)
    except ValueError:
        raise ValueError(f"{name} has a non-numeric value") from None
    if not np.isfinite(values).all():
        raise ValueError(f"{name} has a non-finite value")
    return values


def parse_cube(text: str) -> Table:
    """Parse an Adobe/Resolve .cube 3D LUT into an (N, N, N, 3) RGB table indexed [b, g, r].

    Values are not clamped. A non-default domain is resampled so the table
    always covers the 0..1 input range.
    """
    size = 0
    domain_min = np.zeros(3, np.float64)
    domain_max = np.ones(3, np.float64)
    rows: list[tuple[float, float, float]] = []
    for raw in text.splitlines():
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        key = parts[0].upper()
        if key == "TITLE":
            continue
        if key == "LUT_1D_SIZE":
            raise ValueError("1D LUTs are not supported")
        if key == "LUT_3D_SIZE":
            try:
                size = int(parts[1]) if len(parts) == 2 else 0
            except ValueError:
                size = 0
            if not 2 <= size <= MAX_CUBE_SIZE:
                raise ValueError(f"LUT_3D_SIZE must be 2..{MAX_CUBE_SIZE}")
        elif key == "DOMAIN_MIN":
            domain_min = _parse_floats(parts, 3)
        elif key == "DOMAIN_MAX":
            domain_max = _parse_floats(parts, 3)
        elif key == "LUT_3D_INPUT_RANGE":
            low, high = _parse_floats(parts, 2)
            domain_min, domain_max = np.full(3, low), np.full(3, high)
        else:
            try:
                row = tuple(float(p) for p in parts)
            except ValueError:
                raise ValueError(f"unsupported line: {raw.strip()[:30]!r}") from None
            if len(row) != 3:
                raise ValueError("data rows need 3 values")
            if not size:
                raise ValueError("LUT_3D_SIZE must precede data rows")
            if len(rows) == size**3:
                raise ValueError(f"too many data rows, expected {size**3}")
            rows.append((row[0], row[1], row[2]))
    if not size:
        raise ValueError("missing LUT_3D_SIZE")
    if len(rows) != size**3:
        raise ValueError(f"expected {size**3} data rows, got {len(rows)}")
    if not (domain_max > domain_min).all():
        raise ValueError("DOMAIN_MAX must exceed DOMAIN_MIN")
    data = np.array(rows, np.float64)
    if not np.isfinite(data).all():
        raise ValueError("data contains non-finite values")
    # file order is red fastest, so a plain reshape yields [b, g, r]
    table = data.astype(np.float32).reshape(size, size, size, 3)
    if (domain_min != 0).any() or (domain_max != 1).any():
        grid = np.arange(size) / (size - 1)
        for axis in range(3):
            lo, hi = domain_min[2 - axis], domain_max[2 - axis]
            positions = np.clip((grid - lo) / (hi - lo), 0.0, 1.0) * (size - 1)
            table = _lerp_axis(table, axis, positions)
    return table


def load_cube(path: str | Path) -> "ColorLook":
    """Read a .cube file (size limited) into a look; raises ValueError on bad content."""
    with open(path, "rb") as handle:
        data = handle.read(MAX_CUBE_BYTES + 1)
    if len(data) > MAX_CUBE_BYTES:
        raise ValueError("cube file too large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("cube file is not utf-8") from None
    return ColorLook(parse_cube(text))


def _dense_table(table: Table) -> NDArray[np.uint8]:
    """Expand to a flat (128**3, 3) BGR table sampled at 7-bit bucket centers."""
    last = table.shape[0] - 1
    # bucket q covers inputs 2q and 2q+1, so its center is 2q + 0.5
    positions = (np.arange(_DENSE) * 2 + 0.5) / 255 * last
    dense = table
    for axis in range(3):
        dense = _lerp_axis(dense, axis, positions)
    levels = np.clip(dense, 0.0, 1.0) * np.float32(255) + np.float32(0.5)
    bgr: NDArray[np.uint8] = levels.astype(np.uint8)[..., ::-1]
    return np.ascontiguousarray(bgr).reshape(-1, 3)


class ColorLook:
    """Apply a 3D LUT to BGR frames through a precomputed 7-bit table."""

    def __init__(self, table: Table) -> None:
        """`table` is (N, N, N, 3) RGB floats in 0..1 indexed [b, g, r]."""
        table = np.asarray(table, np.float32)
        n = table.shape[0] if table.ndim == 4 else 0
        if table.shape != (n, n, n, 3) or not 2 <= n <= MAX_CUBE_SIZE:
            raise ValueError(
                f"expected an (N, N, N, 3) table with N in 2..{MAX_CUBE_SIZE}"
            )
        if not np.isfinite(table).all():
            raise ValueError("table contains non-finite values")
        self._dense = _dense_table(table)

    def __call__(self, frame: Frame, strength: float = 1.0) -> Frame:
        """Return the looked frame; strength 0 returns `frame` itself, 1 the full look."""
        validate_frame(frame)
        if not strength > 0.0:
            return frame
        # summed per-channel shifted buckets give the flat [b7, g7, r7] index
        index = cv2.transform(cv2.LUT(frame, _INDEX_LUT), _INDEX_SUM)
        looked: Frame = np.take(self._dense, index.astype(np.intp, copy=False), axis=0)
        if strength >= 1.0:
            return looked
        return cast(Frame, cv2.addWeighted(frame, 1.0 - strength, looked, strength, 0))


def _smooth(x: NDArray[np.float32], amount: float) -> NDArray[np.float32]:
    """Blend toward smoothstep for a gentle S-curve."""
    return x + (x * x * (3.0 - 2.0 * x) - x) * np.float32(amount)


def _luma(rgb: Table) -> Table:
    """Rec.601 luma, keeping a trailing axis of 1."""
    weights = np.array([0.299, 0.587, 0.114], np.float32)
    return (rgb * weights).sum(axis=-1, keepdims=True)


def _saturate(rgb: Table, amount: float) -> Table:
    gray = _luma(rgb)
    return gray + (rgb - gray) * np.float32(amount)


def _tint(rgb: Table, gain: tuple[float, ...], midtone: tuple[float, ...]) -> Table:
    """Per-channel gain plus an offset weighted toward midtones (rgb order)."""
    luma = _luma(rgb)
    weight = 4.0 * luma * (1.0 - luma)
    tinted: Table = rgb * np.array(gain, np.float32)
    tinted += weight * np.array(midtone, np.float32)
    return tinted


def _builtin_function(name: str, rgb: Table) -> Table:
    if name == "warm":
        return _tint(rgb, (1.02, 1.0, 0.97), (0.025, 0.01, -0.025))
    if name == "cool":
        return _tint(rgb, (0.97, 1.0, 1.03), (-0.025, -0.005, 0.03))
    if name == "mono":
        return np.repeat(_smooth(_luma(rgb), 0.6), 3, axis=-1)
    if name == "fade":
        return _saturate(0.08 + rgb * 0.86, 0.85)
    if name == "vivid":
        return _smooth(np.clip(_saturate(rgb, 1.35), 0.0, 1.0), 0.5)
    if name == "film":
        luma = _luma(rgb)
        shadows = (1.0 - luma) ** 2 * np.array([-0.015, 0.01, 0.02], np.float32)
        highlights = luma**2 * np.array([0.03, 0.01, -0.025], np.float32)
        toned = _smooth(_saturate(rgb, 0.95), 0.4) + shadows + highlights
        return 0.02 + toned * 0.97
    raise ValueError(
        f"unknown look {name!r}, expected one of {', '.join(BUILTIN_LOOKS)}"
    )


@cache
def builtin_look(name: str) -> ColorLook:
    """Return the shared built-in look `name`, building its table on first use."""
    axis = np.linspace(0.0, 1.0, _BUILTIN_GRID, dtype=np.float32)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    rgb = np.stack([r, g, b], axis=-1)
    return ColorLook(np.clip(_builtin_function(name, rgb), 0.0, 1.0))
