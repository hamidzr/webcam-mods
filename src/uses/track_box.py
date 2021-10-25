from src.utils.video import sleep_until_fps
import cv2
import math
import numpy as np
from src.types import Rect, Point

clicked: Point = Point()
def click_handler(event,x,y,flags,param):
    global clicked
    if event == cv2.EVENT_LBUTTONDOWN:
        clicked.left, clicked.top = x,y

def visualize(
    frame: Rect = Rect(w=400, h=400),
    crop: Rect = Rect(),
    pred: Rect = Rect(),
):
    # print(frame, crop, pred)
    image = np.zeros((frame.h, frame.w, 3), np.uint8)

    window_name = 'simulate'
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, click_handler)

    crop_color = (255, 255, 255)
    thickness = 1 # -1 to fill
    image = cv2.rectangle(image, crop.start_point.tuple, crop.end_point.tuple, crop_color, thickness)

    pred_color = (0, 255, 255)
    thickness = 1 # -1 to fill
    image = cv2.rectangle(image, pred.start_point.tuple, pred.end_point.tuple, pred_color, thickness)

    cv2.imshow(window_name, image)

def generate_prediction() -> Rect:
    r = Rect()
    r.move_to(clicked)
    return r

def generate_crop(pred: Rect) -> Rect:
    # TODO https://github.com/hamidzr/webcam-mods/issues/12
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
        sleep_until_fps(10)