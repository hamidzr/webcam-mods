from loopback import live_loop, IN_HEIGHT, IN_WIDTH
from mods.video_mods import crop, pad_inward_centered, is_crop_valid
from pynput.keyboard import Key, Listener
from mods.record_replay import engage
import os.path

cur_keys = set()

class Config:
    def __init__(self, path = '.webcam.conf'):
        self.crop_dims = [IN_WIDTH, IN_HEIGHT] # dimenstions: w, h
        self.reset_dependents()
        self._path = path
        if os.path.isfile(path):
            conf = self.load(path)
            self.crop_dims = conf['crop_dims']
            self.crop_pos = conf['crop_pos']
            self.pad_size = conf['pad_size']
        print("starting with config", self)

    def reset_dependents(self):
        self.crop_pos = [0, 0] # x1, h1
        self.pad_size = [0, 0] # horizontal, vertical


    def load(self, path: str = None):
        path = path or self._path
        with open(path, 'r') as f:
            line = f.readline()
            # if line != '':
            vals = [int(x) for x in line.split(',')]
            assert len(vals) == 6
            return {'crop_dims': vals[0:2], 'crop_pos': vals[2:4], 'pad_size': vals[4:6]}

    def persist(self, path: str = None):
        path = path or self._path
        vals = [*self.crop_dims, *self.crop_pos, *self.pad_size]
        with open(path, 'w+') as f:
            f.write(','.join([str(x) for x in vals]))

    def to_dict(self):
        return {'crop_dims': self.crop_dims, 'crop_pos': self.crop_pos, 'pad_size': self.pad_size}

    def __repr__(self):
        return str(self.to_dict())

cf = Config('.webcam.conf')

JUMP = 10  # pixels


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


key_listener = Listener(on_press=on_press, on_release=on_release)
key_listener.start()


def frame_modr(frame):
    # print(cf)
    frame = crop(frame, cf.crop_dims[0], cf.crop_dims[1], x1=cf.crop_pos[0], y1=cf.crop_pos[1])
    frame = pad_inward_centered(frame, horizontal=cf.pad_size[0], vertical=cf.pad_size[1], color=0)
    return engage(frame)


if __name__ == '__main__':
    live_loop(frame_modr)
