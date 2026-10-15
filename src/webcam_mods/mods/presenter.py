"""Camera picture over a shared screen: a round bubble or a person cutout."""

import functools
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from webcam_mods.utils.video import Frame

Alpha = NDArray[np.float32]

# gap between a bubble and the picture edges, as a share of the shorter side
MARGIN_RATIO = 0.03
# cutout coverage this close to 0 or 1 snaps to it
_SNAP = 0.01


@functools.lru_cache(maxsize=4)
def circle_alpha(diameter: int) -> Alpha:
    """Disc coverage with a one-pixel antialiased edge, shaped (d, d, 1)."""
    center = (diameter - 1) / 2
    rows, columns = np.ogrid[:diameter, :diameter]
    distance = np.sqrt((columns - center) ** 2 + (rows - center) ** 2)
    alpha = np.clip(diameter / 2 - distance, 0, 1).astype(np.float32)
    alpha.flags.writeable = False
    return alpha[:, :, None]


def _resize(image: NDArray[Any], width: int, height: int) -> NDArray[Any]:
    shrinking = width < image.shape[1]
    interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
    return cast(
        NDArray[Any], cv2.resize(image, (width, height), interpolation=interpolation)
    )


def bubble(camera: Frame, diameter: int) -> tuple[Frame, Alpha]:
    """Middle square of the camera picture, scaled into a disc."""
    height, width = camera.shape[:2]
    side = min(height, width)
    top, left = (height - side) // 2, (width - side) // 2
    square = camera[top : top + side, left : left + side]
    return cast(Frame, _resize(square, diameter, diameter)), circle_alpha(diameter)


def cutout(image: Frame, mask: NDArray[Any], height: int) -> tuple[Frame, Alpha]:
    """Camera picture and person mask scaled to height, keeping the aspect."""
    source_height, source_width = image.shape[:2]
    width = max(1, round(source_width * height / source_height))
    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.ndim == 3:
        alpha = alpha[:, :, 0]
    # person masks never quite reach 0 or 1; a faint box would show over flat slides
    alpha = np.clip((_resize(alpha, width, height) - _SNAP) / (1 - 2 * _SNAP), 0, 1)
    return cast(Frame, _resize(image, width, height)), cast(Alpha, alpha[:, :, None])


def place(
    frame: Frame, layer: Frame, alpha: Alpha, position: str, *, standing: bool
) -> Frame:
    """Blend layer into a corner of a copy of frame.

    Standing layers sit on the bottom edge, as a person rising from it; others
    keep a margin. Parts outside the frame are cut.
    """
    frame_height, frame_width = frame.shape[:2]
    layer_height, layer_width = layer.shape[:2]
    margin = round(MARGIN_RATIO * min(frame_width, frame_height))
    x = margin if position.endswith("left") else frame_width - margin - layer_width
    if standing:
        y = frame_height - layer_height
    elif position.startswith("top"):
        y = margin
    else:
        y = frame_height - margin - layer_height
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame_width, x + layer_width), min(frame_height, y + layer_height)
    if x1 <= x0 or y1 <= y0:
        return frame
    out = frame.copy()
    region = out[y0:y1, x0:x1].astype(np.float32)
    part = layer[y0 - y : y1 - y, x0 - x : x1 - x].astype(np.float32)
    coverage = alpha[y0 - y : y1 - y, x0 - x : x1 - x]
    blended = region + (part - region) * coverage
    out[y0:y1, x0:x1] = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
    return out
