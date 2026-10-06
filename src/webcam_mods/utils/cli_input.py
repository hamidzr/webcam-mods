"""Explicit, stoppable stdin adapter for queued session commands."""

import os
import select
import sys
from threading import Event, Thread
from typing import Callable, TextIO

from webcam_mods.session import Command


class StdinControls:
    def __init__(
        self, submit: Callable[[Command], bool], stream: TextIO | None = None
    ) -> None:
        self.submit = submit
        self.stream = stream if stream is not None else sys.stdin
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            fd = self.stream.fileno()
        except AttributeError, OSError, ValueError:
            return
        self._stop.clear()
        self._thread = Thread(target=self._read, args=(fd,), daemon=True)
        self._thread.start()

    def _read(self, fd: int) -> None:
        pending = b""
        discarding = False
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    continue
                data = os.read(fd, 4096)
                if not data:
                    if pending and not discarding:
                        self._submit_line(pending)
                    return
                parts = data.split(b"\n")
                for index, part in enumerate(parts):
                    if not discarding:
                        pending += part
                        if len(pending) > 4096:
                            pending = b""
                            discarding = True
                    if index < len(parts) - 1:
                        if not discarding:
                            self._submit_line(pending)
                        pending = b""
                        discarding = False
            except OSError, ValueError:
                return

    def _submit_line(self, line: bytes) -> None:
        action = line.decode("utf-8", errors="replace").strip()
        if action in ("reset", "record", "stop", "replay"):
            self.submit(Command(action))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
