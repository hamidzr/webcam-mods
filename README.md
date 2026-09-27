# Webcam Mods

Tested on Arch Linux.


Checkout my other repository for some ffmpeg-only solutions [here](https://github.com/hamidzr/scripts/tree/master/ffmpeg)

Find installation and a work-in-progress demos here:
 - Latest demo [https://youtu.be/FfD7lu_A1Dw](https://youtu.be/FfD7lu_A1Dw) (recorded on commit `8f08bc68` on Jan 2022). It showcases some of the main features.
 - Archived demo [https://youtu.be/idp7ei-pF40](https://youtu.be/idp7ei-pF40) (recorded using version [cf765](https://github.com/hamidzr/webcam-mods/commit/cf7651fe08caea024e4cc9f33540fa4bd2a2eb82))

## Included Mods

### Face Tracking

Setup your webcam to focus and follow your face by cropping and resizing the frames it receives from
your main webcam.

### Person Segmentation

Separate the people in the frame from the background using a fast real-time prediction model. The model
outputs a mask values between 0 to 1.
We have mods based on this to swap the background with:

- a solid color
- another image
- blurred version of the input frame (aka blur my background)

### Cropping

Interactively move your camera around with arrow keys `ctrl+arrowkeys`
Resize the cropped frame using `ctrl+shift+arrowkeys`
You can disable this control by defining the environment variable `PAN_CONTROL=False`.

### Padding

Interactively pad your camera output with arrow keys `alt+arrowkeys` while keeping the output
framesize fixed.
You can disable this control by defining the environment variable `PADDING_CONTROL=False`.

#### Record & Replay

Record and replay your camera feed on the fly. While you're in any of the other modes above
press `r` to start recording and press `p` to stop recording and start replaying in a loop.

_For entertainment purposes only_

## Installation

### Dependencies

System dependencies:

- Python 3.13 or 3.14 and [uv](https://docs.astral.sh/uv/)
- [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- A virtual camera device: [Linux] v4l2loopback [Windows or MacOS] [OBS](https://obsproject.com/).
Follow [pyvirtualcam's instructions](https://github.com/letmaik/pyvirtualcam#supported-virtual-cameras) to set this up.

### macOS virtual camera setup

Install OBS 30 or newer. Open OBS once and select **Start Virtual Camera**.
If OBS says the virtual camera is not installed, enable its camera extension in
**System Settings > General > Login Items & Extensions > Camera Extensions**,
then restart OBS and try again. Select **Stop Virtual Camera** and close OBS.
After this one-time setup, `webcam_mods` sends
frames directly to the OBS Virtual Camera; OBS does not need to stay open.

On macOS 13 or newer, use OBS 30 or newer. This project installs
`pyvirtualcam` 0.15 or newer.
The OBS device remains installed when `webcam_mods` stops; start and stop
`webcam_mods` to control the video feed.


Install dependencies from the locked project environment:

```sh
uv sync --python 3.14
uv run python -m webcam_mods.models
uv run webcam_mods --help
```

Run `make check` for static checks and `make test` for MediaPipe smoke tests.

Run modes with `uv run webcam_mods <command>`. For example,
`uv run webcam_mods crop-cam`. On Linux, install the video device dependencies
with `uv sync --extra linux --python 3.14`.

Face tracking and background effects use MediaPipe Tasks 0.10.35. Version
1.0.1 aborts while initializing its face detector on macOS ARM64, even with
the CPU delegate ([upstream issue](https://github.com/google-ai-edge/mediapipe/issues/6356),
[source fix awaiting a release](https://github.com/google-ai-edge/mediapipe/commit/32d0e5b1317be070083c630240b274218ce9ed52)).
The two MediaPipe models are downloaded once into `~/.cache/webcam-mods/models`
and verified with SHA-256; later runs use the cached copies.

## Setting up a virtual webcam device on Linux

On Linux once you have the v4l2 module installed you can run `sudo make add-video-dev` to add a virtual
camera device with some pre-set flags.

Which executes the following to remove and re-insert the module.
You might need root access for this.

```
pkill gst-launch &> /dev/null || true
rmmod v4l2loopback &> /dev/null || true
modprobe v4l2loopback devices=1 max_buffers=2 exclusive_caps=1 video_nr=10 card_label="v4l2-cam"
```



## Upgrading

If you run into an issue upgrading try removing the old config file at `.webcam.conf`

## Running the Mods

After you've successfully followed installation steps, you can run the different modes by
calling `uv run webcam_mods --help` from the project directory.

## Settings

When you use the interactive controls to move the camera around the resulting parameters are saved in
a text file to your disk which is by default located at `$HOME/.webcam-mods.conf`

### Environment Variables

Environment variables are used to configure different parameters. Read more about how to set or
persist them [here](https://lmgtfy.app/?q=how+to+set+environment+variables+in+linux)
These are mostly defined in the `config.py` file. To see their default values take a look at that
file.

- `VIDEO_IN` & `VIDEO_OUT`:
If you have multiple video input devices, aka webcams, you can pick the one you want by providing its
index through by setting the `VIDEO_IN` environment variable. eg `export VIDEO_IN=0`. Same if you have
multiple output devices.

- `MAX_OUT_FPS`: [Default: 30] set an upper limit for output FPS.

- `IN_WIDTH` [Default: 640], `IN_HEIGHT` [Default: 480]: Your video input device likely support
multiple resolution and FPS settings use these env variables to pick and persist the one you want.
`v4l2-ctl` can list out the different settings your webcam driver supports: `v4l2-ctl --list-formats-ext | less`

- `OUT_WIDTH` [Default: 640], `OUT_HEIGHT` [Default: 480]: similar to `IN_HEIGHT` and `OUT_HEIGHT`
but for your output device.

- `ON_DEMAND` [Default: False, Linux only]: set to True to lower cpu usage while the output camera device isn't actively
used.

- `IN_FORMAT`: input video format. This dictates the requested video format from the input video device (webcam)
which directly affects picture quality and FPS. If you're looking to get higher a resolution or FPS
out of your webcam it's crucial to inspect your camera and driver capabilities and set the appropriate format here.

- `PAN_CONTROL` [Default True]: Set to False to disable panning/resizing with `ctrl+arrowkeys/ctrl+shift+arrowkeys`.

- `PADDING_CONTROL` [Default True]: Set to False to disable padding with `alt+arrowkeys`.



## TODO

house cleaning:
- clean and reorganize the code
- set up a code formatter
- set up a language server for development with Vim and VSCode
- replace the facetracking model with mediapipe
- move the config file to `$XDG_CONFIG_HOME`
- cli support for settings currently supported by env variables

features:
- [x] more stable edges for person segmentation
- [ ] support other video feed formats from webcam eg mjpeg, h264 for higher resolution
- including headphones in the mask 
- visualize interactive camera control settings
- [x] zoom support. done through resizing.
  - the controls could be more intuitive
- [x] MacOS support
  - disable ionotify. quartz install
- [x] Windows support? should be there with `pyvirtualcam`
- [ ] hot swap inputs
- [~] add screen as an input
- [ ] convert/migrate env variables to cli arguments
- [ ] brightness control. (and hue, saturation?)
- [~] smooth bounding box tracking (for facetracking and more)
  - camera/crop size change transition
- [ ] overlay on top of video

bugs:
- bug what?

a demo video showcasing the features

## Contact

Are you interested in helping improve this tool (hint: look at the TODO section)?
Are you looking for a specific feature, or have you found a bug?
Use [GitHub Issues](https://github.com/hamidzr/webcam-mods/issues/new) to reach out to me.


## Credits

- [Google/mediapipe](https://github.com/google/mediapipe) for their selfie segmentation model.
- [fangfufu/Linux-Fake-Background-Webcam](https://github.com/fangfufu/Linux-Fake-Background-Webcam)
For mask post processing and automatic ondemand pause and restart.
- [letmaik/pyvirtualcam](https://github.com/letmaik/pyvirtualcam)
