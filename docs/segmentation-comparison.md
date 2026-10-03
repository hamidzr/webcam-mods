# Segmentation comparison and boundary smoothing

## Local motion refinement (2026-10-03)

User reactivated our stabilization; macOS Portrait reliance is excluded for this
work. Previously, visible motion covering more than 2% of the image bypassed all
history. That made unrelated stationary edges jitter whenever a hand moved.
History now resets only at visibly changed pixels and their one-pixel neighborhood.
Large mean confidence jumps still reset the whole mask. Regression reproduces the
old failure with a moving/departing hand over 4% of the image and a separate static
boundary; changed pixels respond immediately while the boundary stays smoothed.
Full-image visible motion still takes effect immediately.

Before/after Vision fast comparison used the same 640x480 fixture, 10 warmup frames
and 60 frames per phase, in fresh processes. Static mask variation reduction
remained 65%. Translation-phase smoothing mean/p95 was 0.40/0.49 ms before and
0.57/0.66 ms after; static smoothing was 0.56/0.60 ms before and 0.40/0.44 ms after.
These short runs establish measured cost, not a general speed improvement or
battery saving. Translation mean absolute raw/stabilized mask deviation changed
from zero to 0.00168 because unchanged pixels now retain history. Comparison
sheets were inspected; they do not establish trail-free live hair/hand motion.
Vision fast's existing torso loss and black-input misclassification remain.
Reports and sheets: `dist/segmentation/stabilization-before/` and
`dist/segmentation/stabilization-after/`.

Smoothing stays opt-in. Live hair, hands, low-light movement and subject departure
remain acceptance checks. Measure complete live cost with
`benchmark_live.py --mask-smoothing`; JSON workload records `mask_smoothing`.

## Original fixture checkpoint (2026-10-02)

Measured 2026-10-02 on Apple M4 Max, Python 3.14, 640x480 BGR disk fixture.
Each configuration ran in a fresh process, with 10 warmup frames and 60 frames
per phase: static astronaut, horizontal translation, 30% brightness, black input
as a departure probe. Capture, OBS output and compositing are excluded from
latency. Initialization is excluded. RSS includes imports, models and artifact
assembly, so it is not incremental backend memory.

| Backend | Static segmentation mean / p95 ms | Smoothing mean / p95 ms | Process peak MB |
| --- | --- | --- | --- |
| MediaPipe | 3.53 / 3.89 | 0.48 / 0.53 | 293.5 |
| Vision fast | 3.27 / 3.73 | 0.49 / 0.53 | 258.0 |
| Vision balanced | 9.64 / 10.47 | 0.50 / 0.57 | 264.8 |
| Vision accurate | 32.09 / 33.09 | 0.53 / 0.59 | 301.7 |

Fast static mean absolute mask change fell from 0.002041 to 0.000716 (65%).
Dim-input change fell from 0.002487 to 0.000897 (64%). Other backends produced
stable repeated-image masks; smoothing offers no improvement on those static
inputs. All translated masks matched raw masks exactly after motion bypass.
These are mask variation metrics, not ground-truth accuracy or live FPS.

Inspected comparison sheets: fast drops large torso/collar areas in this fixture;
balanced and accurate retain those regions and provide softer transitions around
the helmet. Accurate has little remaining budget inside a 33.3 ms frame, before
capture/output. Fast produces false foreground on completely black input both
before and after smoothing. Smoothing cannot correct backend misclassification.
Balanced and accurate return empty masks on that probe. Black input is an extreme
transition probe, not realistic subject departure footage.

Keep MediaPipe/OpenCV defaults. Balanced is a useful explicit Vision candidate
for live comparison; this single fixture does not justify a default change.
No claims about moving hair, hands, actual low-light noise, power or live delivery
are supported yet. Use recorded footage for those comparisons without camera
permission; visual live acceptance remains outstanding.

## Usage

```sh
uv run --extra macos webcam_mods --no-controls --segmentation-backend vision --vision-quality fast --mask-smoothing bg-blur
uv run --extra macos python scripts/compare_segmentation.py --backend vision --quality fast --frames 60 --output dist/segmentation/vision-fast
uv run --extra macos python scripts/compare_segmentation.py --backend vision --quality balanced --frames 60 --output dist/segmentation/vision-balanced
uv run --extra macos python scripts/compare_segmentation.py --backend vision --quality accurate --frames 60 --output dist/segmentation/vision-accurate
uv run python scripts/compare_segmentation.py --backend mediapipe --frames 60 --output dist/segmentation/mediapipe-balanced
# recorded footage: frames limits the total decoded video frames
uv run --extra macos python scripts/compare_segmentation.py --source recording.mp4 --frames 300 --output dist/segmentation/recorded
```

Each output directory contains `metrics.json`, `comparison.jpg` (source, raw
composite, stabilized composite, stabilized mask), and `masks.npz` with the final
raw/stabilized float32 masks per phase. Reports retain first-frame transitions;
within-phase delta metrics exclude cross-phase differences. Timing includes mask
postprocessing, including existing MediaPipe dilation/blur/sigmoid. Comparison
uses OpenCV composition and the same inferred mask for raw/smoothed output.

## Stabilization behavior

`--mask-smoothing` is opt-in and works with all background effects and both
processing backends. Defaults and legacy helper behavior remain unchanged.
The filter uses 35% current confidence and 65% previous confidence at static
pixels, without spatial blur. Luma changes greater than 12/255 reset affected
pixels and a one-pixel neighborhood. Motion elsewhere does not bypass history for stationary pixels.
Mean confidence change greater than 0.12 resets
history. Shape changes and run close discard history.

At 30 FPS, static confidence converges 90% within six frames, about 200 ms.
Visible movement bypasses that averaging; low-contrast movement below the luma
threshold may still lag. Thresholds are implementation constants pending actual
hair/hand/low-light evidence. Avoid extra dilation/feathering until fine-detail
comparisons support it. Tests cover binary edge jitter, synthetic noise, sharp
detail, local/global motion, immediate large departures, dimension changes,
input ownership, CLI propagation and close cleanup.
