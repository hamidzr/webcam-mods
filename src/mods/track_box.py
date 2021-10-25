import cv2
import math
import numpy as np
from src.types import Rect

def visualize(
    frame: Rect = Rect(w=400, h=400),
    crop: Rect = Rect(),
    pred: Rect = Rect(),
):
    # print(frame, crop, pred)
    image = np.zeros((frame.h, frame.w, 3), np.uint8)

    crop_color = (255, 255, 255)
    thickness = 1 # -1 to fill
    image = cv2.rectangle(image, crop.start_point.tuple, crop.end_point.tuple, crop_color, thickness)

    pred_color = (0, 255, 255)
    thickness = 1 # -1 to fill
    image = cv2.rectangle(image, pred.start_point.tuple, pred.end_point.tuple, pred_color, thickness)

    cv2.imshow('Simluate', image)


def generate_prediction() -> Rect:
    return Rect()

def generate_crop(pred: Rect) -> Rect:
    crop = Rect.from_rect(pred)
    crop.height += math.floor(pred.height * 0.2)
    crop.width += math.floor(pred.width * 0.2)
    return crop

if __name__ == '__main__':
    while True:
        pred = generate_prediction()
        crop = generate_crop(pred)
        visualize(pred=pred, crop=crop)
        if (cv2.waitKey(1) & 0xFF) == ord('q'):
            cv2.destroyAllWindows()
            break
