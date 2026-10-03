# Capture and delivery quality

Choose settings at launch; restart the session to change them. Common options
work before or after the command. CLI values override environment variables,
then defaults. No automatic power preset is applied.

| Stage | CLI | Environment | Default |
| --- | --- | --- | --- |
| Capture size | `--input-width`, `--input-height` | `IN_WIDTH`, `IN_HEIGHT` | 640x480 |
| Capture rate | `--input-fps` | `IN_FPS` | 30 FPS |
| Delivery size | `--output-width`, `--output-height` | `OUT_WIDTH`, `OUT_HEIGHT` | 640x480 |
| Delivery cap | `--output-fps` | `MAX_OUT_FPS` | 30 FPS |

Capture size determines available detail and the initial effect workload.
Delivery size is applied after effects: the frame is resized and padded to
preserve its aspect ratio. Upscaling does not recover missing camera detail.
Reducing only delivery size does not reduce segmentation's input resolution.

By default, output runs at most `min(negotiated input FPS, output FPS cap)`.
Slow capture or processing can reduce actual delivery below this ceiling.
Opt-in [frame repetition](frame-delivery.md) can deliver a 15 FPS source at
30 FPS by repeating frames. Lowering only the output cap reduces processing
iterations but does not reconfigure the camera's requested FPS. Set both rates
to reduce capture work too.

For example, request 640x480/15 capture and 1280x720/15 delivery:

```sh
uv run webcam_mods bg-blur --no-controls --output preview \
  --input-width 640 --input-height 480 --input-fps 15 \
  --output-width 1280 --output-height 720 --output-fps 15
```

Or request 1280x720/30 capture and 640x480/15 delivery:

```sh
uv run webcam_mods bg-blur --no-controls --output preview \
  --input-width 1280 --input-height 720 --input-fps 30 \
  --output-width 640 --output-height 480 --output-fps 15
```

Use `--output virtual-cam` for OBS/V4L2 delivery. These are setting examples,
not a claim that every camera supports these combinations.

## Camera negotiation

`--capture-backend auto` is the default. With complete macOS bindings it uses
our native AVFoundation adapter, which selects the exact format and retains its
configuration lock. Other platforms and macOS base installations use OpenCV;
missing macOS bindings produce a warning. Explicit `opencv` and `avfoundation`
remain available. Native startup failures do not fall back to another backend.

Auto preserves OpenCV camera numbers by matching the same device's identity,
including after enumeration order changes. It refuses OBS output or a missing
selected device instead of substituting another camera. `list-cameras` lists
indices for the chosen backend; use the same backend for listing and capture.
Explicit AVFoundation indices are separately filtered native indices.

The camera must support the requested resolution and FPS together. OpenCV
requests pixel format and dimensions before FPS, because format changes can
reset the rate. Startup reads and retains the first frame, checks its actual
dimensions, then checks the device's reported FPS. A mismatch fails with the
requested and actual values instead of silently increasing processing work.
Nominal fractional rates such as 29.97 for a 30 FPS request are accepted
(1% relative or 0.1 FPS absolute tolerance). Unreported/nonpositive FPS fails
because the input rate cannot be verified. Later frame-size changes also fail.

Reported FPS is a negotiation check, not a measurement of arrival cadence.
Startup logs input/output metadata; the live benchmark measures delivered cadence.

On macOS, inspect native formats without opening a camera:

```sh
uv run --extra macos webcam_mods list-cameras
```

Auto/OpenCV indices match OpenCV's enumeration, including gaps where OBS is
excluded. To list explicit native indices, add `--capture-backend avfoundation`
to `list-cameras` and the capture command. AVFoundation requires a supported
format and verifies first-frame dimensions/FPS. It ignores
OpenCV's `--input-format` FOURCC. On Linux, inspect device formats with
`v4l2-ctl --list-formats-ext -d /dev/video0`, using the selected input device.

These launch controls are covered by headless camera negotiation and production
CLI/pipeline tests, including independent delivery sizing, padding and FPS caps.
Physical-camera format switching and sustained consumer delivery still require
hardware acceptance. Automatic battery/AC/Low Power Mode presets are deferred
in [TODO](../TODO.md).

## Check format retention

Run from a camera-authorized Terminal:

```sh
uv run --extra macos python scripts/check_capture.py \
  --width 1280 --height 720 --fps 30 --frames 120 --cycles 3
```

Each session checks the initial frame, waits five seconds to reproduce delegate
calibration's startup pause, then checks subsequent frames. No images are saved,
no models load and no output camera opens. `dist/capture-check.json` records
requested/negotiated format, frame counts, post-pause cadence and cleanup.
Only `status: passed` means all requested sessions completed. Permission failures
report `blocked`; partial failures retain progress and exit nonzero. On macOS the
check reads existing authorization before acquisition and does not request
permission from a headless process.

The reported user failure (2026-10-03) passed its initial 1280x720 check, then
received 864x480 through OpenCV. Midstream drift now has a separate error from
unsupported startup negotiation. Native frame-size drift is also rejected.
OpenCV's macOS backend uses a Medium session preset and automatic output-format
matching, and releases its device lock after setting FPS. See
[OpenCV implementation](https://github.com/opencv/opencv/blob/5.0.0/modules/videoio/src/cap_avfoundation_mac.mm#L415).
These mechanisms explain why mode availability alone does not establish retention;
the exact trigger for the reported drift remains unverified on hardware.
