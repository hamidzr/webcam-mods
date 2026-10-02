from typing import Callable, Generator, Optional, List, Any, Tuple
import math
from webcam_mods.settings import load_settings
from webcam_mods.geometry import Number, Rect, Point
from loguru import logger


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
    transition: Transition,
    start: List[Number],
    end: List[Number],
    steps: int,
) -> Generator[List[Number], Any, Any]:
    assert len(start) == len(end)
    # g1 = transition(a1, a2, steps)
    # g2 = transition(b1, b2, steps)
    gs = [transition(start[i], end[i], steps) for i in range(len(start))]
    for _ in range(steps):
        yield [next(g) for g in gs]


def transition_point(
    start: Point, end: Point, over_frames: int = 30
) -> Generator[Point, None, None]:
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


def transition_rect(
    start: Rect, end: Rect, over_frames: int = 30
) -> Generator[Rect, None, None]:
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


def wrap_with_padding(box: Rect, wr: float, hr: float) -> Rect:
    """
    wrap a box with padding on all sides based on ratio.
    wr: width ratio
    hr: height ratio
    """
    output = Rect(w=math.floor(box.width * wr), h=math.floor(box.height * hr))
    output.center_on(box.center)
    return output


class CropTracker:
    """Own face-crop interpolation state for one run."""

    def __init__(self, fps: float | None = None) -> None:
        fps = load_settings().max_out_fps if fps is None else fps
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Crop tracker FPS must be positive")
        self.fps = max(1, round(fps))
        self.last_pred: Optional[Rect] = None
        self.cur_crop: Optional[Rect] = None
        self.transition: Optional[Generator[Rect, None, None]] = None

    def generate_crop(self, pred: Rect, padding: Optional[Tuple[float, float]]) -> Rect:
        """Smooth movement to a face rectangle, then apply padding ratios."""
        threshold = max(pred.w, pred.h) // 3
        padding = padding or (2, 2.5)
        if self.last_pred is None:
            self.last_pred = Rect.from_rect(pred)
        if self.cur_crop is None:
            self.cur_crop = Rect.from_rect(pred)

        move_dist = self.last_pred.center - pred.center
        if (abs(move_dist.l) > threshold or abs(move_dist.t) > threshold) or (
            pred.h - self.last_pred.height > threshold
            or pred.w - self.last_pred.w > threshold
        ):
            logger.debug(f"motion/zoom detected: {move_dist}")
            self.transition = transition_rect(
                self.cur_crop, Rect.from_rect(pred), self.fps
            )
            self.last_pred = Rect.from_rect(pred)

        if self.transition is not None:
            try:
                self.cur_crop = next(self.transition)
            except StopIteration:
                self.transition = None
                logger.debug("transition finished")
        return wrap_with_padding(self.cur_crop, wr=padding[0], hr=padding[1])

    def close(self) -> None:
        """Discard interpolation state after a run."""
        if self.transition is not None:
            self.transition.close()
        self.last_pred = self.cur_crop = self.transition = None


_default_tracker = CropTracker()


def generate_crop(pred: Rect, padding: Optional[Tuple[float, float]]) -> Rect:
    """Compatibility helper; new runs should own a CropTracker instance."""
    return _default_tracker.generate_crop(pred, padding)
