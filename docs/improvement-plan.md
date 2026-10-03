# Improvement plan

Updated 2026-10-02. Session/control and optional native-backend work is implemented;
remaining work below is proposed. Preserve macOS and Linux behavior and existing
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

Latest review: corrected native capture/cadence is confirmed. Boundary polish is
explicitly deferred. Repeated lifecycle and actual OBS/conferencing delivery are
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
- Replaced obsolete mypy config with strict checks for eight owned/core modules in make check.
- Repaired legacy face entrypoint and isolated box-demo tracker state.
- Resolved startup settings once with CLI overrides, validation and actionable Linux-extra errors.
- Centralized monotonic frame pacing across outputs; removed redundant deadline GUI polling and cumulative jitter drift.
- Added live-camera measurement script; fixture-to-OBS smoke passed, Terminal live capture confirmed; native-format override found and fixed with retained device lock.
- Added repeatable processing benchmark and measured portable float32 improvement.
- Confirmed corrected native camera -> Vision fast -> preview at 640x480/30 from Terminal: 300 measured frames, 29.96 FPS.

## Current checkpoint and next checks

Core session/control ownership, startup settings, native capture/processing adapters,
preview output, pacing, typing and legacy cleanup are implemented. The 640x480
native capture fix is now hardware-confirmed. Continue validation of these changes
before adding new architecture or visual polish.

| Priority | Remaining check | Acceptance evidence |
| --- | --- | --- |
| 1 | Repeated native start/stop and actual OBS/conferencing delivery | Several authorized Terminal runs with cleanup; camera reception in a conferencing client |
| 2 | Broader native quality/cost comparison | Compare fast/balanced/accurate and portable masks on moving hair/hands/low light; record latency/memory and visual results |
| 3 | Linux consumer detection and native output parity | Real V4L2 consumer smoke check when Linux hardware is available |

Remote CI validation is explicitly excluded. Python 3.14 is the only supported
runtime. Screen sharing and an own signed virtual-camera extension are excluded;
retain OBS output.

## Deferred visual polish

- Background-blur boundary shifts/jitters many times per second in the live
  Vision fast preview (user observation, 2026-10-02).
- Investigate quality-level tradeoffs, edge feathering and temporal mask
  stabilization with motion-aware reset/adaptation.
- Acceptance: steadier static edges and smoother hair/hands without obvious
  motion trails, delayed subject departure or lost fine detail; measure added
  cost and preserve the 640x480/30 target.
- Deferred by user choice. No mask-refinement implementation has been added.
  Resume as a separate section after the current improvement checkpoints.

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
