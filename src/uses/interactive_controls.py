import os.path
from sys import stderr
from src.config import IN_HEIGHT, IN_WIDTH
from src.mods.video_mods import is_crop_valid
from pynput.keyboard import Key, Listener
from typing import List
import json

cur_keys = set()
JUMP = 10  # pixels

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

cf = Config.from_disk()

def on_press(key):
    global cf, cur_keys
    cur_keys.add(key)
    target_keys = [Key.ctrl, Key.alt]
    if not any(key in cur_keys for key in target_keys):
        return
    if (Key.ctrl in cur_keys):
        if (Key.shift in cur_keys): # control crop dimensions
            if key == Key.right:
                cf.crop_dims[0] += JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_dims[0] -= JUMP
            elif key == Key.left:
                cf.crop_dims[0] -= JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_dims[0] += JUMP
            elif key == Key.up:
                cf.crop_dims[1] += JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_dims[1] -= JUMP
            elif key == Key.down:
                cf.crop_dims[1] -= JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_dims[1] += JUMP
        else: # control crop position
            # left and right are reversed to compensate for mirror effects
            if key == Key.right:
                cf.crop_pos[0] -= JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_pos[0] += JUMP
            elif key == Key.left:
                cf.crop_pos[0] += JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_pos[0] -= JUMP
            elif key == Key.up:
                cf.crop_pos[1] -= JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_pos[1] += JUMP
            elif key == Key.down:
                cf.crop_pos[1] += JUMP
                if not is_crop_valid((IN_WIDTH, IN_HEIGHT), cf.crop_pos, cf.crop_dims):
                    cf.crop_pos[1] -= JUMP
    if (Key.alt in cur_keys): # control frame padding
        if key == Key.right:
            cf.pad_size[0] = max(0, cf.pad_size[0] - JUMP)
        elif key == Key.left:
            cf.pad_size[0] = min(cf.crop_dims[0], cf.pad_size[0] + JUMP)
        elif key == Key.up:
            cf.pad_size[1] = max(0, cf.pad_size[1] - JUMP)
        elif key == Key.down:
            cf.pad_size[1] = min(cf.crop_dims[1], cf.pad_size[1] + JUMP)

    cf.persist() # TODO reduce unnecessary writes


def on_release(key):
    if key in cur_keys:
        cur_keys.remove(key)


# TODO avoid always engaging these
key_listener = Listener(on_press=on_press, on_release=on_release)
