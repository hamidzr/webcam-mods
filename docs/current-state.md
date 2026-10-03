# Current state

Updated 2026-10-02 after session/control and optional native-backend implementation.

## Implemented behavior

All existing command names remain: crop-cam, bg-color, bg-swap, bg-blur, brighten,
track-face, share-screen and test-loop. Common freeze-on-error now propagates to
all camera commands. Global options precede the command; --no-controls disables
keyboard and stdin together. Track-face and test-loop omit crop/replay preparation.
Screen sharing is excluded from this change and retains its legacy implementation.

Each camera CLI run owns Config, ordered controls and Recorder, with effect models
and native contexts scoped to the run and closed explicitly. CLI import/help starts
no stdin reader or desktop listener and creates no config file. The original
Python helpers for face/segmentation remain lazy compatibility instances.

Crop/padding uses existing Ctrl/Alt/Shift arrow gestures. Stdin commands are
`reset`, `record`, `stop`, `replay`. Commands apply before the next frame; invalid
geometry and empty replay are rejected. Recording copies frames, stops when the
configured memory cap would be exceeded, and starts new recording/replay at index
zero. Default cap is 256 MiB, adjustable with --recording-limit-mb. A full command
queue rejects new controls instead of overwriting old ones.

Config retains ~/.webcam-mods.conf and existing JSON field names. Loading validates
integer pairs, positive crop bounds and even nonempty padding. Invalid/missing
settings use in-memory defaults without overwriting the file on construction.
Actual frame dimensions adapt valid persisted crops or reset invalid ones. Changed
settings persist atomically; write failures restore the previous in-memory state.

The loop opens input once, accepts positive finite negotiated metadata, closes
partial output setup and tears down capture/controls after failures. OpenCV honors
IN_FPS and releases failed capture handles. Default output remains native V4L2 on
Linux and pyvirtualcam/OBS elsewhere.

## Configuration

[env.example](../env.example) documents existing environment variables. No new
backend environment aliases were added; CLI selects optional native backends. Startup
settings resolve once before acquisition with CLI > environment > defaults. Numeric
values are validated; malformed environment does not prevent help. Boolean values
accept true/false (case-insensitive) and 1/0. See README for CLI overrides.

| Settings | Default / behavior |
| --- | --- |
| VIDEO_IN | 0, camera index |
| VIDEO_OUT | /dev/video10, native Linux output only |
| IN_WIDTH / IN_HEIGHT | 640 / 480, requested capture dimensions |
| IN_FPS | 30, applied by both capture adapters |
| IN_FORMAT | YUYV, OpenCV FOURCC request only |
| OUT_WIDTH / OUT_HEIGHT | 640 / 480 |
| MAX_OUT_FPS | 30, output cap; loop paces all backends |
| ON_DEMAND | false; true/1 enables consumer polling |
| PAN_CONTROL / PADDING_CONTROL | true; true/1 enables respective keyboard gestures |
| freeze_on_error | false; existing Typer environment option |
| XDG_CACHE_HOME | ~/.cache fallback, verified model cache |
| --output | virtual-cam default; preview displays final frames in a bare window |
| --segmentation-backend | mediapipe default; optional vision |
| --processing-backend | opencv default; optional coreimage for backgrounds |
| --capture-backend | opencv default; optional avfoundation |
| --vision-quality | balanced default; fast / accurate available |
| --controls / --no-controls | enabled default for prepared camera commands |
| --recording-limit-mb | 256 maximum retained recording MiB |

## Native backends

Optional macOS extra supplies PyObjC Vision, Quartz, AVFoundation, CoreMedia and
libdispatch. Vision produces person masks; Core Image composites backgrounds and
uses Gaussian blur rather than existing box blur. AVFoundation uses bounded
newest-frame delivery and copied BGR arrays. No own camera extension, ScreenCaptureKit,
HTTP control server or zero-copy frame abstraction was introduced.

[Native backend report](macos-backends.md) contains measured processing timings,
visual differences, commands and verification limits. Portable defaults stay:
native backends showed no general processing speed advantage on the measured
fixture. Portable float32 blending improved 1080p median processing time by about
11%; final sample differs from baseline by at most one channel value.

## Verification and remaining gaps

Checks cover compileall, configured flake8 rules, Black and unittest discovery,
including CLI option propagation/import side effects, command ordering, persistence,
record/replay bounds, model state isolation, partial startup cleanup, real CPU
MediaPipe, real Vision/Core Image and native buffer orientation/stride/lifetime.
Use make verify UV_FLAGS='--extra macos' to run optional native tests.

