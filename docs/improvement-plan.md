# Improvement plan

Updated 2026-10-02. Session/control and optional native-backend work is implemented;
typing and opt-in boundary stabilization are also implemented; hardware acceptance
remains outstanding. Preserve macOS and Linux behavior and existing
CLI commands. Do not add a server or generic plugin framework without a concrete
product requirement.

## Goal and review cadence

Goal: improve macOS capture/processing and predictable run/session ownership while
preserving the supported CLI, portable fallback, test seams and OBS output.

Reprioritize after each completed section, hardware result or scope change. Before
starting the next section, review the full completed/remaining/deferred log against
this goal, update acceptance evidence and explain any priority change. New visual
issues belong in the backlog unless promoted deliberately. Keep each validated
implementation section independently committed.

Latest review: corrected native capture/cadence is confirmed. User activated typing
and boundary work; fixture comparison and opt-in smoothing are complete. Repeated lifecycle and actual OBS/conferencing delivery are
the next acceptance checks; remote CI, screen sharing and an own camera extension
remain excluded.

## Completed

- Added macOS/Linux Python 3.14 verification workflow; remote validation excluded by user.
- Removed import-time listeners, stdin threads and config writes; explicit controls.
- Added RunSession-owned settings, bounded ordered command queue, validated mutations,
  atomic persistence and bounded recording/replay.
- Applied common freeze behavior consistently to camera commands.
- Opened input once, validated negotiated metadata and handled partial startup cleanup.
- Scoped CLI model/timestamp/motion/native-context state to each run with cleanup.
- Declared OpenCV dependency and optional native PyObjC extra.
- Added optional Vision masks, Core Image backgrounds and AVFoundation capture.
- Excluded OBS output from native input selection using manufacturer/model identity.
- Replaced obsolete mypy config; strict checks now cover 20 modules plus static frame/mask regressions in make check.
- Replaced Frame = Any with uint8 BGR arrays; float32 masks, effect composition, native adapters and output ownership now have checked contracts.
- Replaced dynamic background-method dispatch with typed callables; validated CLI context and explicit closed-output guards.
- Added list-cameras to inspect eligible native indices, formats and excluded OBS output without opening capture.
- Repaired legacy face entrypoint and isolated box-demo tracker state.
- Resolved startup settings once with CLI overrides, validation and actionable Linux-extra errors.
- Centralized monotonic frame pacing across outputs; removed redundant deadline GUI polling and cumulative jitter drift.
- Added live-camera measurement script; fixture-to-OBS smoke passed, Terminal live capture confirmed; native-format override found and fixed with retained device lock.
- Passed three fixture -> Vision fast -> actual OBS producer start/stop cycles with input/effect/output cleanup assertions. This does not verify physical-camera restarts or consumer reception.
- Added repeatable processing benchmark and measured portable float32 improvement.
- Typed face pixel bounds, geometry, crop transitions and adapter metadata; preserved compatibility helpers.
- Added opt-in motion-aware temporal mask smoothing and repeatable image/video quality comparisons; fixture evidence recorded in [segmentation comparison](segmentation-comparison.md).
- Confirmed corrected native camera -> Vision fast -> preview at 640x480/30 from Terminal: 300 measured frames, 29.96 FPS.

## Current checkpoint and next checks

Core session/control ownership, startup settings, native capture/processing adapters,
preview output, pacing, typing and legacy cleanup are implemented. The 640x480
native capture fix is now hardware-confirmed. Type-safety expansion, targeted
effect/output modernization and camera-selection diagnostics are complete.
The typing/stabilization 2026-10-02 checkpoint passed 153 local tests, strict mypy, Black, Flake8 and
compile checks on Python 3.14. Hardware-dependent evidence remains separate.

