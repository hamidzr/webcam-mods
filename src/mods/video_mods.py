import cv2
import numpy as np


# def frame_modr(frame):
#     kernel = np.ones((5, 3)).astype(np.uint8)
#     grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
#     mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
#     return mapped_grad


def crop(frame, w: int, h: int, x1=0, y1=0):
    """
    x1, y1: top left corner of the crop area.
    # assuming frame is always of the same shape
    # assuming w, h are smaller than the frame
    """

    fh, fw, _ = frame.shape

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


def resize_and_pad(img: np.ndarray, sw: int, sh: int, padColor=0) -> np.ndarray:
    assert isinstance(img, np.ndarray)
    h, w = img.shape[:2]

    if h == sh and w == sw:
        return img

    # interpolation method
    if h > sh or w > sw: # shrinking image
        interp = cv2.INTER_AREA
    else: # stretching image
        interp = cv2.INTER_CUBIC

    # aspect ratio of image
    aspect = w/h  # if on Python 2, you might need to cast as a float: float(w)/h

    # compute scaling and pad sizing
    if aspect > 1: # horizontal image
        new_w = sw
        new_h = np.round(new_w/aspect).astype(int)
        pad_vert = (sh-new_h)/2
        pad_top, pad_bot = np.floor(pad_vert).astype(int), np.ceil(pad_vert).astype(int)
        pad_left, pad_right = 0, 0
    elif aspect < 1: # vertical image
        new_h = sh
        new_w = np.round(new_h*aspect).astype(int)
        pad_horz = (sw-new_w)/2
        pad_left, pad_right = np.floor(pad_horz).astype(int), np.ceil(pad_horz).astype(int)
        pad_top, pad_bot = 0, 0
    else: # square image
        new_h, new_w = sh, sw
        pad_left, pad_right, pad_top, pad_bot = 0, 0, 0, 0

    # set pad color
    if len(img.shape) is 3 and not isinstance(padColor, (list, tuple, np.ndarray)): # color image but only one color provided
        padColor = [padColor]*3

    # scale and pad
    scaled_img = cv2.resize(img, (new_w, new_h), interpolation=interp)
    scaled_img = cv2.copyMakeBorder(scaled_img, pad_top, pad_bot, pad_left, pad_right, borderType=cv2.BORDER_CONSTANT, value=padColor)

    return scaled_img
