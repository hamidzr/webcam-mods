from typing import List
from src.config import IN_HEIGHT, IN_WIDTH
from sys import stderr
import os.path
import json

class Config:
    def __init__(self, path: str = '.webcam.conf'):
        self.crop_dims: List[int] = [IN_WIDTH, IN_HEIGHT] # dimenstions: w, h
        self.reset_dependents()
        self._path: str = path
        print("starting with config", self) # TODO use a logger

    def reset_dependents(self):
        self.crop_pos: List[int] = [0, 0] # x1, h1
        self.pad_size: List[int] = [0, 0] # horizontal, vertical

    @classmethod
    def from_disk(cls, path: str = None):
        if path is not None:
            c = cls(path=path)
        else:
            c = cls()
        c.load(path)
        return c

    def load(self, path: str = None):
        conf = self.read(path)
        if conf is not None:
            self.crop_dims = conf['crop_dims']
            self.crop_pos = conf['crop_pos']
            self.pad_size = conf['pad_size']

    def read(self, path: str = None):
        path = path or self._path
        if not os.path.isfile(path):
            print(f'config file not found at {path}', file=stderr)
            return None
        try:
            with open(path, 'r') as f:
                conf = json.loads(f.read())
                return conf
        except:
            print(f'issue reading the config file at {path}', file=stderr)
            return None



    def persist(self, path: str = None):
        path = path or self._path
        with open(path, 'w+') as f:
            f.write(json.dumps(self.to_dict()))

    def to_dict(self):
        return {'crop_dims': self.crop_dims, 'crop_pos': self.crop_pos, 'pad_size': self.pad_size}

    def __repr__(self):
        return str(self.to_dict())
