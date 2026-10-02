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
backend environment aliases were added; CLI selects optional native backends.

| Settings | Default / behavior |
| --- | --- |
| VIDEO_IN | 0, camera index |
| VIDEO_OUT | /dev/video10, native Linux output only |
| IN_WIDTH / IN_HEIGHT | 640 / 480, requested capture dimensions |
| IN_FPS | 30, applied by both capture adapters |
| IN_FORMAT | YUYV, OpenCV FOURCC request only |
| OUT_WIDTH / OUT_HEIGHT | 640 / 480 |
| MAX_OUT_FPS | 30, output cap; Linux output remains unpaced |
| ON_DEMAND | false; exact True enables consumer polling |
| PAN_CONTROL / PADDING_CONTROL | true; exact True enables respective keyboard gestures |
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

Local macOS ARM64 Python 3.13 and 3.14 checks pass: 97 tests on each version.
Both CLI entrypoints run and wheel/source-distribution builds succeed. GitHub verification workflow
now targets both versions on macOS ARM64 and Linux x86_64; it has not run remotely
because these changes have not been pushed. Local Linux execution was not performed.

Bare-window preview displays the final resized/padded BGR frame without overlays.
It pumps GUI events, paces against monotonic deadlines and stops the run on close
or Escape. Six real macOS preview frames displayed and cleanup passed; camera
permission checks remain separate.

OBS Virtual Camera initialized, received three synthetic 640x480 frames at 30 FPS
and closed successfully. A subsequent 12-frame fixture run exercised Vision, Core
Image and production live_loop through real OBS output with cleanup. Conferencing-app reception was not checked. Initial
camera permission requests from T3 Code/Python failed for both direct AVFoundation
and OpenCV; native device capture remains pending permission/hardware verification.
A Terminal hardware attempt exposed use of the inputPriority preset, which is
unsupported on macOS despite being exported by the Python binding. Setup now
attaches input/output before selecting activeFormat/FPS directly. Mocked regression covers unsupported explicit preset, setup
ordering and format-failure cleanup; hardware retest from Terminal remains pending.
Tests with mocked camera startup do not establish hardware delivery.

Other remaining gaps:

- No unified portable pacing or portable consumer/pause capability contract.
- Screen.setup still lacks width/height metadata expected by default-output path;
  screen sharing was explicitly excluded.
- No hot input switching, user-facing file output, HTTP service or cross-process control.
- Globals remain for import-time environment constants and legacy helper compatibility.
- No live-camera latency, power or segmentation-quality benchmark on moving people.
- Legacy demos, stale mypy configuration and historical TODO entries remain.

See [remaining improvement plan](improvement-plan.md).
