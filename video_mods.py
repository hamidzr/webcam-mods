import cv2
import numpy as np


def frame_modr(frame):
    kernel = np.ones((5, 3)).astype(np.uint8)
    grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
    mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
    return mapped_grad


def crop(frame, w: int, h: int, x1=0, y1=0):
    x2 = x1+w
    y2 = y1+h
    fw, fh, _ = frame.shape

    # keep the output strictly WxH
    # assuming w, h are smaller than the frame
    if x2 > fw:
        dx = fw - x2
        x1 += dx
        x2 = fw  # off by one?
    if y2 > fh:
        dy = fh - y2
        y1 += dy
        y2 = fh
    if x1 < 0:
        dx = 0-x1
        x2 += dx
        x1 = 0
    if y1 < 0:
        dy = 0-y1
        y2 += dy
        y1 = 0

    return frame[y1:y2, x1:x2].copy()
