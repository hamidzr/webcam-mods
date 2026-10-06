# Webcam Mods

Face tracking, background blur/replacement, crop, brightness and bounded replay
for a virtual camera. Python 3.14 processing runs on macOS and Linux. macOS also
has an optional native menu bar app. Windows adapters exist but current Windows
installation and hardware behavior are unverified.

## Install

Requires [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/).
Run from this checkout:

```sh
just install
webcam_mods --help
```

Installation builds a wheel snapshot and includes platform extras. The command
works outside the checkout; rerun `just install` after source changes. See
[installation details](docs/installation.md) for PATH and development setup.

On macOS, install OBS 30 or newer, open it once, and start its Virtual Camera to
install/enable the camera extension. If necessary enable it under System Settings
> General > Login Items & Extensions > Camera Extensions. Stop Virtual Camera and
close OBS. Webcam Mods then sends directly to OBS Virtual Camera. Select that
camera in the receiving app. No custom camera extension or paid Apple membership
is required. Preview output requires no OBS installation.

Linux requires v4l2loopback. Configure the module outside the application, for
example `sudo modprobe v4l2loopback devices=1 exclusive_caps=1 video_nr=10
card_label="v4l2-cam"`. Existing device use may prevent module changes; the app
does not unload modules or terminate other video processes.

## Use

```sh
webcam_mods bg-blur --brighten 20
webcam_mods track-face --blur
webcam_mods bg-swap /path/to/background.jpg
webcam_mods crop-cam --output preview
webcam_mods list-cameras --capture-backend avfoundation
```

Common options work before or after commands; command-side values override root
values. Use `webcam_mods COMMAND --help` for the complete option set.
`--no-controls` disables keyboard and stdin controls. Camera capture needs Camera
permission for the launching application. macOS terminal runs offer a numbered
camera picker unless an explicit index or `VIDEO_IN` is set; noninteractive runs
never prompt. OBS output, closed-lid built-in cameras and unavailable inputs are
excluded. Indices belong to the chosen backend.

Capture defaults to `auto`: AVFoundation on macOS with installed bindings,
otherwise OpenCV. Auto retains OpenCV indices and maps the selected identity into
native capture; explicit `avfoundation` uses its filtered native indices. Startup
errors never silently switch cameras or backends. Requested resolution/FPS must
be supported together by the camera.

`--output preview` opens a bare window containing the final output frame; close
it or press Escape to stop. `--output virtual-cam` is default. `gui` remains a
legacy preview alias. [Quality settings](docs/quality-settings.md) describe
independent capture/output dimensions and FPS. [Repeat mode](docs/frame-delivery.md)
keeps delivery cadence independent of processing by repeating the latest frame:

```sh
webcam_mods bg-blur --repeat-frames --processing-fps 15 --output-fps 30
```

## macOS menu and profiles

See [native menu guide](docs/macos-menu.md) for building/installing the optional
SwiftUI app, saved profiles and local session control. Profiles retain native camera
identity and allow independent capture/output dimensions and FPS. Explicit Start/Stop owns
one Python worker session. Existing CLI commands remain available.

## Effects and controls

Background modes use MediaPipe by default; optional `--segmentation-backend vision`
and `--processing-backend coreimage` select native macOS implementations. OpenCV
blur is box blur; Core Image blur is Gaussian. These are behavioral choices,
not a demonstrated general performance advantage. `--mask-smoothing` enables
motion-aware segmentation smoothing; it remains opt-in.

Face tracking follows the nearest compatible face after initially choosing the
largest. This is geometric continuity, not identity recognition. Defaults target
40% face height, horizontal center, vertical position 42%, and at most 2x digital
zoom within source bounds. Output aspect ratio is preserved. Tuning:

```sh
webcam_mods track-face --face-height 0.35 --max-zoom 1.5 --target-y 0.4
```

`--pan-deadzone` and `--zoom-deadzone` suppress small movements;
`--pan-seconds` and `--zoom-seconds` set independent response time constants.
`--lost-after` holds framing before widening/reselection. Legacy `--x-padding`
/ `--y-padding` replace face-height framing with minimum crop-to-face ratios.
Tracking disables interactive crop/replay controls.

For prepared camera modes, Ctrl+arrows move crop, Ctrl+Shift+arrows resize it,
and Alt+arrows adjust padding. Stdin accepts `record`, `stop`, `replay` and `reset`.
Empty replay is rejected. Recording defaults to a 256 MiB memory cap, adjustable
with `--recording-limit-mb`. Crop/padding persists atomically in
`~/.webcam-mods.conf`; saved launch profiles are separate.

## Screen sharing

```sh
webcam_mods share-screen --width 1280 --height 720 --output preview --no-controls
webcam_mods share-screen --select area --output virtual-cam --no-controls
```

Explicit coordinates use `--left`, `--top`, `--width`, `--height`; negative
coordinates support other displays. macOS `--select area|screen|visible` requires
`select-region` on PATH (installed separately from `~/scripts/compat`). Selection
cannot combine with coordinates. Area selection fits output aspect ratio; a
click-through border follows later crop changes. `--no-border` hides it.
Screen runs use fresh crop state, MSS capture and the same output/control path.
Grant Screen Recording permission to the launching application.

## Configuration and models

CLI startup settings resolve once: CLI > environment > defaults. Invalid values
fail before devices open; help remains available. [env.example](env.example)
lists supported names. Booleans accept true/false or 1/0. Input/output default to
640x480/30. Native capture ignores OpenCV's `IN_FORMAT` FOURCC.

MediaPipe uses checksum-verified models under `~/.cache/webcam-mods/models`,
honoring `XDG_CACHE_HOME`. `just models` downloads them ahead of use. macOS ARM64
uses the bundled Metal-enabled wheel; [vendor provenance](vendor/mediapipe/README.md)
describes rebuilding it. Other platforms use the official release.

On macOS ARM64, CPU and Metal are compared on first use of each model/frame shape.
Three warmed comparisons include input conversion and result readback; GPU must
be over 5% faster in every round. Probe failures use CPU. Successful decisions
persist with hardware/software identity and expiry; warm launches skip probes.
Cold calibration still takes several seconds. Other platforms use CPU.

## Develop and verify

```sh
just deps
just run --help
just check
just test
just e2e
just verify
```

`check` runs Flake8, Black and strict mypy; `test` runs headless regression tests.
E2E uses real models and deterministic image input through the production loop,
writing PNG output and metrics under `dist/e2e`. It needs no camera, OBS or display.
Native app checks are documented in the [menu guide](docs/macos-menu.md).

These checks establish processing and lifecycle behavior. They do not establish
conferencing reception, 720p effects/output, realistic moving-person quality or
power consumption. Those checks are deferred. Historical benchmarks retain exact
workload context in [macOS backends](docs/macos-backends.md).

[Developer documentation](docs/README.md) contains architecture, current state and
the [backlog](TODO.md). Report bugs through [GitHub Issues](https://github.com/hamidzr/webcam-mods/issues/new).
Historical demos: [January 2022](https://youtu.be/FfD7lu_A1Dw),
[earlier demo](https://youtu.be/idp7ei-pF40); they are not current acceptance evidence.

## Credits

- [MediaPipe](https://github.com/google/mediapipe), face/person models.
- [Linux-Fake-Background-Webcam](https://github.com/fangfufu/Linux-Fake-Background-Webcam), mask/on-demand inspiration.
- [pyvirtualcam](https://github.com/letmaik/pyvirtualcam), virtual camera output.
