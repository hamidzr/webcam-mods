from loopback import live_loop
from mods.person_segmentation import color_bg, blur_bg, swap_bg
from mods.record_replay import engage
from pathlib import Path
from src.mods.video_mods import resize_and_pad, pad_inward_centered, crop
from uses.interactive_controls import cf
import cv2
import os.path
import typer

app = typer.Typer()

DEFAULT_BG_IMAGE = f'{Path.cwd()}/data/bg.jpg'
ON_DEMAND = os.getenv('ON_DEMAND') == 'True'


def base_mod(frame):
    frame = crop(frame, cf.crop_dims[0], cf.crop_dims[1], x1=cf.crop_pos[0], y1=cf.crop_pos[1])
    frame = pad_inward_centered(frame, horizontal=cf.pad_size[0], vertical=cf.pad_size[1], color=0)
    return engage(frame)


@app.command()
def crop_cam():
    """
    Basic mods with interactive camera control
    """
    live_loop(base_mod, on_demand=ON_DEMAND)


@app.command()
def bg_color(color: int = 192):
    """
    Basic controls + a solid color background
    """
    def frame_mod(frame):
        frame = base_mod(frame)
        frame = color_bg(frame, color)
        return frame
    live_loop(frame_mod, on_demand=ON_DEMAND)


@app.command()
def bg_swap(img_path: str = DEFAULT_BG_IMAGE):
    """
    Basic controls + a swapped background with the provided image
    """
    bg_image = cv2.imread(img_path)
    def frame_mod(frame):
        frame = base_mod(frame)
        resized_bg = crop(bg_image, cf.crop_dims[0], cf.crop_dims[1])
        return swap_bg(frame, resized_bg)
    live_loop(frame_mod)


@app.command()
def bg_blur(kernel_size: int = 31):
    """
    Basic controls + a blurred background.
    kernel-size is in pixels and needs to be an odd number.
    """
    def frame_mod(frame):
        frame = base_mod(frame)
        return blur_bg(frame, kernel_size)
    live_loop(frame_mod, on_demand=ON_DEMAND)


if __name__ == "__main__":
    app()
