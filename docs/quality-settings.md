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

The output runs at most `min(negotiated input FPS, output FPS cap)`.
Slow capture or processing can reduce actual delivery below this ceiling.
There is no frame interpolation or duplication to raise a 15 FPS source to
30 FPS. Lowering only the output cap reduces processing iterations but does not
reconfigure the camera's requested FPS. Set both rates to reduce capture work too.

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

For those formats, add `--capture-backend avfoundation`. Native input indices
can differ from OpenCV indices, and OBS output is excluded. AVFoundation already
requires a supported format and verifies first-frame dimensions. It ignores
OpenCV's `--input-format` FOURCC. On Linux, inspect device formats with
`v4l2-ctl --list-formats-ext -d /dev/video0`, using the selected input device.

These launch controls are covered by headless camera negotiation and production
CLI/pipeline tests, including independent delivery sizing, padding and FPS caps.
Physical-camera format switching and sustained consumer delivery still require
hardware acceptance. Automatic battery/AC/Low Power Mode presets are deferred
in [TODO](../TODO.md).
