from webcam_mods.utils.video import sleep_until_fps
import cv2
import random
import numpy as np
from webcam_mods.geometry import Rect, Point
from webcam_mods.mods.camera_motion import generate_crop, FPS

c = 0
clicked: Point = Point()
def click_handler(event,x,y, *args):
    global clicked, c
    if event == cv2.EVENT_LBUTTONDOWN:
        clicked.left, clicked.top = x,y
        c += 1

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

    pred_color = (0, 255, 0)
    thickness = -1 # -1 to fill
    image = cv2.rectangle(image, pred.start_point.tuple, pred.end_point.tuple, pred_color, thickness)

    crop_color = (255, 255, 255)
    thickness = 1 # -1 to fill
    image = cv2.rectangle(image, crop.start_point.tuple, crop.end_point.tuple, crop_color, thickness)

    cv2.imshow(window_name, image)

def generate_prediction() -> Rect:
    r = Rect(
        w=150 if c%3==0 else 100,
        h=150 if c%3==0 else 100
        # w=int(100 * random.uniform(0.8,1.3)),
        # h=int(100 * random.uniform(0.8,1.2))
    )
    r.center_on(clicked)
    return r

if __name__ == '__main__':
    print('click on the canvas to simulate moving the prediction box')
    while True:
        pred = generate_prediction()
        crop = generate_crop(pred)
        visualize(pred=pred, crop=crop)
        if (cv2.waitKey(1) & 0xFF) == ord('q'):
            cv2.destroyAllWindows()
            break
        sleep_until_fps(FPS)

