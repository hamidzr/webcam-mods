"""Monotonic frame cadence shared by every output backend."""

import math
import time
from collections.abc import Callable


class FramePacer:
    def __init__(
        self,
        fps: float,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("fps must be finite and positive")
        self.period = 1 / fps
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_tick = self._clock()

    def wait(
        self,
        *,
        interval: float | None = None,
        process_events: Callable[[], bool] | None = None,
    ) -> bool:
        """Count processing toward each period; skip missed deadlines without bursts.

        Event callbacks return False to stop and are polled at most 20 ms apart.
        """
        deadline = self._last_tick + (self.period if interval is None else interval)
        while True:
            if process_events is not None and not process_events():
                return False
            now = self._clock()
            remaining = deadline - now
            if remaining <= 0:
                self._last_tick = max(deadline, now)
                return True
            self._sleep(min(remaining, 0.02) if process_events else remaining)
