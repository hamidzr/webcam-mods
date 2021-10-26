from typing import Generator, Optional
import math
from src.config import MAX_OUT_FPS
from src.geometry import Rect, Point

FPS = MAX_OUT_FPS
last_pred: Optional[Rect] = None
move_gen: Optional[Generator] = None

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
    global last_pred, move_gen
    THRESHOLD = max(pred.w, pred.h) // 4
    TRANSITION_SPEED = 2 # sec

    if last_pred is None:
        last_pred = pred
    move_dist = last_pred.center - pred.center
    # print(move_dist, THRESHOLD)
    if abs(move_dist.l) > THRESHOLD or abs(move_dist.t) > THRESHOLD : # TODO transition sizes
        print('motion detected', move_dist)
        move_gen = transition_point(last_pred.center, pred.center, TRANSITION_SPEED*FPS)
        last_pred = pred

    # keep generating
    elif move_gen is None:
        move_gen = transition_point(last_pred.center, last_pred.center, FPS)
    try:
        pt = next(move_gen)
    except StopIteration:
        move_gen = transition_point(last_pred.center, last_pred.center, FPS)
        pt = next(move_gen)

    crop = Rect(
        w=math.floor(last_pred.width * 1.2),
        h=math.floor(last_pred.height * 1.2)
    )
    crop.center_on(pt)
    return crop

