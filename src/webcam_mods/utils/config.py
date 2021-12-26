from typing import List
from webcam_mods.config import IN_HEIGHT, IN_WIDTH
import os.path
from pathlib import Path
import json
from loguru import logger

default_config_path = Path.home() / '.webcam-mods.conf'

class Config:
    def __init__(self, path: Path = default_config_path):
        self.reset()
        self._path: str = str(path)
        if self.load(self._path) is None:
            self.persist()

    def reset_dependents(self):
        self.crop_pos: List[int] = [0, 0] # x1, h1
        self.pad_size: List[int] = [0, 0] # horizontal, vertical

    def reset(self):
        self.crop_dims = [IN_WIDTH, IN_HEIGHT]
        self.reset_dependents()

    def load(self, path: str = None):
        conf = self.read(path)
        if conf is not None:
            self.crop_dims = conf['crop_dims']
            self.crop_pos = conf['crop_pos']
            self.pad_size = conf['pad_size']
            logger.info(f'loaded config: {conf}')
        return conf

    def read(self, path: str = None):
        path = path or self._path
        if not os.path.isfile(path):
            logger.warning(f'config file not found at {path}')
            return None
        try:
            with open(path, 'r') as f:
                conf = json.loads(f.read())
                return conf
        except:
            logger.warning(f'issue reading the config file at {path}')
            return None



    def persist(self, path: str = None):
        path = path or self._path
        with open(path, 'w+') as f:
            f.write(json.dumps(self.to_dict()))

    def to_dict(self):
        return {'crop_dims': self.crop_dims, 'crop_pos': self.crop_pos, 'pad_size': self.pad_size}

    def __repr__(self):
        return str(self.to_dict())
