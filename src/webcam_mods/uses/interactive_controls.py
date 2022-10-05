from webcam_mods.config import IN_HEIGHT, IN_WIDTH, LISTEN_ALT, LISTEN_CTRL
from webcam_mods.mods.video_mods import is_crop_valid
from webcam_mods.utils.cli_input import inp
from loguru import logger
from pynput.keyboard import Key, Listener
from webcam_mods.utils.config import Config

cur_keys = set()
JUMP = 10  # pixels
target_keys = set()  # currently listening keys
# avoid always engaging these controls
if LISTEN_CTRL:
    target_keys.add(Key.ctrl)
if LISTEN_ALT:
    target_keys.add(Key.alt)

cf = Config()


def on_press(key):
    global cf, cur_keys
    cur_keys.add(key)
    if not any(key in cur_keys for key in target_keys):
        return
    if Key.ctrl in cur_keys:
        if Key.shift in cur_keys:  # control crop dimensions
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
        else:  # control crop position
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
    if Key.alt in cur_keys:  # control frame padding
        if key == Key.right:
            cf.pad_size[0] = min(cf.crop_dims[0], cf.pad_size[0] + JUMP)
        elif key == Key.left:
            cf.pad_size[0] = max(0, cf.pad_size[0] - JUMP)
        elif key == Key.up:
            cf.pad_size[1] = min(cf.crop_dims[1], cf.pad_size[1] + JUMP)
        elif key == Key.down:
            cf.pad_size[1] = max(0, cf.pad_size[1] - JUMP)

    cf.persist()  # TODO reduce unnecessary writes


def process_input():
    if inp[0] == "reset":
        cf.reset()
        logger.info("config reset")
        inp[0] = ""


def on_release(key):
    if key in cur_keys:
        cur_keys.remove(key)


key_listener = Listener(on_press=on_press, on_release=on_release)
