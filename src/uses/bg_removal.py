from src.mods.video_mods import resize_and_pad, pad_inward_centered
from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.person_segmentation import color_bg, blur_bg, swap_bg
from uses.crop_cam import cf, crop
import os.path
from pathlib import Path
import cv2

bg_image = cv2.imread(f'{Path.cwd()}/data/bg.jpg')
# bg_image = cv2.resize(, (OUT_WIDTH, OUT_HEIGHT))

def frame_modr(frame):
    # TODO this should be more modular
    frame = crop(frame, cf.crop_dims[0], cf.crop_dims[1], x1=cf.crop_pos[0], y1=cf.crop_pos[1])
    resized_bg = resize_and_pad(bg_image, cf.crop_dims[0], cf.crop_dims[1]) # TODO we probably want to resize and avoid adding padding.
    frame = pad_inward_centered(frame, horizontal=cf.pad_size[0], vertical=cf.pad_size[1], color=0)
    frame = swap_bg(frame, resized_bg)
    return frame


live_loop(frame_modr)
