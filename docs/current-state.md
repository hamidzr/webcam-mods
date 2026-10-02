# Current state

Source review and local verification: 2026-10-02. This describes implemented
behavior, including gaps; it does not promise that every exposed command works.

## Capabilities

| CLI command | Current behavior |
| --- | --- |
| `crop-cam` | Interactive crop/padding and record/replay |
| `bg-color` | Common controls plus solid background |
| `bg-swap` | Common controls plus image background |
| `bg-blur` | Common controls plus blur and optional brightness |
| `brighten` | Common controls plus brightness |
| `track-face` | Smoothed face crop; optional blur; listener disabled |
| `share-screen` | MSS region input; GUI or default virtual-camera output |
| `test-loop` | Default camera pass-through loop |

There is no HTTP control interface, API server, general effect-stack command,
user-facing file output, or hot input switching. Python callers can inject effects
and adapters into `live_loop`, but this is not a session control interface.

Interactive crop/padding uses Ctrl/Alt plus arrows, with Shift for crop dimensions.
The actual stdin commands are `reset`, `record`, `stop`, and `replay`. The README's
`r`/`p` recording instructions do not match this implementation. Record/replay
holds frames in memory without a size limit; replay with no recorded frames can
index an empty list. Replay position is not reset when starting a new recording.

## Configuration inventory

Environment constants are read at import. They cannot currently be changed through
a runtime control interface. `ON_DEMAND`, `PAN_CONTROL`, and `PADDING_CONTROL`
recognize exact `True` only; `freeze_on_error` is parsed separately by Typer.

| Environment name | Default | Notes |
| --- | --- | --- |
| `VIDEO_IN` | `0` | Integer webcam index |
| `VIDEO_OUT` | `/dev/video10` | Used by native Linux output; pyvirtualcam does not forward it |
| `IN_WIDTH`, `IN_HEIGHT` | `640`, `480` | Requested webcam dimensions; default-output probe requires exact match |
| `IN_FORMAT` | `YUYV` | FOURCC requested twice, lowercase then uppercase; setter results ignored |
| `IN_FPS` | `30` | Defined but capture hardcodes 30 FPS |
| `OUT_WIDTH`, `OUT_HEIGHT` | `640`, `480` | Default output dimensions |
| `MAX_OUT_FPS` | `30` | Output FPS cap; native V4L2 adapter has no pacing implementation |
| `ON_DEMAND` | false | Consumer-based pausing; documented for Linux |
| `PAN_CONTROL` | true | Enables pan/resize key handling, not listener construction |
| `PADDING_CONTROL` | true | Enables padding key handling, not listener construction |
| `XDG_CACHE_HOME` | `~/.cache` | Model cache root |
| `freeze_on_error` | false | Typer common option environment name; only `track-face` forwards it |

CLI command options supply effect-specific values, such as blur kernel size,
brightness, background path, face padding, and screen region. There is no unified
CLI/environment/persisted-setting resolution or validation step.

Interactive settings are JSON in `~/.webcam-mods.conf`, despite the `.conf` suffix:
`crop_dims`, `crop_pos`, and `pad_size`. Construction writes defaults if reading
fails. JSON syntax errors are caught, but required keys, types, and crop bounds
are not validated. Writes are direct rather than atomic and run from keyboard
callbacks, including some keys that do not change settings. No `env.example` exists.

## macOS and Linux

| Area | macOS | Linux |
| --- | --- | --- |
| Webcam capture | OpenCV | OpenCV |
| Default output | pyvirtualcam, documented OBS setup | Native V4L2 output |
| Extra dependencies | Base project environment | Install with `uv sync --extra linux` for default output |
| Consumer detection | Adapter always reports in use | inotify approximation |
| Output pacing | pyvirtualcam sleep | `wait_until_next_frame` is a no-op |
| Desktop controls | pynput; desktop permissions/backend required | pynput; available desktop backend required |
| Screen input | MSS; platform permissions apply | MSS; available capture backend required |
| Local evidence in this review | macOS ARM64 checks and headless tests passed | Source reviewed; no Linux execution |

Keep OS-specific imports out of shared processing and preserve native output
capabilities. A Linux base installation lacks the optional packages that default
output imports. This needs an actionable error or explicit output selection.
Linux kernel setup remains an operator task; application startup should not silently
insert or remove modules. Existing `make add-video-dev` is a Linux-only helper.

`share-screen` with default output currently returns only FPS from `Screen.setup`,
but the loop's probe reads width and height as well. The GUI branch supplies output
explicitly and bypasses that probe. Hardware delivery and GUI behavior were not
validated in this review.

## Verification

`make verify` passed locally on macOS ARM64 during this review:

- `uv run python -m compileall -q src tests`
- `uv run flake8 --select=E9,F63,F7,F821 src tests`
- `uv run black --check src tests`
- `uv run python -m unittest discover -s tests`: 18 tests passed

The suite includes real CPU face detection and segmentation, PNG input/output
through production `live_loop`, resize/crop/brightness, blur/background replacement,
positive and negative detection, error/freeze frames, and several failure cleanup
paths. Tests pass explicit input/output adapters, disable controls, and turn off
on-demand mode. They therefore bypass CLI startup, default backend selection,
default capture probing, and desktop behavior.

`make e2e` saves images and metrics under `dist/e2e`; `make test` uses temporary
directories. The existing artifact harness is useful for diagnosing visual
regressions. Disk-based elapsed times are not live-camera FPS measurements.

Not verified here: Linux execution, camera hardware, OBS/V4L2 delivery, conferencing
apps, keyboard hooks, screen capture, record/replay, CLI option propagation,
partial output setup cleanup, or timing guarantees. No new tests were added for
this documentation change.

The only tracked CI workflow is Ubuntu CodeQL; it does not run `make verify`.
`mypy.ini` still targets Python 3.7, includes unrelated dependency sections, and
mypy is neither a dev dependency nor part of `make check`. Compileall and the
selected flake8 rules do not validate runtime interface compatibility.

## Documentation and legacy gaps

- README and TODO contain historical items, including features already present.
  Treat source and this capability inventory as current behavior.
- Legacy `uses/track_face.py` imports a removed module; `uses/track_box.py` calls
  `generate_crop` without its required padding argument.
- `output/file.py` is empty; saved output is test-only.
- Shared adapter base classes carry output defaults even for input adapters,
  use loose metadata dictionaries, and have incomplete lifecycle behavior.
  `FrameOutput.is_in_use` contains `raise True`, which raises a `TypeError`.

Prioritized remediation and the future API direction are in the
[improvement plan](improvement-plan.md).
