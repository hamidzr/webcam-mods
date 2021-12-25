from webcam_mods.geometry import Rect
import cv2
import math
import numpy as np
from typing import Tuple, Optional


# def frame_modr(frame):
#     kernel = np.ones((5, 3)).astype(np.uint8)
#     grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
#     mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
#     return mapped_grad


def is_crop_valid(frame: Tuple[int, int], start: Tuple[int, int], dims: Tuple[int, int]) -> bool:
    """
    Checks whether the rectangle defined by `start` and `dims` represent a valid section in `frame`.
    frame: frame dimensions
    """
    # Make sure start is within frame
    if (start[0] > frame[0]) or (start[0] < 0) or (start[1] > frame[1]) or (start[1] < 0):
        return False

    # Make sure that dims are positive numbers, <0 not supported
    if dims[0] < 0 or dims[1] < 0:
        return False

    # Make sure start + dims are still within the frame
    if (start[0] + dims[0] > frame[0]) or (start[1] + dims[1] > frame[1]):
        return False

    return True


def crop(frame, w: int, h: int, x1=0, y1=0) -> Optional[np.ndarray]:
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
    elif x1 > fw-w:
        x1 = fw-w
    if y1 < 0:
        y1 = 0
    elif y1 > fh-h:
        y1 = fh-h

    return frame[y1:y1+h, x1:x1+w].copy()

def crop_rect(frame, box: Rect):
    return crop(frame, box.w, box.h, box.l, box.t)

def ensure_rgb_color(color):
    # color image but only one color provided
    if not isinstance(color, (list, tuple, np.ndarray)):
        color = [color]*3
    return color

# pad frame with pixels on each side.
def pad(frame: np.ndarray, left=0, top=0, right=0, bottom=0, color=[0,0,0]):
    color = ensure_rgb_color(color)
    return cv2.copyMakeBorder(frame, top, bottom, left, right,
        cv2.BORDER_CONSTANT, None, color)


# given a frame pad inward while keeping the image centered
def pad_inward_centered(frame: np.ndarray, horizontal=0, vertical=0, color=0):
    assert horizontal % 2 == 0, "needs an even size"
    assert vertical % 2 == 0, "needs an even size"
    # print('input frame shape', frame.shape)
    fh, fw, _ = frame.shape

    # ensure that inward padding isn't greater than the image dimensions
    horizontal = min(fw, horizontal)
    vertical = min(fh, vertical)

    crop_width = fw-horizontal
    crop_height = fh-vertical
    left_pad = horizontal//2
    top_pad = vertical//2
    frame = crop(frame, crop_width, crop_height, left_pad, top_pad)
    # print('cropped frame shape', frame.shape, (crop_height, crop_width))
    padded = pad(frame, left_pad, top_pad, left_pad, top_pad, color)
    # print('padded shape', padded.shape)
    return padded

# given a frame pad inward while keeping the image centered
def pad_outward_centered(frame: np.ndarray, horizontal=0, vertical=0, color=0):
    # TODO remove the need for even dims
    assert horizontal % 2 == 0, "needs an even size"
    assert vertical % 2 == 0, "needs an even size"
    return pad(frame, horizontal//2, vertical//2, horizontal//2, vertical//2, color)


def resize_to_box(img, tw: int, th: int):
    """
    Resize to a bounding box while keeping aspect ratio
    tw: width of the target bounding box
    th: height of the bounding box
    """
    assert isinstance(img, np.ndarray)
    h, w = img.shape[:2]

    if h == th and w == tw:
        return img

    h_scale = th / h # 5, 5
    w_scale = tw / w # 2, 0.1

    scale = min(h_scale, w_scale)

    # interpolation method
    if scale < 1: # shrinking image
        interp = cv2.INTER_AREA
    else: # stretching image
        interp = cv2.INTER_CUBIC

    # compute new even dimensions. FIXME we shouldn't need to care about making the frame even here
    new_w = math.floor(w * scale / 2) * 2
    new_h = math.floor(h * scale / 2) * 2

    # scale and pad
    scaled_img = cv2.resize(img, (new_w, new_h), interpolation=interp)
    return scaled_img


def pad_to_box(img, tw: int, th: int, color=0):
    """
    pad an input frame to an equal or bigger bounding box.
    tw: width of the target bounding box
    th: height of the bounding box
    """
    h, w = img.shape[:2]

    assert h <= th, "frame does not fit the target"
    assert w <= tw, "frame does not fit the target"

    return pad_outward_centered(img, tw-w, th-h, color)


def resize_and_pad(img: np.ndarray, sw: int, sh: int, pad_color=0) -> np.ndarray:
    """
    Resize while keeping the aspect ratio of the input frame by padding horizontally or vertically.
    sw: target width
    sh: target height
    """

    img = resize_to_box(img, sw, sh)
    return pad_to_box(img, sw, sh, pad_color)


def brighten(img, value: int):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    lim = 255 - value
    v[v > lim] = 255
    v[v <= lim] += value

    final_hsv = cv2.merge((h, s, v))
    img = cv2.cvtColor(final_hsv, cv2.COLOR_HSV2BGR)
    return img