Supported runtime: Python 3.14 only. Local macOS ARM64 checks pass: 133 tests.
Both CLI entrypoints run and wheel/source-distribution builds succeed. GitHub verification workflow
targets Python 3.14 on macOS ARM64 and Linux x86_64; remote validation
is excluded by user choice. Local Linux execution was not performed.

Bare-window preview displays the final resized/padded BGR frame without overlays.
It pumps GUI events, paces against monotonic deadlines and stops the run on close
or Escape. Six real macOS preview frames displayed and cleanup passed; camera
permission checks remain separate. Pacing preserves phase through small sleep/event
jitter and avoids a redundant GUI poll after reaching the deadline. Whole-period
misses restart the schedule without bursts. A 120-frame fixed-fixture/real-preview
smoke (10 warmup, Vision fast, 640x480) observed 22.19 FPS before and 30.00 after
this pacing fix. Processing medians differed (11.92/6.03 ms); these short runs
confirm cadence behavior and are not a controlled model-speed comparison.

OBS Virtual Camera initialized, received three synthetic 640x480 frames at 30 FPS
and closed successfully. A subsequent 12-frame fixture run exercised Vision, Core
Image and production live_loop through real OBS output with cleanup. Conferencing-app reception was not checked. Initial
camera permission requests from T3 Code/Python failed for both direct AVFoundation
and OpenCV. Capture is now confirmed from authorized Terminal; T3 still lacks access.
A Terminal hardware attempt exposed use of the inputPriority preset, which is
unsupported on macOS despite being exported by the Python binding. Setup now
attaches input/output before selecting activeFormat/FPS directly. Mocked regression covers unsupported explicit preset, setup
ordering and format-failure cleanup. Native capture retains the device configuration
lock until session shutdown, preventing macOS from overriding the selected format
at commit/start. Cleanup releases it once, including startup failures; a stopping
timeout retains it until the worker finishes. Startup rejects unexpected frame dimensions.
Tests with mocked camera startup do not establish hardware delivery. The new
live benchmark camera smoke test also failed with permission denial. A later
Terminal run exposed AVFoundation index 0 selecting OBS (1920x1080/60 only),
while local index 1 supports the requested 640x480/30. Read-only native format
selection confirmed both; benchmark now accepts `--input-device`, and format
errors include device identity, available formats and selection guidance. OBS
subsequently moved to raw index 1, confirming raw device-order instability. Native
input selection now excludes OBS by manufacturer/model before applying input
indices. Default 0 selects the first remaining input; read-only checks with both
orders selected the built-in camera, and repeated mocked starts cover reordering.
Five headless
benchmark regressions pass, and its measurement path delivered 12 fixture frames
through Vision fast/Core Image and real OBS output at 29.67 FPS (30 FPS target).
This fixture smoke verifies cadence/delivery, not real-camera throughput.

User Terminal run: physical index 1 delivered 300 measured frames after 30 warmup,
Vision fast/OpenCV blur/preview, 640x480 output at a 30 FPS target. Before the lock
fix, capture unexpectedly returned 1920x1080: processing median 24.32 ms/p95
31.70 ms, capture-to-send median 25.29 ms/p95 32.68 ms, delivery 26.35 FPS and
process peak RSS 458,276,864 bytes. This confirms hardware capture but exposes an
incorrect capture resolution. Corrected Terminal rerun is now confirmed: 300 measured frames after 30 warmup,
640x480 input/output at 30 FPS target, delivery 29.955 FPS. Processing median/p95
6.34/15.23 ms, capture-to-send 21.30/31.64 ms, capture wait 14.01/17.03 ms, and
process peak RSS 315,473,920 bytes. This is the requested resolution, not a same-
resolution comparison with the earlier 1080p run. Repeated hardware start/stop and
conferencing reception remain unverified. User observed frequent mask-boundary
jitter in Vision fast preview; visual refinement is explicitly deferred in the
[improvement plan](improvement-plan.md).

Other remaining gaps:

- No portable consumer/pause capability contract; unified pacing is implemented.
- Screen.setup still lacks width/height metadata expected by default-output path;
  screen sharing was explicitly excluded.
- No hot input switching, user-facing file output, HTTP service or cross-process control.
- Lazy legacy helper compatibility remains; CLI startup uses a validated immutable snapshot.
- No live-camera latency, power or segmentation-quality benchmark on moving people.
- Strict mypy checks cover startup settings, pacing, model cache, recording, adapter
  interfaces, OpenCV capture, session and crop persistence. Legacy demos are repaired;
  remaining effect/geometry modules are outside the current typing scope.

See [remaining improvement plan](improvement-plan.md).
