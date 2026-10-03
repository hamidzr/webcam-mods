# Webcam Mods

Tested on Arch Linux.

Developer documentation: [current architecture, state, and improvement plan](docs/README.md).


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
enter `record` on stdin to start recording, `stop` to stop, and `replay` to loop
the recording. Empty replay is rejected. Recording stops at a 256 MiB memory limit
by default; configure it with `--recording-limit-mb`. Enter `reset` to reset crop
and padding. Use `--no-controls` to disable keyboard and stdin controls.

_For entertainment purposes only_

## Installation

### Dependencies

System dependencies:

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
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

Run `make check` for static checks and `make test` for headless regression tests.

Optional macOS native capture and effects keep OBS output:

```sh
uv sync --extra macos
uv run --extra macos webcam_mods list-cameras
uv run --extra macos webcam_mods --no-controls --capture-backend avfoundation --segmentation-backend vision --vision-quality fast bg-blur
make verify UV_FLAGS='--extra macos'
```

`list-cameras` shows native input indices, formats and excluded OBS output without
opening a camera or requesting permission. Use its index with `--input-device`.

Run from macOS Terminal and allow Camera access when prompted. Common options
work before or after commands; command-side values override root values.
`--processing-backend coreimage` selects Gaussian background
blur/compositing; portable OpenCV box blur remains default. Native options are
experimental and do not guarantee better performance or segmentation quality.
See [backend report](docs/macos-backends.md) for measured results and limitations.
No own camera extension or paid Apple membership is required.

Preview the exact final webcam frame in a bare window:

```sh
uv run webcam_mods --no-controls --output preview bg-blur
# native capture and Vision, with the same preview output
uv run --extra macos webcam_mods --no-controls --output preview --capture-backend avfoundation --segmentation-backend vision --vision-quality fast bg-blur
```

Close the window or press Escape to stop. Preview uses configured output dimensions
and the output FPS cap, including negotiated input FPS. `--output virtual-cam`
remains the default. Preview sends frames only to the window and requires no OBS
setup; webcam input still needs Camera permission. The output option applies to
camera and screen-sharing commands. Root help groups frequent options;
`webcam_mods <command> --help` shows all common and command-specific options.

Share a screen region through the same preview or virtual-camera output:

```sh
uv run webcam_mods share-screen --width 1280 --height 720 --output preview --no-controls
uv run webcam_mods share-screen --left 0 --top 0 --width 1280 --height 720 --output virtual-cam
```

`--width`/`--height` set the capture region, defaulting to input dimensions.
`--input-fps` sets requested screen cadence (30 by default); `--output-width`,
`--output-height` and `--output-fps` independently set final output size and cap.
Negative `--left`/`--top` support monitors above or left of the primary display.
Screen sharing supports the same crop/padding, record/replay, `--no-controls`
and `--freeze-on-error` behavior. `--output gui` remains a preview alias.
Camera backend selection applies only to cameras; screen capture uses MSS.
On macOS, grant Screen Recording permission to the application launching Python.

Run modes with `uv run webcam_mods <command>`. For example,
`uv run webcam_mods crop-cam`. On Linux, install the video device dependencies
with `uv sync --extra linux --python 3.14`.

Face tracking and background effects use MediaPipe Tasks 1.0.1. On macOS ARM64,
`uv sync` installs our Metal-enabled source snapshot `1.0.1+git32d0e5b.metal`, which fixes
[upstream issue #6356](https://github.com/google-ai-edge/mediapipe/issues/6356).
The wheel and its native dependencies are included in this repository; see
[build provenance and rebuild instructions](vendor/mediapipe/README.md).
Use the `uv` project installation on macOS: standalone `pip` installs do not
apply this dependency override. Other platforms use the official release.
On macOS ARM64, each MediaPipe model automatically compares CPU and Metal
on its first input frame at each resolution. Three isolated, warmed comparisons
include input conversion and result readback; GPU must be over 5% faster
in every comparison. Probe failures use CPU. Selection adds several seconds
at first use, is cached for the process, and is logged; no CLI selection is needed.
Both delegates use RGBA input. Other platforms use CPU.
The two MediaPipe models are downloaded once into `~/.cache/webcam-mods/models`
and verified with SHA-256; later runs use the cached copies.

## Repeatable end-to-end checks

```sh
make e2e     # headless pipeline with saved output
make verify  # static checks + full test suite (includes E2E)
```

`make e2e` writes deterministic PNG inputs, runs them through the production
`live_loop` and real MediaPipe effects, writes lossless PNG output, and
reopens it to assert frame count, dimensions, ordering, crop/brightness,
background blur/color/replacement, positive and negative face detection,
foreground preservation, error/freeze behavior, and cleanup on failures.
Eight frames per scenario keep repeat runs cheap. Models download on first
use; cached models and the bundled person fixture allow offline repeat runs.
No webcam, OBS, display, keyboard hooks, or external API is needed.

Outputs live under `dist/e2e/<test>/`: input PNGs, output PNGs,
`preview.png` (input left, output right), and `metrics.json`.
`dist/e2e/report.json` records overall success and elapsed time. A failed
assertion exits nonzero. `make test` uses temporary output directories.
Timings include disk I/O and model startup, not live-camera FPS.

These checks cover the processing loop and effects. They do not validate CLI
option wiring, keyboard controls, record/replay, hardware capture, OBS delivery,
or a conferencing app. For the hardware check, run
`uv run webcam_mods bg-blur --brighten 20`, select OBS Virtual Camera in the
receiving app, and confirm moving video, blur, brightness, and clean shutdown.

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
Startup settings resolve once at command execution: CLI options override environment variables,
then defaults from `settings.py`. Invalid values fail before devices open; `--help` remains available.
Use `--input-device`, `--input-width`, `--input-height`, `--input-fps`, `--input-format`,
`--output-width`, `--output-height`, `--output-fps`, `--output-device`,
`--on-demand/--no-on-demand`, `--pan-control/--no-pan-control`, and
`--padding-control/--no-padding-control` before the camera command.
Booleans accept true/false (case-insensitive) or 1/0. Crop/padding persistence remains separate.

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
- [x] add screen as an input
- [x] convert/migrate env variables to cli arguments
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

### Live-camera benchmark

From a camera-authorized Terminal:

```sh
uv run --extra macos python scripts/benchmark_live.py --frames 300 --warmup 30
```

Defaults to AVFoundation, Vision fast and preview. Use `--output-backend virtual-cam`
for OBS. Saves timing/cadence/memory metrics, with optional `--save-frame` for quality
review. See [measurement details](docs/macos-backends.md#live-camera-measurements).

Check repeated physical-camera and OBS producer startup/shutdown from a
camera-authorized Terminal:

```sh
uv run --extra macos python scripts/benchmark_live.py --cycles 3 --frames 100 --warmup 10 --output-backend virtual-cam --report dist/benchmarks/lifecycle.json
```

Each cycle creates fresh capture, effect and output resources, delivers the full
frame count, checks adapters are closed and closes effects before starting again.
Multi-cycle JSON contains `status`, requested/completed counts and individual
`runs`. Progress is saved after each cycle; failures or interruptions retain
completed runs, identify the failed cycle and exit nonzero. Only `status: passed`
means all cycles completed. Single-cycle success keeps the existing report shape.
Metrics stay separate per cycle; peak RSS remains a process-lifetime measurement.
Images are saved only with `--save-frame`; multiple cycles add `-cycle-N` to its
filename. Select OBS Virtual Camera in a receiving app to check moving video
through each restart; producer send completion alone does not establish reception.
