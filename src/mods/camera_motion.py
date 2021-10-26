from typing import Generator, Optional
import math
from src.config import MAX_OUT_FPS
from src.geometry import Rect, Point

FPS = MAX_OUT_FPS
last_loc: Optional[Point] = None
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
    global last_loc, move_gen
    if last_loc is None:
        last_loc = pred.center
    if last_loc != pred.center:
        print('detected a move')
        move_gen = transition_point(last_loc, pred.center, 2*FPS)
        last_loc = pred.center
    elif move_gen is None:
        move_gen = transition_point(last_loc, pred.center, FPS)
    try:
        pt = next(move_gen)
    except StopIteration:
        move_gen = transition_point(last_loc, pred.center, FPS)
        pt = next(move_gen)

    crop = Rect(
        w=math.floor(pred.width * 1.2),
        h=math.floor(pred.height * 1.2)
    )
    crop.center_on(pt)
    return crop

