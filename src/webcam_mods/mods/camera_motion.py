from typing import Callable, Generator, Optional, List, Tuple
import math
import time
from webcam_mods.settings import load_settings
from webcam_mods.geometry import Number, Rect, Point


def linear_transition(
    a: Number, b: Number, steps: int
) -> Generator[Number, None, None]:
    """
    linear transition
    """
    d = (b - a) / steps
    for _ in range(steps):
        yield a + d
        a += d


Transition = Callable[[Number, Number, int], Generator[Number, None, None]]


def transition_nd(
    transition: Transition,
    start: List[Number],
    end: List[Number],
    steps: int,
) -> Generator[List[Number], None, None]:
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
    """Frame-bounded, time-based framing with independent pan and zoom targets."""

    def __init__(
        self,
        fps: float | None = None,
        *,
        aspect_ratio: float = 4 / 3,
        face_height: float = 0.4,
        max_zoom: float = 2.0,
        target_x: float = 0.5,
        target_y: float = 0.42,
        pan_deadzone: float = 0.08,
        zoom_deadzone: float = 0.08,
        pan_seconds: float = 0.25,
        zoom_seconds: float = 0.6,
        lost_after: float = 1.0,
    ) -> None:
        fps = load_settings().max_out_fps if fps is None else fps
        values = dict(
            fps=fps,
            aspect_ratio=aspect_ratio,
            face_height=face_height,
            max_zoom=max_zoom,
            target_x=target_x,
            target_y=target_y,
            pan_deadzone=pan_deadzone,
            zoom_deadzone=zoom_deadzone,
            pan_seconds=pan_seconds,
            zoom_seconds=zoom_seconds,
            lost_after=lost_after,
        )
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("Tracking settings must be finite")
        if fps <= 0 or aspect_ratio <= 0 or not 0 < face_height <= 1:
            raise ValueError(
                "FPS, aspect ratio and face height must be positive; face height <= 1"
            )
        if max_zoom < 1:
            raise ValueError("Maximum zoom must be at least 1")
        if not 0 <= target_x <= 1 or not 0 <= target_y <= 1:
            raise ValueError("Target position must be between 0 and 1")
        if not 0 <= pan_deadzone < 1 or not 0 <= zoom_deadzone < 1:
            raise ValueError("Deadzones must be between 0 and 1, excluding 1")
        if pan_seconds <= 0 or zoom_seconds <= 0 or lost_after < 0:
            raise ValueError(
                "Response times must be positive; loss timeout nonnegative"
            )
        self.fps = fps
        self.aspect_ratio = aspect_ratio
        self.face_height = face_height
        self.max_zoom = max_zoom
        self.target_x, self.target_y = target_x, target_y
        self.pan_deadzone, self.zoom_deadzone = pan_deadzone, zoom_deadzone
        self.pan_seconds, self.zoom_seconds = pan_seconds, zoom_seconds
        self.lost_after = lost_after
        self.cur_crop: Rect | None = None
        self._state: tuple[float, float, float] | None = None
        self._focus: tuple[float, float] | None = None
        self._target_height: float | None = None
        self._seen_at: float | None = None
        self._last_time: float | None = None
        self._frame_size: tuple[int, int] | None = None

    def generate_crop(
        self,
        pred: Rect | None,
        padding: Optional[Tuple[float, float]] = None,
        *,
        frame_size: tuple[int, int],
        now: float | None = None,
    ) -> Rect:
        """Return an in-frame crop; zoom is relative to the largest fitted view.

        Padding remains an optional compatibility framing override. Both dimensions
        are minimum requested context, expanded to the configured output aspect.
        """
        width, height = frame_size
        if width < 2 or height < 2:
            raise ValueError("Tracking frame must be at least 2x2")
        now = time.monotonic() if now is None else now
        if not math.isfinite(now) or (
            self._last_time is not None and now < self._last_time
        ):
            raise ValueError("Tracking time must be finite and monotonic")
        if padding is not None and any(not math.isfinite(v) or v <= 0 for v in padding):
            raise ValueError("Padding ratios must be finite and positive")
        if pred is not None and (pred.w <= 0 or pred.h <= 0):
            raise ValueError("Face dimensions must be positive")
        if self._frame_size != frame_size:
            self._reset()
            self._frame_size = frame_size
        dt = 1 / self.fps if self._last_time is None else now - self._last_time
        self._last_time = now
        max_height = min(height, width / self.aspect_ratio)
        min_height = min(
            max_height, max(2, 2 / self.aspect_ratio, max_height / self.max_zoom)
        )
        if pred is not None:
            desired_height = (
                max(pred.h * padding[1], pred.w * padding[0] / self.aspect_ratio)
                if padding is not None
                else pred.h / self.face_height
            )
            desired_height = min(max_height, max(min_height, desired_height))
            focus = (pred.l + pred.w / 2, pred.t + pred.h / 2)
            reacquired = self._seen_at is None or now - self._seen_at > self.lost_after
            self._seen_at = now
            if self._focus is None or reacquired:
                self._focus = focus
                self._target_height = desired_height
            else:
                fx, fy = self._focus
                crop_height = (
                    self._state[2] if self._state is not None else desired_height
                )
                # anchor each axis independently so tiny motion does not accumulate jitter
                self._focus = (
                    (
                        focus[0]
                        if abs(focus[0] - fx)
                        > self.pan_deadzone * crop_height * self.aspect_ratio
                        else fx
                    ),
                    (
                        focus[1]
                        if abs(focus[1] - fy) > self.pan_deadzone * crop_height
                        else fy
                    ),
                )
                assert self._target_height is not None
                if abs(desired_height / self._target_height - 1) > self.zoom_deadzone:
                    self._target_height = desired_height
        lost = self._seen_at is None or now - self._seen_at > self.lost_after
        if lost:
            target_height = max_height
            tx, ty = width / 2, height / 2
        else:
            assert self._focus is not None and self._target_height is not None
            target_height = self._target_height
            tx = (
                self._focus[0]
                + (0.5 - self.target_x) * target_height * self.aspect_ratio
            )
            ty = self._focus[1] + (0.5 - self.target_y) * target_height
        target_width = target_height * self.aspect_ratio
        tx = min(width - target_width / 2, max(target_width / 2, tx))
        ty = min(height - target_height / 2, max(target_height / 2, ty))
        if self._state is None:
            cx, cy, ch = tx, ty, target_height
        else:
            cx, cy, ch = self._state
            pan_alpha = -math.expm1(-dt / self.pan_seconds)
            zoom_alpha = -math.expm1(-dt / self.zoom_seconds)
            cx += (tx - cx) * pan_alpha
            cy += (ty - cy) * pan_alpha
            ch += (target_height - ch) * zoom_alpha
        ch = min(max_height, max(min_height, ch))
        cw = ch * self.aspect_ratio
        cx = min(width - cw / 2, max(cw / 2, cx))
        cy = min(height - ch / 2, max(ch / 2, cy))
        self._state = (cx, cy, ch)
        # round upward so pixel quantization cannot exceed the zoom ceiling
        crop_width = min(width, max(2, math.ceil(cw - 1e-9)))
        crop_height = min(height, max(2, math.ceil(ch - 1e-9)))
        self.cur_crop = Rect(
            w=crop_width,
            h=crop_height,
            l=max(0, min(width - crop_width, round(cx - crop_width / 2))),
            t=max(0, min(height - crop_height, round(cy - crop_height / 2))),
        )
        return Rect.from_rect(self.cur_crop)

    def close(self) -> None:
        """Discard framing state after a run."""
        self._reset()

    def _reset(self) -> None:
        self.cur_crop = None
        self._state = None
        self._focus = None
        self._target_height = None
        self._seen_at = None
        self._last_time = None
        self._frame_size = None


_default_tracker = CropTracker()


def generate_crop(
    pred: Rect | None,
    padding: Optional[Tuple[float, float]],
    *,
    frame_size: tuple[int, int],
    now: float | None = None,
) -> Rect:
    """Compatibility helper; new runs should own a CropTracker instance."""
    return _default_tracker.generate_crop(pred, padding, frame_size=frame_size, now=now)
