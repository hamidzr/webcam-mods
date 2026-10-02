"""Optional keyboard adapter; callbacks enqueue changes without mutating settings."""

from typing import Any

from webcam_mods.config import PADDING_CONTROL, PAN_CONTROL
from webcam_mods.session import Command, RunSession
from webcam_mods.utils.cli_input import StdinControls

JUMP = 10


class KeyboardControls:
    def __init__(self, session: RunSession) -> None:
        self.session = session
        self.keys: set[Any] = set()
        self.listener = None

    def start(self) -> None:
        if not (PAN_CONTROL or PADDING_CONTROL):
            return
        from pynput.keyboard import Key, Listener

        self.key_type = Key
        self.listener = Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()

    def on_press(self, key: Any) -> None:
        self.keys.add(key)
        Key = self.key_type
        directions = {
            Key.right: (JUMP, 0),
            Key.left: (-JUMP, 0),
            Key.up: (0, JUMP),
            Key.down: (0, -JUMP),
        }
        if key not in directions:
            return
        x, y = directions[key]
        if PAN_CONTROL and Key.ctrl in self.keys:
            if Key.shift in self.keys:
                self.session.submit(Command("resize", x, y))
            else:
                self.session.submit(Command("move", -x, -y))
        if PADDING_CONTROL and Key.alt in self.keys:
            self.session.submit(Command("pad", x, y))

    def on_release(self, key: Any) -> None:
        self.keys.discard(key)

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            if self.listener.ident is not None:
                self.listener.join(timeout=1)
            self.listener = None
        self.keys.clear()


class ControlAdapters:
    def __init__(self, session: RunSession, owns_session: bool = False) -> None:
        self.session = session
        self.owns_session = owns_session
        self.keyboard = KeyboardControls(session)
        self.stdin = StdinControls(session.submit)

    def start(self) -> None:
        self.keyboard.start()
        self.stdin.start()

    def apply_commands(self) -> None:
        self.session.apply_commands()

    def stop(self) -> None:
        try:
            self.stdin.stop()
        finally:
            try:
                self.keyboard.stop()
            finally:
                if self.owns_session:
                    self.session.close()


def create_default_listener() -> ControlAdapters:
    return ControlAdapters(RunSession(), owns_session=True)
