"""Bounded, run-owned recording and replay."""

from webcam_mods.utils.video import Frame


class Recorder:
    def __init__(self, max_bytes: int = 256 * 1024 * 1024) -> None:
        if max_bytes <= 0:
            raise ValueError("recording limit must be positive")
        self.max_bytes = max_bytes
        self.frames: list[Frame] = []
        self.size_bytes = 0
        self.index = 0
        self.recording = False
        self.replaying = False

    def command(self, action: str) -> bool:
        if action == "record":
            self.frames.clear()
            self.size_bytes = self.index = 0
            self.recording, self.replaying = True, False
        elif action == "stop":
            self.recording = self.replaying = False
        elif action == "replay":
            if not self.frames:
                return False
            self.index = 0
            self.recording, self.replaying = False, True
        else:
            return False
        return True

    def engage(self, frame: Frame) -> Frame:
        if self.recording:
            if self.size_bytes + frame.nbytes > self.max_bytes:
                self.recording = False
            else:
                self.frames.append(frame.copy())
                self.size_bytes += frame.nbytes
        elif self.replaying:
            result = self.frames[self.index].copy()
            self.index = (self.index + 1) % len(self.frames)
            return result
        return frame

    def close(self) -> None:
        self.frames.clear()
        self.size_bytes = self.index = 0
        self.recording = self.replaying = False
