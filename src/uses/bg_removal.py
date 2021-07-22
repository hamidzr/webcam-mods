from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.person_segmentation import color_bg, blur_bg, swap_bg
from uses.crop_cam import shmem, crop
import os.path
from pathlib import Path
import cv2

bg_image = cv2.resize(cv2.imread(f'{Path.cwd()}/data/bg.jpg'), (OUT_WIDTH, OUT_HEIGHT))

def frame_modr(frame):
    # TODO this should be more modular
    frame = crop(frame, OUT_WIDTH, OUT_HEIGHT, shmem[0], shmem[1])
    frame = swap_bg(frame, bg_image)
    return frame


live_loop(frame_modr)
