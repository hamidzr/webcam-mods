# Webcam Mods

Tested on Arch Linux.

Checkout my other repository for some ffmpeg-only solutions [here](https://github.com/hamidzr/scripts/tree/master/ffmpeg)

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

### Padding

Interactively pad your camera output with arrow keys `alt+arrowkeys` while keeping the output
framesize fixed.

## Installation

You might need to include `src` directory in your `$PYTHONPATH`

### Dependencies

Python dependencies are listed in `Pipfile`. Install them using [Pipenv](https://pipenv-fork.readthedocs.io/en/latest/)

System dependencies:

- v4l2loopback


## Upgrading

If you run into an issue upgrading try removing the old config file at `.webcam.conf`

## TODO

house cleaning:
- clean and reorganize the code
- set up a code formatter
- set up a language server for development with Vim and VSCode
- replace the facetracking model with mediapipe
- move the config file to `$XDG_CONFIG_HOME`

features:
- more stable edges for person segmentation
- zoom support
- MacOS and Windows support?

bugs:
- bug what?

ideas from https://github.com/fangfufu/Linux-Fake-Background-Webcam/blob/master/fake.py#L285
- post processing, sigmoid
- on demand processing

## Contact

Are you interested in helping improve this tool (hint: look at the TODO section)?
Are you looking for a specific feature, or have you found a bug?
Use [GitHub Issues](https://github.com/hamidzr/webcam-mods/issues/new) to reach out to me.


## Credits

- [Google/mediapipe](https://github.com/google/mediapipe) for their selfie segmentation model.
- There are more, I'll add them later..
