from typing import Generator, Optional
import math
from src.types import Rect, Point

FPS = 20
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
        last_loc = pred.start_point
    if last_loc != pred.start_point:
        print('detected a move')
        move_gen = transition_point(last_loc, pred.start_point, 2*FPS)
        last_loc = pred.start_point
    elif move_gen is None:
        move_gen = transition_point(last_loc, pred.start_point, FPS)
    try:
        pt = next(move_gen)
    except StopIteration:
        move_gen = transition_point(last_loc, pred.start_point, FPS)
        pt = next(move_gen)

    crop = Rect.from_rect(pred)
    crop.height += math.floor(pred.height * 0.2)
    crop.width += math.floor(pred.width * 0.2)
    crop.move_to(pt)
    return crop

