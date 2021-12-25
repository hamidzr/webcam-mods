from src.mods.video_mods import ensure_rgb_color
import cv2
from mediapipe.python.solutions import selfie_segmentation
import numpy as np

BG_COLOR = (192, 192, 192) # gray
MODEL_SELECTION = 0

selfie_segmentation = selfie_segmentation.SelfieSegmentation(model_selection=MODEL_SELECTION)
# selfie_segmentation.close()

def biggest_comp(image):
    """
    Find the biggest connected component in a black and white mask
    """
    # find white blocks
    nb_components, output, stats, centroids = cv2.connectedComponentsWithStats(image, connectivity=4)
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

def sigmoid(x, a=5., b=-10.):
    """
    Converts the 0-1 value to a sigmoid going from zero to 1 in the same range
    """
    z = np.exp(a + b * x)
    sig = 1 / (1 + z)
    return sig


# given a frame generates a mask
def mask(frame):
    image = frame

    # Flip the image horizontally for a later selfie-view display, and convert
    # the BGR image to RGB.
    image = cv2.cvtColor(cv2.flip(image, 1), cv2.COLOR_BGR2RGB)
    # To improve performance, optionally mark the image as not writeable to
    # pass by reference.
    image.flags.writeable = False
    results = selfie_segmentation.process(image)
    result = results.segmentation_mask

    image.flags.writeable = True
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

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


def blur_bg(frame, kernel_size):
    image, condition = mask(frame)
    # bg_image = cv2.GaussianBlur(image,(kernel_size,kernel_size),0) # more cpu intensive
    bg_image = cv2.blur(image,(kernel_size,kernel_size))
    return apply_alpha_mask(fg=image, bg=bg_image, mask=condition)


def swap_bg(frame, bg_image):
    image, condition = mask(frame)
    return apply_alpha_mask(fg=image, bg=bg_image, mask=condition)

# mask: matrix with values 0-1
def apply_alpha_mask(fg, bg, mask):
    output_image = fg * mask + bg * (1-mask)
    return output_image.astype(np.uint8)
