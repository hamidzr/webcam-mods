"""Run-owned controls; mutations apply on the processing thread between frames."""

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
from typing import Literal

import numpy as np

from webcam_mods.mods.record_replay import Recorder
from webcam_mods.mods.video_mods import crop, pad_inward_centered
from webcam_mods.utils.config import Config
from webcam_mods.settings import StartupSettings


@dataclass(frozen=True)
class Command:
    action: Literal["reset", "record", "stop", "replay", "move", "resize", "pad"]
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class CommandResult:
    command: Command
    applied: bool
    reason: str = ""


class RunSession:
    def __init__(
        self,
        settings: Config | None = None,
        recording_limit: int = 256 * 1024 * 1024,
        *,
        startup: StartupSettings | None = None,
    ) -> None:
        self.settings = (
            settings
            if settings is not None
            else (
                Config(width=startup.in_width, height=startup.in_height)
                if startup
                else Config()
            )
        )
        self.recorder = Recorder(recording_limit)
        self.commands: Queue[Command] = Queue(maxsize=256)
        self._lock = Lock()
        self._closed = False

    def submit(self, command: Command) -> bool:
        """Return acceptance, not completion; full/closed queues reject commands."""
        with self._lock:
            if self._closed or self.commands.full():
                return False
            self.commands.put_nowait(command)
            return True

    def apply_commands(self) -> list[CommandResult]:
        results = []
        # bounded drain avoids control producers starving frame processing
        for _ in range(self.commands.maxsize):
            try:
                command = self.commands.get_nowait()
            except Empty:
                break
            results.append(self._apply(command))
        return results

    def _apply(self, command: Command) -> CommandResult:
        if command.action in ("record", "stop", "replay"):
            applied = self.recorder.command(command.action)
            return CommandResult(command, applied, "" if applied else "no recording")
        previous = self.settings.to_dict()
        candidate = self.settings.to_dict()
        if command.action == "reset":
            candidate = {
                "crop_dims": [self.settings.width, self.settings.height],
                "crop_pos": [0, 0],
                "pad_size": [0, 0],
            }
        else:
            key = {"move": "crop_pos", "resize": "crop_dims", "pad": "pad_size"}.get(
                command.action
            )
            if key is None:
                return CommandResult(command, False, "unknown command")
            candidate[key] = [
                candidate[key][0] + command.x,
                candidate[key][1] + command.y,
            ]
        if not self.settings.valid(candidate):
            return CommandResult(command, False, "crop or padding outside frame")
        if previous != candidate:
            for key, value in candidate.items():
                setattr(self.settings, key, value)
            try:
                self.settings.persist()
            except OSError:
                for key, value in previous.items():
                    setattr(self.settings, key, value)
                raise
        return CommandResult(command, True)

    def prepare(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        if (width, height) != (self.settings.width, self.settings.height):
            self.settings.width, self.settings.height = width, height
            if not self.settings.valid(self.settings.to_dict()):
                self.settings.reset()
        settings = self.settings.to_dict()
        result = crop(frame, *settings["crop_dims"], *settings["crop_pos"])
        result = pad_inward_centered(result, *settings["pad_size"])
        return self.recorder.engage(result)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            while not self.commands.empty():
                self.commands.get_nowait()
        self.recorder.close()
