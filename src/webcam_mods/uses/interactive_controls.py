"""Optional keyboard adapter; callbacks enqueue changes without mutating settings."""

from typing import Any

from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.session import Command, RunSession
from webcam_mods.utils.cli_input import StdinControls

JUMP = 10


class KeyboardControls:
    def __init__(
        self, session: RunSession, settings: StartupSettings | None = None
    ) -> None:
        self.session = session
        self.settings = settings or load_settings()
        self.keys: set[Any] = set()
        self.listener = None

    def start(self) -> None:
        if self.listener is not None:
            return
        if not (self.settings.pan_control or self.settings.padding_control):
            return
        from pynput.keyboard import Key, Listener

        self.key_type = Key
        self.listener = Listener(on_press=self.on_press, on_release=self.on_release)
        try:
            self.listener.start()
        except BaseException as error:
            try:
                self.stop()
            except Exception as cleanup_error:
                error.add_note(f"keyboard cleanup failed: {cleanup_error}")
            raise

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
        if self.settings.pan_control and Key.ctrl in self.keys:
            if Key.shift in self.keys:
                self.session.submit(Command("resize", x, y))
            else:
                self.session.submit(Command("move", -x, -y))
        if self.settings.padding_control and Key.alt in self.keys:
            self.session.submit(Command("pad", x, y))

    def on_release(self, key: Any) -> None:
        self.keys.discard(key)

    def stop(self) -> None:
        listener, self.listener = self.listener, None
        try:
            if listener is not None:
                try:
                    listener.stop()
                finally:
                    if listener.ident is not None:
                        listener.join(timeout=1)
        finally:
            self.keys.clear()


class ControlAdapters:
    def __init__(
        self,
        session: RunSession,
        owns_session: bool = False,
        settings: StartupSettings | None = None,
    ) -> None:
        self.session = session
        self.owns_session = owns_session
        self.keyboard = KeyboardControls(session, settings)
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


def create_default_listener(settings: StartupSettings | None = None) -> ControlAdapters:
    settings = settings or load_settings()
    return ControlAdapters(
        RunSession(startup=settings), owns_session=True, settings=settings
    )
