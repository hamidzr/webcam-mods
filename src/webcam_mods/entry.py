from pathlib import Path
from webcam_mods.config import DEFAULT_BG_IMAGE
from webcam_mods.loopback import live_loop
from webcam_mods.mods.camera_motion import generate_crop
from webcam_mods.mods.record_replay import engage
from webcam_mods.mods.video_mods import (
    brighten as brighten_mod,
    crop_rect,
    pad_inward_centered,
    crop,
)
from webcam_mods.output.gui import GUI
from webcam_mods.uses.interactive_controls import cf, process_input as interactive_cli
import cv2
import typer

app = typer.Typer()


def crop_pad(func):
    def mod(frame):
        frame = crop(
            frame,
            cf.crop_dims[0],
            cf.crop_dims[1],
            x1=cf.crop_pos[0],
            y1=cf.crop_pos[1],
        )
        frame = pad_inward_centered(
            frame, horizontal=cf.pad_size[0], vertical=cf.pad_size[1], color=0
        )
        return func(frame)

    return mod


def record_replay(func):
    def mod(frame):
        return func(engage(frame))

    return mod


@crop_pad
@record_replay
def base_mod(frame):
    interactive_cli()
    return frame


def base_mod_dec(func):
    def mod(frame):
        return func(base_mod(frame))

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
    from webcam_mods.mods.person_segmentation import color_bg

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
    from webcam_mods.mods.person_segmentation import swap_bg

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
    from webcam_mods.mods.person_segmentation import blur_bg

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
def track_face(
    x_padding: float = 1.5,
    y_padding: float = 2,
    blur: bool = False,
    blur_kernel_size: int = 31,
):
    """
    Crop around the first detected face.
    x-padding and y-padding: padding ratios.
    """
    from webcam_mods.mods.mp_face import abs_boundingbox, predict

    if blur:
        from webcam_mods.mods.person_segmentation import blur_bg

    def frame_mod(frame):
        # fh, fw, _ = frame.shape
        bbox = predict(frame)
        if bbox is None:
            frame = crop(
                frame,
                cf.crop_dims[0],
                cf.crop_dims[1],
                x1=cf.crop_pos[0],
                y1=cf.crop_pos[1],
            )
        else:
            # crop_box = (int(bbox.width*fw), int(bbox.height*fh), int(bbox.xmin*fw), int(bbox.ymin*fh))
            # frame = crop(frame, crop_box[0], crop_box[1], crop_box[2], crop_box[3])
            pred_box = abs_boundingbox(frame, bbox)
            frame = crop_rect(frame, generate_crop(pred_box, (x_padding, y_padding)))

        return frame if not blur else blur_bg(frame, blur_kernel_size)

    live_loop(mod=frame_mod, interactive_listener=None)


@app.command()
def share_screen(
    top: int = 0,
    left: int = 0,
    width: int = 640,
    height: int = 480,
    output: str = "virtual-cam",
):
    """
    Share a portion of the screen.
    """
    from webcam_mods.input.screen import Screen

    screen = Screen(top=top, left=left, width=width, height=height)
    if output == GUI.id:
        gui = GUI(width=width, height=height)
        live_loop(fIn=screen, fOut=gui)
    else:
        live_loop(fIn=screen)


@app.command()
def test_loop():
    """
    For testing purposes.
    """
    live_loop()


if __name__ == "__main__":
    app()
