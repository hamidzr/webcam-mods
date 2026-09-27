from numpy.typing import NDArray
from webcam_mods.mods.video_mods import ensure_rgb_color
import cv2
import mediapipe as mp
import numpy as np
import time

from webcam_mods.models import model_path

BG_COLOR = (192, 192, 192)  # gray
_segmenter = None
_last_timestamp_ms = 0


def init() -> mp.tasks.vision.ImageSegmenter:
    global _segmenter
    if _segmenter is None:
        options = mp.tasks.vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(model_path("selfie_segmenter")),
                delegate=mp.tasks.BaseOptions.Delegate.CPU,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            output_confidence_masks=True,
        )
        _segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(options)
    return _segmenter


def biggest_comp(image):
    """
    Find the biggest connected component in a black and white mask
    """
    # find white blocks
    nb_components, output, stats, centroids = cv2.connectedComponentsWithStats(
        image, connectivity=4
    )
    sizes = stats[:, -1]

    max_label = 1
    max_size = sizes[0]
    for i in range(0, nb_components):
        if sizes[i] > max_size:
            max_label = i
            max_size = sizes[i]

    img2 = np.zeros(output.shape)
    img2[output == max_label] = 255
    # cv2.imshow("Biggest component", img2)
    return img2


def sigmoid(x, a=5.0, b=-10.0):
    """
    Converts the 0-1 value to a sigmoid going from zero to 1 in the same range
    """
    z = np.exp(a + b * x)
    sig = 1 / (1 + z)
    return sig


# given a frame generates a mask
def mask(frame: NDArray):
    global _last_timestamp_ms

    # Flip the image horizontally for a later selfie-view display, and convert
    # the BGR image to RGB.
    image = cv2.flip(frame, 1)
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb_image)
    )
    _last_timestamp_ms = max(time.monotonic_ns() // 1_000_000, _last_timestamp_ms + 1)
    results = init().segment_for_video(mp_image, _last_timestamp_ms)
    result = results.confidence_masks[0].numpy_view().squeeze(axis=-1)

    # post processing
    result = cv2.dilate(result, np.ones((5, 5), np.uint8), iterations=1)
    result = cv2.blur(result.astype(float), (10, 10))

    result = sigmoid(result)

    # condition = np.stack((result,) * 3, axis=-1) > 0.1
    # condition = result > 0.1

    # bg_image = np.zeros(result.shape, dtype=np.uint8)
    # bg_image[:] = (0,)
    # fg_image = np.zeros(result.shape, dtype=np.uint8)
    # fg_image[:] = (255,)
    # mask = np.where(condition, fg_image, bg_image)

    # # cv2.imshow('befoe', mask)
    # mask = biggest_comp(mask) cv2.imshow('after', mask)

    # To improve segmentation around boundaries, consider applying a joint
    # bilateral filter to "results.segmentation_mask" with "image".
    # Apply bilateral filter with d = 15,
    # sigmaColor = sigmaSpace = 75.
    # mask = cv2.bilateralFilter(mask, 3, 75, 75)

    # se1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (20,20))
    # mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, se1)
    # se2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (20,20))
    # mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, se2)

    # mask = cv2.GaussianBlur(mask,(5,5),0)

    # cv2.imshow('after more process', mask)

    # # Generate intermediate image; use morphological closing to keep parts of the brain together
    # gray = cv2.cvtColor(output_image, cv2.COLOR_RGB2GRAY)
    # inter = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    # # ret, inter = cv2.threshold(mask, 127, 255, 0)
    # # Find largest contour in intermediate image
    # cnts, _ = cv2.findContours(inter, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    # cnt = max(cnts, key=cv2.contourArea)

    # out = np.zeros(image.shape, np.uint8)
    # cv2.drawContours(out, [cnt], 0, 255, cv2.FILLED)

    # condition = out > 192
    # condition = np.stack((mask,) * 3, axis=-1) > 0.1
    condition = np.stack((result,) * 3, axis=-1)

    # cv2.waitKey(100)
    return image, condition


def color_bg(frame, color=BG_COLOR):
    image, condition = mask(frame)
    bg_image = np.zeros(image.shape, dtype=np.uint8)
    bg_image[:] = ensure_rgb_color(color)
    return apply_alpha_mask(fg=image, bg=bg_image, mask=condition)


def blur_bg(frame: NDArray, kernel_size):
    image, condition = mask(frame)
    # bg_image = cv2.GaussianBlur(image,(kernel_size,kernel_size),0) # more cpu intensive
    bg_image = cv2.blur(image, (kernel_size, kernel_size))
    return apply_alpha_mask(fg=image, bg=bg_image, mask=condition)


def swap_bg(frame, bg_image):
    image, condition = mask(frame)
    return apply_alpha_mask(fg=image, bg=bg_image, mask=condition)


# mask: matrix with values 0-1
def apply_alpha_mask(fg, bg, mask):
    output_image = fg * mask + bg * (1 - mask)
    return output_image.astype(np.uint8)
