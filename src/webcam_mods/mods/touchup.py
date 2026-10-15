"""Skin-restricted edge-preserving smoothing."""

from typing import cast

import cv2
import numpy as np

from webcam_mods.utils.video import Frame, validate_frame

# YCrCb skin range; Y floor skips near-black pixels whose chroma is noise
_SKIN_LOW = (40, 133, 77)
_SKIN_HIGH = (255, 173, 127)
_FEATHER_KERNEL = (9, 9)
_CLOSE_KERNEL = np.ones((3, 3), np.uint8)
# half-resolution gradient magnitude from where features such as eyes, brows and
# lips start keeping their detail, and where they keep all of it
_EDGE_LOW = 60.0
_EDGE_HIGH = 200.0
_BILATERAL_DIAMETER = 9


def smooth_skin(frame: Frame, strength: int) -> Frame:
    """Bilateral-smooth skin tones only; strength 0..100, 0 returns an unchanged copy.

    The skin mask runs at half resolution and leaves strong edges alone, so eyes and
    mouths stay sharp; the filter and blend run at full resolution, and non-skin
    areas keep every original pixel.
    """
    validate_frame(frame)
    if (
        not isinstance(strength, (int, np.integer))
        or isinstance(strength, bool)
        or not 0 <= strength <= 100
    ):
        raise ValueError("strength must be an int in 0..100")
    if strength == 0:
        return frame.copy()
    height, width = frame.shape[:2]
    small = cv2.resize(
        frame, (max(1, width // 2), max(1, height // 2)), interpolation=cv2.INTER_AREA
    )
    skin = cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb), _SKIN_LOW, _SKIN_HIGH)
    if not cv2.countNonZero(skin):
        return frame.copy()
    # close noise holes, then feather so the blend fades out at skin borders
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, _CLOSE_KERNEL)
    alpha = cv2.GaussianBlur(skin, _FEATHER_KERNEL, 0).astype(np.float32)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = np.asarray(
        cv2.magnitude(
            cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3),
            cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3),
        ),
        np.float32,
    )
    edges -= _EDGE_LOW
    edges *= 1 / (_EDGE_HIGH - _EDGE_LOW)
    np.clip(edges, 0, 1, out=edges)
    alpha *= 1 - cv2.GaussianBlur(cv2.dilate(edges, _CLOSE_KERNEL), (5, 5), 0)
    # square root: the middle of the slider already shows
    alpha *= (strength / 100) ** 0.5 / 255
    smoothed = cv2.bilateralFilter(
        frame, _BILATERAL_DIAMETER, 10 + 0.4 * strength, _BILATERAL_DIAMETER
    )
    alpha_full = cv2.resize(alpha, (width, height), interpolation=cv2.INTER_LINEAR)
    result = np.subtract(smoothed, frame, dtype=np.float32)
    result *= alpha_full[:, :, None]
    result += frame
    return cast(Frame, cv2.convertScaleAbs(result))
