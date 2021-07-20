import cv2
import mediapipe as mp
import numpy as np

BG_COLOR = (192, 192, 192) # gray
MODEL_SELECTION = 0
BLUR_SIZE = 45

selfie_segmentation = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=MODEL_SELECTION)
# selfie_segmentation.close()

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

    image.flags.writeable = True
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    # Draw selfie segmentation on the background image.
    # To improve segmentation around boundaries, consider applying a joint
    # bilateral filter to "results.segmentation_mask" with "image".
    condition = np.stack((results.segmentation_mask,) * 3, axis=-1) > 0.1
    return image, condition


def color_bg(frame, color=BG_COLOR):
    image, condition = mask(frame)
    bg_image = np.zeros(image.shape, dtype=np.uint8)
    bg_image[:] = BG_COLOR
    output_image = np.where(condition, image, bg_image)
    return output_image


def blur_bg(frame, blur_size=BLUR_SIZE):
    image, condition = mask(frame)
    bg_image = cv2.GaussianBlur(image,(blur_size,blur_size),0)
    output_image = np.where(condition, image, bg_image)
    return output_image


def swap_bg(frame, path: str):
    image, condition = mask(image)
    bg_image = cv2.imread('/path/to/image/file')
    output_image = np.where(condition, image, bg_image)
    return output_image

