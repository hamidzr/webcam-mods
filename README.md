# Webcam Mods

Tested on Arch Linux.


Checkout my other repository for some ffmpeg-only solutions [here](https://github.com/hamidzr/scripts/tree/master/ffmpeg)

Find installation and a work-in-progress demo here: [https://youtu.be/idp7ei-pF40](https://youtu.be/idp7ei-pF40) (recorded using version [cf765](https://github.com/hamidzr/webcam-mods/commit/cf7651fe08caea024e4cc9f33540fa4bd2a2eb82))

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

### Padding

Interactively pad your camera output with arrow keys `alt+arrowkeys` while keeping the output
framesize fixed.

#### Record & Replay

Record and replay your camera feed on the fly. While you're in any of the other modes above
press `r` to start recording and press `p` to stop recording and start replaying in a loop.

_For entertainment purposes only_

## Installation

Depending on your python setup you might need to include the current directory in your `$PYTHONPATH`.
To do so run the following: `export PYTHONPATH="$PYTHONPATH:./"`

### Dependencies

System dependencies:

- Python 3.8: Some installation options include [pyenv](https://github.com/pyenv/pyenv) [conda](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html)
- [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- A virtual camera device: [Linux] v4l2loopback [Windows or MacOS] [OBS](https://obsproject.com/).
Follow [pyvirtualcam's instructions](https://github.com/letmaik/pyvirtualcam#supported-virtual-cameras) to set this up.


If you're just interested in running the released features install the project as a python package using:
`pip install git+https://github.com/hamidzr/webcam-mods@master` (python 3.8 environment) and access the
offered features using `webcam_mods` CLI. This would replace the `entry.py` mentions in the rest of 
the documentation.

Python dependencies are listed in `Pipfile`. Install them using [Pipenv](https://pipenv-fork.readthedocs.io/en/latest/) (recommended)

[WARN] If you don't use `pipenv` for dependency and virtual env management you'd need to find replacements wherever you
see `pipenv` mentioned => `grep -R pipenv .`

1. create a virtual environment: `pipenv --python 3.8`
2. activate it `pipenv shell`
3. install the dependencies `pipenv install --skip-lock`

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
calling `python webcam_mods/entry.py --help` from within the `src` directory .

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
