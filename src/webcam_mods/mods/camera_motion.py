from typing import Callable, Generator, Optional, List, Any, Tuple
import math
from webcam_mods.config import MAX_OUT_FPS
from webcam_mods.geometry import Number, Rect, Point
from loguru import logger

FPS = MAX_OUT_FPS
last_pred: Optional[Rect] = None
cur_crop: Optional[Rect] = None
transition: Optional[Generator] = None


def linear_transition(a: Number, b: Number, steps: int) -> Generator[Number, Any, Any]:
    """
    linear transition
    """
    d = (b - a) / steps
    for _ in range(steps):
        yield a + d
        a += d


Transition = Callable[[Number, Number, int], Generator[Number, Any, Any]]


def transition_nd(
    transition: Transition, start: List[Number], end: List[Number], steps: int,
) -> Generator[List[Number], Any, Any]:
    assert len(start) == len(end)
    # g1 = transition(a1, a2, steps)
    # g2 = transition(b1, b2, steps)
    gs = [transition(start[i], end[i], steps) for i in range(len(start))]
    for _ in range(steps):
        yield [next(g) for g in gs]


def transition_point(start: Point, end: Point, over_frames: int = 30) -> Point:
    """
    move a point from start to end over n frames in a linear fashion
    """
    diff = end - start
    step_t, step_l = diff.t / over_frames, diff.l / over_frames
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


def transition_rect(start: Rect, end: Rect, over_frames: int = 30):
    """
    transitions location as well as dimensions
    """
    g = transition_nd(
        linear_transition,
        start=[start.l, start.t, start.w, start.h],
        end=[end.l, end.t, end.w, end.h],
        steps=over_frames,
    )
    for _ in range(over_frames):
        l, t, w, h = next(g)
        yield Rect(l=int(l), w=int(w), h=int(h), t=int(t))


def wrap_with_padding(box: Rect, wr, hr) -> Rect:
    """
    wrap a box with padding on all sides based on ratio.
    wr: width ratio
    hr: height ratio
    """
    output = Rect(w=math.floor(box.width * wr), h=math.floor(box.height * hr))
    output.center_on(box.center)
    return output


def generate_crop(pred: Rect, padding: Optional[Tuple[float, float]]) -> Rect:
    """
    generates a smooth moving crop to `pred` from `last_pred`
    padding: padding ratio (width_ratio, height_ratio)
    """
    # TODO https://github.com/hamidzr/webcam-mods/issues/12
    global last_pred, transition, cur_crop
    THRESHOLD = max(pred.w, pred.h) // 3
    TRANSITION_TIME = 1  # sec
    padding = padding or (1.4, 1.8)

    if last_pred is None:
        last_pred = pred
    if cur_crop is None:
        cur_crop = pred

    # did prediction move significantly?
    move_dist = last_pred.center - pred.center
    if (abs(move_dist.l) > THRESHOLD or abs(move_dist.t) > THRESHOLD) or (
        pred.h - last_pred.height > THRESHOLD or pred.w - last_pred.w > THRESHOLD
    ):
        logger.debug(f"motion/zoom detected: {move_dist}")
        transition = transition_rect(cur_crop or last_pred, pred, TRANSITION_TIME * FPS)
        last_pred = pred

    # keep generating
    if transition is not None:
        try:
            transitioned_pred = next(transition)
            cur_crop = transitioned_pred
        except StopIteration:
            transition = None
            logger.debug("transition finished")

    return wrap_with_padding(cur_crop, wr=padding[0], hr=padding[1])
