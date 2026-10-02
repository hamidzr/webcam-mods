"""Validated crop settings, loaded explicitly and persisted atomically."""

import json
import os
from pathlib import Path
import tempfile

from webcam_mods.config import IN_HEIGHT, IN_WIDTH

default_config_path = Path.home() / ".webcam-mods.conf"


class Config:
    def __init__(
        self,
        path: Path | None = default_config_path,
        width: int = IN_WIDTH,
        height: int = IN_HEIGHT,
    ) -> None:
        self.width, self.height = width, height
        self._path = Path(path) if path is not None else None
        self.reset()
        if self._path is not None:
            self.load()

    def reset_dependents(self) -> None:
        self.crop_pos = [0, 0]
        self.pad_size = [0, 0]

    def reset(self) -> None:
        self.crop_dims = [self.width, self.height]
        self.reset_dependents()

    def valid(self, conf: dict) -> bool:
        pairs = [conf.get(key) for key in ("crop_dims", "crop_pos", "pad_size")]
        if any(
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(value) is not int for value in pair)
            for pair in pairs
        ):
            return False
        dims, pos, pad = pairs
        return all(
            0 < dims[i] <= size
            and 0 <= pos[i] <= size - dims[i]
            and 0 <= pad[i] < dims[i]
            and pad[i] % 2 == 0
            for i, size in enumerate((self.width, self.height))
        )

    def load(self, path: str | None = None) -> dict | None:
        conf = self.read(path)
        if conf is not None and self.valid(conf):
            self.crop_dims = conf["crop_dims"][:]
            self.crop_pos = conf["crop_pos"][:]
            self.pad_size = conf["pad_size"][:]
            return conf
        return None

    def read(self, path: str | None = None) -> dict | None:
        target = Path(path) if path else self._path
        if target is None:
            return None
        try:
            conf = json.loads(target.read_text())
            return conf if isinstance(conf, dict) else None
        except (OSError, ValueError):
            return None

    def persist(self, path: str | None = None) -> None:
        target = Path(path) if path else self._path
        if target is None:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(self.to_dict(), handle)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def to_dict(self) -> dict[str, list[int]]:
        return {
            "crop_dims": self.crop_dims[:],
            "crop_pos": self.crop_pos[:],
            "pad_size": self.pad_size[:],
        }

    def __repr__(self) -> str:
        return str(self.to_dict())
