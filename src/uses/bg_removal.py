from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.person_segmentation import color_bg, blur_bg, noop
from uses.crop_cam import frame_modr as crop_modr
import os.path

def frame_modr(frame):
    # frame = mask(frame, OUT_WIDTH, OUT_HEIGHT)
    # TODO this should be more modular
    frame = crop_modr(frame)
    frame = color_bg(frame)
    return frame


live_loop(frame_modr)
