from src.input.video_dev import Webcam
from src.mods.camera_motion import generate_crop
from src.loopback import live_loop
from src.mods.person_segmentation import color_bg, blur_bg, swap_bg
from src.mods.record_replay import engage
from pathlib import Path
from src.mods.video_mods import brighten as brighten_mod, crop_rect, pad_inward_centered, crop
from src.mods.mp_face import abs_boundingbox, predict
from src.config import DEFAULT_BG_IMAGE, IN_WIDTH, IN_HEIGHT
from src.uses.interactive_controls import cf
from src.output.gui import GUI
import cv2
import os
import typer

app = typer.Typer()


def crop_pad(func):
    def mod(frame):
        frame = crop(frame, cf.crop_dims[0], cf.crop_dims[1], x1=cf.crop_pos[0], y1=cf.crop_pos[1])
        frame = pad_inward_centered(frame, horizontal=cf.pad_size[0], vertical=cf.pad_size[1], color=0)
        return func(frame)
    return mod

def record_replay(func):
    def mod(frame):
        return func(engage(frame))
    return mod

@crop_pad
@record_replay
def base_mod(frame):
    return frame

def base_mod_dec(func):
    @crop_pad
    @record_replay
    def mod(frame):
        return func(frame)
    return mod


@app.command()
def crop_cam():
    """
    Basic mods with interactive camera control
    """
    live_loop(base_mod)


@app.command()
def bg_color(color: int = 192):
    """
    Basic controls + a solid color background
    """
    @base_mod_dec
    def frame_mod(frame):
        frame = color_bg(frame, color)
        return frame
    live_loop(frame_mod)


@app.command()
def bg_swap(img_path: str = DEFAULT_BG_IMAGE):
    """
    Basic controls + a swapped background with the provided image
    """
    bg_image = cv2.imread(str(Path(img_path)))
    @base_mod_dec
    def frame_mod(frame):
        resized_bg = crop(bg_image, cf.crop_dims[0], cf.crop_dims[1])
        return swap_bg(frame, resized_bg)
    live_loop(frame_mod)


@app.command()
def bg_blur(kernel_size: int = 31):
    """
    Basic controls + a blurred background.
    kernel-size is in pixels and needs to be an odd number.
    """
    @base_mod_dec
    def frame_mod(frame):
        return blur_bg(frame, kernel_size)
    live_loop(frame_mod)


@app.command()
def brighten(level=30):
    """
    Brighten the video feed by LEVEL
    """
    @base_mod_dec
    def frame_mod(frame):
        return brighten_mod(frame, int(level))
    live_loop(frame_mod)


@app.command()
def track_face():
    """
    Crop around the first detected face.
    """
    def frame_mod(frame):
        # fh, fw, _ = frame.shape
        bbox = predict(frame)
        if bbox is None:
            frame = crop(frame, cf.crop_dims[0], cf.crop_dims[1], x1=cf.crop_pos[0], y1=cf.crop_pos[1])
        else:
            # crop_box = (int(bbox.width*fw), int(bbox.height*fh), int(bbox.xmin*fw), int(bbox.ymin*fh))
            # frame = crop(frame, crop_box[0], crop_box[1], crop_box[2], crop_box[3])
            pred_box = abs_boundingbox(frame, bbox)
            frame = crop_rect(frame, generate_crop(pred_box))
        return frame
    # frame_in = Webcam(width=IN_WIDTH, height=IN_HEIGHT)
    live_loop(mod=frame_mod, interactive_listener=None)

@app.command()
def share_screen(top: int = 0, left: int = 0,
                 width: int = 640, height: int = 480,
                 output: str = 'virtual-cam'):
    """
    Share a portion of the screen.
    """
    from src.input.screen import Screen
    screen = Screen(top=top, left=left, width=width, height=height)
    if output == GUI.id:
        gui = GUI(width=width, height=height)
        live_loop(fIn=screen, fOut=gui)
    else:
        live_loop(fIn=screen)
if __name__ == "__main__":
    app()
