import cv2
import numpy as np


def frame_modr(frame):
    kernel = np.ones((5, 3)).astype(np.uint8)
    grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
    mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
    return mapped_grad


def crop(frame, w: int, h: int, x1=0, y1=0):
    # assuming frame is always of the same shape
    # assuming w, h are smaller than the frame

    fh, fw, _ = frame.shape

    # keep the output strictly WxH
    if x1 < 0:
        x1 = 0
    if x1 > fw-w:
        x1 = fw-w
    if y1 < 0:
        y1 = 0
    if y1 > fh-h:
        y1 = fh-h

    return frame[y1:y1+h, x1:x1+w].copy()
