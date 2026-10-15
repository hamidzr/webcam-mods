"""Thread-safe frame rate and duration meters for live session stats."""

from collections import deque
import threading
import time
from typing import Callable


class RateMeter:
    """Frames per second and mean duration over a short sliding window."""

    def __init__(
        self, window: float = 2.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._window, self._clock = window, clock
        self._lock = threading.Lock()
        self._ticks: deque[tuple[float, float | None]] = deque(maxlen=512)

    def tick(self, duration: float | None = None) -> None:
        with self._lock:
            self._ticks.append((self._clock(), duration))

    def snapshot(self) -> tuple[float | None, float | None]:
        """Return (fps, mean duration seconds); None until there is enough data."""
        with self._lock:
            now = self._clock()
            while self._ticks and now - self._ticks[0][0] > self._window:
                self._ticks.popleft()
            ticks = list(self._ticks)
        fps = None
        if len(ticks) >= 2 and ticks[-1][0] > ticks[0][0]:
            fps = (len(ticks) - 1) / (ticks[-1][0] - ticks[0][0])
        durations = [duration for _, duration in ticks if duration is not None]
        return fps, sum(durations) / len(durations) if durations else None
