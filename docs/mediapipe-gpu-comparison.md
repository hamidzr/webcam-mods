# MediaPipe CPU versus Metal comparison

Measured 2026-10-03 on Apple M4 Max, macOS ARM64, Python 3.14.7.
Metal reduces median face detection time at both resolutions. Segmentation with
app background blur improves modestly at 480p and becomes slightly slower at 1080p.
Results support testing an optional GPU face delegate; they do not justify
switching every effect to GPU. Current app installation and defaults remain CPU.

## Method

Both delegates use the same GPU-enabled patched `1.0.1+git32d0e5b` wheel,
including the upstream CPU initialization fix. Every successful worker recorded
the same native library SHA256. Both receive identical BGR fixture frames,
converted to RGBA inside the measured path. Input conversion, native call, and
output materialization/readback are included. Segmentation total also includes
the app's exact OpenCV background blur (kernel 31), with smoothing disabled.
Face total covers detection only, excluding tracking/cropping. OpenCV uses one
thread for both delegates. Capture, virtual-camera output, model initialization,
frame generation and validation are excluded.

Four rounds alternate CPU/GPU order. Each worker warms up for 60 frames and
measures 500 frames, giving 2,000 measured frames per delegate/model/resolution.
Nine pre-materialized horizontal translations of the astronaut fixture repeat;
this is synthetic motion, not recorded webcam footage. Workers use VIDEO mode
and increasing timestamps. All 48 workers passed, with valid outputs for every
measured frame. CPU SRGB runs additionally measure the current app input path;
they are excluded from the fair RGBA comparison.

Background load remained: one-minute load averages at worker start ranged from
5.61 to 7.34. CPU idle was approximately 70% before the run and 53% at a mid-run
sample. `pmset -g therm` reported no thermal/performance warning before the run.
GPU utilization was not measured. These observations describe this loaded device,
not idle-machine limits. No other agent builds or checks ran during timing.

## Results

Pooled median / p95 milliseconds per frame; lower is faster. Change compares
GPU median to CPU median, using the same RGBA path.

| Resolution | Task | CPU median / p95 ms | GPU median / p95 ms | GPU time |
| --- | --- | --- | --- | --- |
| 640x480 | face | 2.49 / 2.60 | 1.10 / 1.52 | 55.8% less |
| 640x480 | segmentation | 5.61 / 5.80 | 5.08 / 5.54 | 9.4% less |
| 1920x1080 | face | 2.77 / 2.96 | 2.07 / 3.19 | 25.3% less |
| 1920x1080 | segmentation | 24.20 / 24.73 | 24.77 / 25.94 | 2.4% more |

The direction of each median result was consistent across all four rounds.
At 1080p face GPU p95 is worse despite its better median. At 1080p segmentation,
CPU boundary-inclusive inference is 3.12 ms versus GPU 3.64 ms; most total time
is shared CPU mask postprocessing and blur. CPU SRGB medians are 2.49/2.71 ms for
face and 5.59/24.09 ms for background blur at 480p/1080p respectively.

## Output differences

Both delegates detect one face on every measured frame. First/last fixture
box coordinates differ by up to 3 pixels at 480p and 24 pixels at 1080p.
First/last raw confidence-mask mean absolute differences are 0.00865 at 480p
and 0.02420 at 1080p, on a 0-1 scale; maximum individual pixel differences are
0.642 and 0.844. Saved 1080p previews show differences around hair, helmet and
foreground edges. Neither delegate has been scored against ground truth, so
these measurements do not establish equivalent accuracy or which is better.
Continuous-session stability and camera throughput were not tested.

## Reproduce

Build an experimental wheel separately; the committed CPU wheel stays intact:

```sh
./scripts/build_mediapipe.py --gpu
uv venv dist/mediapipe-metal-env --python .venv/bin/python
uv pip install --python dist/mediapipe-metal-env/bin/python -e .
uv pip install --python dist/mediapipe-metal-env/bin/python --reinstall dist/mediapipe-metal/mediapipe-1.0.1+git32d0e5b-py3-none-macosx_11_0_arm64.whl
dist/mediapipe-metal-env/bin/python scripts/benchmark_mediapipe.py --frames 500 --warmup 60 --rounds 4 --cpu-baseline --output dist/mediapipe-fair-benchmark
```

Full samples, environment, native hash, parity and PNG/NPZ outputs from this run
are local artifacts under `dist/mediapipe-fair-benchmark-20261003`.
The wheel SHA256 for this run is `fae7c05922a5211898cb2fbe4ebf65d62a3e9ecd6746e73d416366c8db70545a`.
Experimental wheel and CPU wheel currently share a source version string;
use their hashes and isolated environments to distinguish build configuration.
