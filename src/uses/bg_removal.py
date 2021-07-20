from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.person_segmentation import color_bg, blur_bg
import os.path

def frame_modr(frame):
    # frame = mask(frame, OUT_WIDTH, OUT_HEIGHT)
    frame = color_bg(frame)
    return frame


live_loop(frame_modr)