| Priority | Remaining work | Acceptance evidence |
| --- | --- | --- |
| 1 | Repeated physical-camera starts/stops and OBS/conferencing reception | Authorized Terminal runs with cleanup; actual reception in a conferencing client. Fixture producer restarts passed; T3 camera permission remains unavailable |
| Completed | Face prediction, geometry and adapter metadata typing | Strict contracts and regression tests; integer pixel division corrected; compatibility helpers retained |
| Implemented; visual acceptance outstanding | Quality/cost comparison and opt-in boundary stabilization | Four real backends/quality configurations compared on fixtures; 65% fast static variation reduction; recorded/live hair, hands and low-light noise still needed |
| When hardware is available | Linux consumer detection and native output parity | Real V4L2 consumer smoke check; mocked ownership checks already pass |

Ordering reflects work/value: close the hardware evidence gap when possible, then
make targeted changes supported by concrete defects. Broad rewrites, compatibility
removal without caller evidence, and extra benchmarking stay below current user
needs. Camera-selection diagnostics addressed repeated input-selection failures.

Remote CI validation is explicitly excluded. Python 3.14 is the only supported
runtime. Screen sharing and an own signed virtual-camera extension are excluded;
retain OBS output.

## Boundary refinement checkpoint

- Background-blur boundary shifts/jitters many times per second in the live
  Vision fast preview (user observation, 2026-10-02).
- Compared quality-level cost and fixture output; added temporal mask
  stabilization with motion-aware reset/adaptation. Spatial feathering remains
  pending fine-detail evidence.
- Acceptance: steadier static edges and smoother hair/hands without obvious
  motion trails, delayed subject departure or lost fine detail; measure added
  cost and preserve the 640x480/30 target.
- Activated by user request. Opt-in motion-aware mask refinement now exists; defaults stay unchanged.
- Fixture comparison is complete: [results and commands](segmentation-comparison.md).
  Moving hair/hands and realistic low-light/subject-departure acceptance remain
  unverified. Vision fast misclassifies black input even without smoothing.

External runtime control/API, hot input switching and native-frame experiments
remain future product/architecture decisions, not active implementation tasks.
The sections below retain the design constraints for that later work.

## Shared control direction

CLI and keyboard/stdin now share RunSession.submit(Command). Submission reports
acceptance; apply_commands runs on the frame thread and returns applied/rejected
results. This establishes an in-process seam without choosing an HTTP transport.
Shutdown stops adapters, rejects subsequent commands and closes owned resources.

A future API should submit through the same behavior, expose separate status reads,
and distinguish accepted from completed work. It must not mutate effect globals or
spawn an interactive CLI as its control interface. RunSession currently owns
preparation/control/recording; CLI scope owns effects and live_loop owns adapters.
Deepen session ownership if an API requires controlling a whole run lifecycle.

Cross-process CLI control requires explicit IPC. Decide local-only versus remote,
single versus multiple sessions, authentication, supported mutations and restart
semantics before implementing transport. Hot input switching is separate scope.

## Native processing decisions

Keep portable defaults and OBS output. Optional native paths currently copy BGR
arrays between capture, Vision, Core Image and pyvirtualcam. Measured processing
results do not justify automatically selecting them or introducing a richer frame
representation yet. See [benchmark report](macos-backends.md).

A future native-frame experiment must define ownership, lifetime, pixel format,
strides, timestamps, orientation and color metadata, then measure complete workload
including output materialization. Native crop/resize/brightness is deferred with
that experiment. GStreamer, custom Metal kernels and ML frameworks remain unjustified
for current synchronous webcam effects. An own signed camera extension was excluded
by user choice; OBS remains the output provider.

Screen sharing was explicitly excluded. Its existing metadata gap and any
ScreenCaptureKit migration remain separate future work.

## Portability and verification

Keep native Linux delivery as an adapter and do not replace it before proving
format conversion, pacing and consumer parity. Lazy-load platform dependencies.
Keep kernel setup outside normal startup. Preserve existing config names/path when
changing settings resolution. Adapter hardware checks and CI fixture tests must
remain distinct; fixture throughput is not live-camera FPS.

Retain headless visual fixtures and tests for real CPU models. Add runtime-control
transport tests only once transport is selected. Future migration infrastructure
must follow append-only project instructions if databases are introduced.
