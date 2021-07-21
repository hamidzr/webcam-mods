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
    mask = results.segmentation_mask

    image.flags.writeable = True
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    # To improve segmentation around boundaries, consider applying a joint
    # bilateral filter to "results.segmentation_mask" with "image".
    # Apply bilateral filter with d = 15, 
    # sigmaColor = sigmaSpace = 75.
    # mask = cv2.bilateralFilter(mask, 3, 75, 75)

    # se1 = cv2.getStructuringElement(cv2.MORPH_RECT, (20,20))
    # mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, se1)
    # remove rectangles smaller than 10x10
    se2 = cv2.getStructuringElement(cv2.MORPH_RECT, (10,10))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, se2)

    mask = cv2.GaussianBlur(mask,(5,5),0)

    condition = np.stack((mask,) * 3, axis=-1) > 0.1

    # bg_image = np.zeros(image.shape, dtype=np.uint8)
    # bg_image[:] = (0, 0, 0)
    # fg_image = np.zeros(image.shape, dtype=np.uint8)
    # fg_image[:] = (255, 255, 255)
    # output_image = np.where(condition, bg_image, fg_image)

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


def swap_bg(frame, bg_image):
    image, condition = mask(frame)
    output_image = np.where(condition, image, bg_image)
    return output_image
