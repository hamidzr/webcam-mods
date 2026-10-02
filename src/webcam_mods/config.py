"""Bundled assets and compatibility access to runtime environment settings."""

from pathlib import Path
from webcam_mods.settings import StartupSettings, load_settings

data_root = Path(__file__).parent / "data"
NO_SIGNAL_IMAGE = data_root / "nosignal.jpg"
DEFAULT_BG_IMAGE = data_root / "bg.jpg"
ERROR_IMAGE = data_root / "errors" / "xp.jpg"


def __getattr__(name: str) -> object:
    # legacy Python callers can still read existing uppercase configuration names
    if name.lower() in StartupSettings.__dataclass_fields__:
        return getattr(load_settings(), name.lower())
    raise AttributeError(name)
