from typing import Generator, Optional
import math
from src.config import MAX_OUT_FPS
from src.geometry import Rect, Point

FPS = MAX_OUT_FPS
last_pred: Optional[Rect] = None
cur_crop: Optional[Rect] = None
transition: Optional[Generator] = None

def transition_point(start: Point, end: Point, over_frames: int = 30):
    """
    move a point from start to end over n frames in a linear fashion
    """
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


def generate_crop(pred: Rect) -> Rect:
    # TODO https://github.com/hamidzr/webcam-mods/issues/12
    global last_pred, transition, cur_crop
    THRESHOLD = max(pred.w, pred.h) // 3
    TRANSITION_SPEED = 2 # sec

    if last_pred is None:
        last_pred = pred
    if cur_crop is None:
        cur_crop = pred
    move_dist = last_pred.center - pred.center
    # print(move_dist, THRESHOLD)
    if abs(move_dist.l) > THRESHOLD or abs(move_dist.t) > THRESHOLD : # TODO transition sizes
        print('motion detected', move_dist)
        transition = transition_point(cur_crop.center or last_pred.center, pred.center, TRANSITION_SPEED*FPS)
        last_pred = pred

    # keep generating
    if transition is not None:
        try:
            pt = next(transition)
            cur_crop.center_on(pt)
        except StopIteration:
            transition = None
            print('transition finished')

    crop = Rect(
        w=math.floor(last_pred.width * 1.4),
        h=math.floor(last_pred.height * 1.6)
    )
    crop.center_on(cur_crop.center)
    return crop

