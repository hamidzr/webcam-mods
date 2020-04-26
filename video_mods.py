import cv2
import numpy as np


def frame_modr(frame):
    kernel = np.ones((5, 3)).astype(np.uint8)
    grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
    mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
    return mapped_grad


def crop(frame, w: int, h: int, x=0, y=0):
    return frame[y:y+h, x:x+w].copy()
