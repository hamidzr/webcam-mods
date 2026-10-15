"""Keystone correction: warp a chosen quadrilateral to an upright rectangle."""

from dataclasses import dataclass, field
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.profiles import Quad, validate_quad
from webcam_mods.utils.video import Frame

MAX_CACHED_SIZES = 4


@dataclass(frozen=True)
class _Transform:
    matrix: NDArray[np.float64]
    size: tuple[int, int]


@dataclass
class _State:
    quad: Quad
    transforms: dict[tuple[int, int], _Transform] = field(default_factory=dict)


class PerspectiveView:
    """Warp a chosen quadrilateral to an upright rectangle; caches the transform."""

    def __init__(self, quad: Quad) -> None:
        self._state = _State(validate_quad(quad))

    def configure(self, quad: Quad) -> None:
        # one swap so a concurrent frame never mixes an old quad with a new cache
        self._state = _State(validate_quad(quad))

    def output_size(self, frame_width: int, frame_height: int) -> tuple[int, int]:
        """Quad aspect from mean edge lengths, scaled to fit within the frame; even dims."""
        return _output_size(self._state.quad, frame_width, frame_height)

    def __call__(self, frame: Frame) -> Frame:
        height, width = frame.shape[:2]
        transform = self._transform(self._state, width, height)
        return cast(
            Frame,
            cv2.warpPerspective(
                frame,
                transform.matrix,
                transform.size,
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            ),
        )

    def _transform(self, state: _State, width: int, height: int) -> _Transform:
        key = (width, height)
        transform = state.transforms.get(key)
        if transform is None:
            transform = _build_transform(state.quad, width, height)
            if len(state.transforms) >= MAX_CACHED_SIZES:
                state.transforms.pop(next(iter(state.transforms)))
            state.transforms[key] = transform
        return transform


def _edge_lengths(quad: Quad, width: int, height: int) -> tuple[float, float]:
    """Mean horizontal and vertical edge length in pixels."""
    tl, tr, br, bl = (np.array([x * width, y * height]) for x, y in quad)
    top, bottom = np.linalg.norm(tr - tl), np.linalg.norm(br - bl)
    left, right = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
    return float(top + bottom) / 2, float(left + right) / 2


def _output_size(quad: Quad, width: int, height: int) -> tuple[int, int]:
    quad_w, quad_h = _edge_lengths(quad, width, height)
    fit = min(width / quad_w, height / quad_h)
    # nearest even size, never past the frame's own even bounds
    out_w = min(max(2, round(quad_w * fit / 2) * 2), max(2, width // 2 * 2))
    out_h = min(max(2, round(quad_h * fit / 2) * 2), max(2, height // 2 * 2))
    return out_w, out_h


def _build_transform(quad: Quad, width: int, height: int) -> _Transform:
    out_w, out_h = _output_size(quad, width, height)
    # normalized corners are pixel-edge coordinates; opencv samples at pixel centers
    src = np.array(quad, np.float32) * np.array([width, height], np.float32) - 0.5
    dst = np.array([(0, 0), (out_w, 0), (out_w, out_h), (0, out_h)], np.float32) - 0.5
    matrix = cast(NDArray[np.float64], cv2.getPerspectiveTransform(src, dst))
    return _Transform(matrix, (out_w, out_h))
