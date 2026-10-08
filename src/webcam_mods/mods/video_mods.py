from numpy.typing import NDArray
from webcam_mods.utils.video import Frame
from webcam_mods.geometry import Rect
import cv2
import math
import numpy as np
from typing import Tuple, Optional, cast

Color = int | float | list[int] | tuple[int, ...] | NDArray[np.uint8]

# def frame_modr(frame):
#     kernel = np.ones((5, 3)).astype(np.uint8)
#     grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
#     mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
#     return mapped_grad


def is_crop_valid(
    frame: Tuple[int, int], start: Tuple[int, int], dims: Tuple[int, int]
) -> bool:
    """
    Checks whether the rectangle defined by `start` and `dims` represent a valid section in `frame`.
    frame: frame dimensions
    """
    # Make sure start is within frame
    if (
        (start[0] > frame[0])
        or (start[0] < 0)
        or (start[1] > frame[1])
        or (start[1] < 0)
    ):
        return False

    # reject empty crops before calling OpenCV
    if dims[0] <= 0 or dims[1] <= 0:
        return False

    # Make sure start + dims are still within the frame
    if (start[0] + dims[0] > frame[0]) or (start[1] + dims[1] > frame[1]):
        return False

    return True


def crop(frame: Frame, w: int, h: int, x1: int = 0, y1: int = 0) -> Optional[Frame]:
    """
    x1, y1: top left corner of the crop area.
    w, h: crop width and height
    # assuming frame is always of the same shape
    # assuming w, h are smaller than the frame
    """

    fh, fw, _ = frame.shape

    if not is_crop_valid((fw, fh), (x1, y1), (w, h)):
        return None

    # keep the output strictly WxH
    if x1 < 0:
        x1 = 0
    elif x1 > fw - w:
        x1 = fw - w
    if y1 < 0:
        y1 = 0
    elif y1 > fh - h:
        y1 = fh - h

    return frame[y1 : y1 + h, x1 : x1 + w].copy()


def crop_rect(frame: Frame, box: Rect) -> Optional[Frame]:
    """Keep a padded face crop inside the image, preserving its size when possible."""
    height, width = frame.shape[:2]
    crop_width, crop_height = min(box.width, width), min(box.height, height)
    left = max(0, min(box.left, width - crop_width))
    top = max(0, min(box.top, height - crop_height))
    return crop(frame, crop_width, crop_height, left, top)


def ensure_rgb_color(color: Color) -> tuple[float, ...]:
    # color image but only one color provided
    channels: tuple[float, ...]
    if not isinstance(color, (list, tuple, np.ndarray)):
        channels = (float(color),) * 3
    else:
        try:
            channels = tuple(float(channel) for channel in color)
        except TypeError, ValueError:
            raise ValueError("color must contain three finite BGR values in [0, 255]")
    if len(channels) != 3 or any(
        not math.isfinite(channel) or not 0 <= channel <= 255 for channel in channels
    ):
        raise ValueError("color must contain three finite BGR values in [0, 255]")
    return channels


# pad frame with pixels on each side.
def pad(
    frame: Frame,
    left: int = 0,
    top: int = 0,
    right: int = 0,
    bottom: int = 0,
    color: Color = 0,
) -> Frame:
    border_color = ensure_rgb_color(color)
    # OpenCV preserves the input dtype; its stubs expose a broader numeric union
    return cast(
        Frame,
        cv2.copyMakeBorder(
            frame, top, bottom, left, right, cv2.BORDER_CONSTANT, None, border_color
        ),
    )


# given a frame pad inward while keeping the image centered
def pad_inward_centered(
    frame: Frame, horizontal: int = 0, vertical: int = 0, color: Color = 0
) -> Frame:
    assert horizontal % 2 == 0, "needs an even size"
    assert vertical % 2 == 0, "needs an even size"
    if horizontal == 0 and vertical == 0:
        return frame
    # print('input frame shape', frame.shape)
    fh, fw, _ = frame.shape

    # ensure that inward padding isn't greater than the image dimensions
    horizontal = min(fw, horizontal)
    vertical = min(fh, vertical)

    crop_width = fw - horizontal
    crop_height = fh - vertical
    left_pad = horizontal // 2
    top_pad = vertical // 2
    cropped = crop(frame, crop_width, crop_height, left_pad, top_pad)
    if cropped is None:
        raise ValueError("inward padding produces an invalid crop")
    # print('cropped frame shape', frame.shape, (crop_height, crop_width))
    padded = pad(cropped, left_pad, top_pad, left_pad, top_pad, color)
    # print('padded shape', padded.shape)
    return padded


# given a frame pad inward while keeping the image centered
def pad_outward_centered(
    frame: Frame, horizontal: int = 0, vertical: int = 0, color: Color = 0
) -> Frame:
    # TODO remove the need for even dims
    assert horizontal % 2 == 0, "needs an even size"
    assert vertical % 2 == 0, "needs an even size"
    return pad(
        frame, horizontal // 2, vertical // 2, horizontal // 2, vertical // 2, color
    )


def resize_to_box(img: Frame, tw: int, th: int) -> Frame:
    """
    Resize to a bounding box while keeping aspect ratio.
    The resulting image is at or lower dimensions than target.
    tw: width of the target bounding box
    th: height of the bounding box
    """
    assert isinstance(img, np.ndarray)
    h, w = img.shape[:2]

    if h == th and w == tw:
        return img

    h_scale = th / h  # 5, 5
    w_scale = tw / w  # 2, 0.1

    scale = min(h_scale, w_scale)

    # interpolation method
    if scale < 1:  # shrinking image
        interp = cv2.INTER_AREA
    else:  # stretching image
        interp = cv2.INTER_CUBIC

    # integer ratios avoid losing a pixel at an exactly matching aspect
    if tw * h <= th * w:
        new_w, new_h = tw, max(1, h * tw // w)
    else:
        new_w, new_h = max(1, w * th // h), th

    # scale and pad
    scaled_img = cast(Frame, cv2.resize(img, (new_w, new_h), interpolation=interp))
    return scaled_img


def pad_to_box(img: Frame, tw: int, th: int, color: Color = 0) -> Frame:
    """
    pad an input frame to an equal or bigger bounding box.
    tw: width of the target bounding box
    th: height of the bounding box
    """
    h, w = img.shape[:2]

    assert h <= th, "frame does not fit the target"
    assert w <= tw, "frame does not fit the target"

    if (w, h) == (tw, th):
        return img
    horizontal, vertical = tw - w, th - h
    return pad(
        img,
        horizontal // 2,
        vertical // 2,
        horizontal - horizontal // 2,
        vertical - vertical // 2,
        color,
    )


def resize_and_pad(img: Frame, sw: int, sh: int, pad_color: Color = 0) -> Frame:
    """
    Resize while keeping the aspect ratio of the input frame by padding horizontally or vertically.
    sw: target width
    sh: target height
    """

    img = resize_to_box(img, sw, sh)
    assert img is not None
    return pad_to_box(img, sw, sh, pad_color)


def brighten(img: Frame, value: int) -> Frame:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # saturating channel addition avoids split/merge and boolean-index arrays
    cv2.add(hsv, np.asarray((0, 0, value, 0), dtype=np.float64), dst=hsv)
    return cast(Frame, cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
