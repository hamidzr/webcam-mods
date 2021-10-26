from typing import Generator, Optional
from src.utils.video import sleep_until_fps
import cv2
import math
import numpy as np
from src.types import Rect, Point

FPS = 10

clicked: Point = Point()
def click_handler(event,x,y, *args):
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

    pred_color = (0, 255, 0)
    thickness = -1 # -1 to fill
    image = cv2.rectangle(image, pred.start_point.tuple, pred.end_point.tuple, pred_color, thickness)

    crop_color = (255, 255, 255)
    thickness = 1 # -1 to fill
    image = cv2.rectangle(image, crop.start_point.tuple, crop.end_point.tuple, crop_color, thickness)

    cv2.imshow(window_name, image)

def generate_prediction() -> Rect:
    r = Rect()
    r.move_to(clicked)
    return r

def move_cam(start: Point, end: Point, over_frames: int = 30):
    diff = end - start
    step_t, step_l = diff.t/over_frames, diff.l/over_frames
    cur_pos = start.copy()
    t_cum, l_cum = 0.0, 0.0
    for _ in range(over_frames):
        t_cum += step_t
        l_cum += step_l
        if int(t_cum) != 0:
            cur_pos.top += int(t_cum)
            t_cum -= int(t_cum)
        if int(l_cum) != 0:
            cur_pos.left += int(l_cum)
            l_cum -= int(l_cum)
        yield cur_pos.copy()


last_loc: Optional[Point] = None
move_gen: Optional[Generator] = None
def generate_crop(pred: Rect) -> Rect:
    # TODO https://github.com/hamidzr/webcam-mods/issues/12
    global last_loc, move_gen
    if last_loc is None:
        last_loc = pred.start_point
    if last_loc != pred.start_point:
        print('detected a move')
        move_gen = move_cam(last_loc, pred.start_point, 2*FPS)
        last_loc = pred.start_point
    elif move_gen is None:
        move_gen = move_cam(last_loc, pred.start_point, FPS)
    try:
        pt = next(move_gen)
    except StopIteration:
        move_gen = move_cam(last_loc, pred.start_point, FPS)
        pt = next(move_gen)

    crop = Rect.from_rect(pred)
    crop.height += math.floor(pred.height * 0.2)
    crop.width += math.floor(pred.width * 0.2)
    crop.move_to(pt)
    return crop

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

