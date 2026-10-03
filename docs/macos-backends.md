# macOS backends

Implemented 2026-10-02. Python orchestration and OBS/pyvirtualcam output remain.
ScreenCaptureKit and an own camera extension are outside this change.

## Selection

```sh
uv sync --extra macos
uv run --extra macos webcam_mods --no-controls --segmentation-backend vision --vision-quality fast bg-blur
uv run --extra macos webcam_mods --no-controls --segmentation-backend vision --processing-backend coreimage bg-blur
uv run --extra macos webcam_mods --no-controls --capture-backend avfoundation --segmentation-backend vision bg-blur
```

Global options precede commands. Add `--output preview` for a bare final-frame
window instead of virtual-camera delivery; close or Escape stops the run. Portable defaults remain OpenCV capture,
MediaPipe segmentation and OpenCV processing. Native options are explicit; there
is no silent fallback. `--no-controls` disables keyboard and stdin together.
`PAN_CONTROL=False` and `PADDING_CONTROL=False` independently disable keyboard
features. Vision segmentation requires macOS 12 or newer; Python bindings are
optional in the `macos` extra and never imported by CLI help.

Native capture requests camera permission at setup. Authorize the launching app
in System Settings > Privacy & Security > Camera. This includes the terminal or
coding application, depending on how Python is launched. Capture selects a device
index from AVFoundation inputs after excluding OBS output by manufacturer/model
identity. Default index 0 selects the first remaining input; OBS moving between
enumeration slots does not change a single physical camera selection. Other
physical or virtual input devices remain available. `--input-device` and `VIDEO_IN`
index this filtered list, which may differ from OpenCV. Unsupported formats report the selected device and available
resolutions/FPS instead of silently switching cameras. Capture requires a format
matching requested dimensions/FPS, retains only the
latest frame, copies callback BGRA buffers into owned BGR arrays and reports sample
timestamps. Setup attaches input/output before selecting activeFormat and FPS,
configuring the device directly and holding its configuration lock through capture.
The lock is released after the native worker stops, including startup-failure cleanup.
Unexpected first-frame dimensions fail startup instead of silently increasing the
processing workload. [Apple documents automatic macOS format changes](https://developer.apple.com/documentation/avfoundation/capture-device-formats).
The inputPriority preset is unsupported on macOS
and is never selected. Startup, frame waits and shutdown have timeouts. `IN_FPS` now applies
to both capture backends. Native capture ignores OpenCV's `IN_FORMAT` FOURCC.

Vision owns one reusable request and input buffer per effect instance. It returns
a copied float32 foreground mask. Segmentation effects preserve existing horizontal
mirroring, exactly once. Vision uses its own confidence mask directly; MediaPipe
retains existing dilation, smoothing and sigmoid postprocessing. Vision offers
`fast`, `balanced` and `accurate`; these trade quality for processing cost.

Core Image owns one context, uses a per-frame autorelease pool and composites with
a single-channel float mask. Color management is disabled for numeric BGR blending
parity. Crop/padding, final resize, brightness and replay remain portable CPU
operations. Core Image blur is Gaussian; OpenCV blur remains box blur. The kernel
option maps to native radius `(kernel_size - 1) / 2`, not an equivalence between
filters. Background images stretch to current prepared frame dimensions.

This implementation preserves BGR NumPy interfaces. It is not a zero-copy pipeline:
capture, Vision, Core Image and pyvirtualcam still cross CPU/native boundaries.
Buffer-owning frame architecture is deferred until a measured workload justifies
its complexity. No Apple Developer membership is needed for these ordinary native
framework integrations; OBS continues supplying the signed camera extension.

## Benchmarks

Repeatable processing-only benchmark:

```sh
uv run --extra macos python scripts/benchmark_processing.py --backend vision --quality fast --frames 100 --output dist/benchmarks/vision-fast.json
uv run --extra macos python scripts/benchmark_processing.py --backend vision --processing coreimage --width 1920 --height 1080 --output dist/benchmarks/vision-coreimage.json
```

Reports include environment, per-frame timings, median/p95, process peak RSS and
sample PNG. Capture, output, initialization and fixture-motion generation are
excluded. Peak RSS is whole-process high-water memory, not isolated effect memory.

Local Apple M4 Max, macOS ARM64, Python 3.14, OpenCV 5.0.0, PyObjC 12.2.2.
Moving astronaut fixture, 10 warmup frames, 50 measured frames per case. Baseline
uses source at `df50ccd`; optimized output differs by at most one channel value
on the final sample at both resolutions. Results are observations, not live FPS
or proof of segmentation quality on webcam footage.

| Segmentation / processing | 640x480 median / p95 ms | 1920x1080 median / p95 ms |
| --- | --- | --- |
| Original MediaPipe / OpenCV | 6.16 / 6.47 | 25.99 / 26.77 |
| Optimized MediaPipe / OpenCV | 5.77 / 6.04 | 23.19 / 23.58 |
| Vision fast / OpenCV | 5.56 / 8.31 | 24.11 / 24.63 |
| Vision balanced / OpenCV | 12.25 / 13.59 | 32.12 / 34.31 |
| Vision fast / Core Image | 6.55 / 8.32 | 24.62 / 26.30 |
| Vision balanced / Core Image | 13.08 / 14.78 | 32.94 / 34.65 |

Portable optimizations remove float64 masks, three-channel mask copies and extra
blend temporaries. Median processing time drops about 6% at 640x480 and 11% at
1080p on this fixture. Vision fast visibly excludes some helmet/suit details that
MediaPipe retains. Balanced improves those details but costs more. Core Image
adds no demonstrated speed advantage through the current array boundary. Keep
portable defaults; choose native effects for their behavior or future workloads.

## Verification

Run `make verify UV_FLAGS='--extra macos'` to include native fixture tests; base
installations skip optional native tests. Tests exercise real Vision/Core Image,
fractional alpha, orientation, padded pixel-buffer lifetime, mailbox dropping,
repeated mocked camera startup and failure cleanup. CI is configured for Python
3.14 on macOS ARM64 and Linux x86_64; remote validation is excluded.

Camera hardware requests from the T3 Code-launched Python process failed permission
checks during this change, including OpenCV's AVFoundation backend. Mocked camera
setup and real native buffer copying pass; they do not prove device capture.
OBS output initialized, accepted three synthetic 640x480 frames at 30 FPS and
closed. A 12-frame fixture run also exercised Vision, Core Image and production
live_loop through real OBS output with cleanup. Conferencing-client reception,
live latency, power consumption and moving-person quality remain hardware checks.

## References

- [PyObjC Vision](https://pyobjc.readthedocs.io/en/latest/apinotes/Vision.html)
- [Apple Vision quality guidance](https://developer.apple.com/videos/play/wwdc2021/10040/)
- [AVFoundation callback queues](https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput/setsamplebufferdelegate(_:queue:))
- [Core Image performance](https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/CoreImaging/ci_performance/ci_performance.html)
- [PyObjC autorelease pools](https://pyobjc.readthedocs.io/en/latest/api/module-objc.html)

## Live-camera measurements

Run from the project directory in a camera-authorized Terminal. Keep capture format, output backend and
scene consistent when comparing effects. Launch each variant in a fresh process
so lifetime high-water RSS is comparable. Example:

```sh
uv run --extra macos python scripts/benchmark_live.py \
  --capture avfoundation --backend vision --quality fast \
  --output-backend preview --frames 300 --warmup 30 \
  --report dist/benchmarks/live-vision-fast.json
```

Add `--input-device N` to override `VIDEO_IN` for the chosen capture backend.
AVFoundation excludes OBS output before indexing; default 0 selects the first
remaining input. Avoid an old raw AVFoundation index from previous runs.

Repeat with `--quality balanced`, `--processing coreimage`, and
`--backend mediapipe --processing opencv`. Use `--output-backend virtual-cam` to
include OBS delivery. The script honors existing capture/output environment
settings and runs the production loop with controls and recording disabled.
Closing preview early fails the run instead of publishing incomplete metrics.

Reports include negotiated dimensions/FPS, capture wait, effect time, capture-to-send
time including final resize/padding, send duration, delivered cadence and process
peak RSS. Capture wait does not measure exposure latency; send completion does not
measure conferencing reception. Peak RSS includes imports, model initialization
and warmup. Power remains unmeasured.

No camera images are saved by default. Add `--save-frame dist/benchmarks/final.png`
to save the exact final output for visual review. This enables a per-frame copy;
compare cadence with identical save settings. Check moving hair, hands, fast
motion and low light in preview before choosing a segmentation quality.

Local validation: five headless regressions cover measured cadence, warmup exclusion,
exact saved output, partial setup cleanup, early close and invalid workloads. A
12-frame fixture smoke test (three warmup frames) passed through Vision fast,
Core Image and OBS at 640x480/30 FPS; observed delivery was 29.67 FPS. This short
fixture run establishes delivery and cleanup, not live-camera performance.
Camera benchmark startup from T3 still reports permission denial. An authorized
Terminal run confirmed camera delivery: 300 frames after 30 warmup, Vision fast,
OpenCV blur and preview. Capture unexpectedly returned 1920x1080 despite a 640x480
request. Processing median/p95 was 24.32/31.70 ms, capture-to-send 25.29/32.68 ms,
delivery 26.35 FPS and process peak RSS 458,276,864 bytes. Device-lock retention
now prevents automatic format changes; a hardware rerun must confirm the requested
640x480 input. Conferencing reception remains unverified.

Preview pacing follow-up: a 120-frame fixed-fixture run (10 warmup, 640x480,
Vision fast/OpenCV blur) observed 22.19 FPS with the original pacing and 30.00
with the corrected pacing. The fix removes a redundant GUI poll at the deadline
and prevents minor timing jitter from shifting every subsequent deadline. Processing
medians differed (11.92/6.03 ms), so this short fixture evidence does not establish
a model-speed gain. Fake-clock regressions independently isolate event overhead,
sleep overruns and whole-period missed deadlines. Live-camera cadence must be
remeasured after the format fix.
