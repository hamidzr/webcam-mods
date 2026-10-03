# Improvement plan

Updated 2026-10-03. Session/control and optional native-backend work is implemented;
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

Latest review (2026-10-03): user requested selection hints, output-aspect area
selection and a persistent capture-region indicator. Added opt-in Swift flags
for live tips, fitted preview/selection, and global-point borders with geometry
updates and owner-exit cleanup; existing recorder options are preserved. Sharing
now owns border cleanup and crop updates; fresh screen crop state avoids hidden
saved camera crops. All 272 tests and static checks pass. Live screenshots
confirmed hints and border geometry updates. Installed CLI delivered three real
400x300 screen frames to 640x480/30 preview with border cleanup. Swift fitting
checks covered four drag directions; legacy screen/visible geometry matched the
pre-change helper. Multi-display and conferencing acceptance remain.

Previous review (2026-10-03): user activated screen-sharing selection after reviewing
~/scripts recording patterns. Added explicit macOS area/screen/visible selection
through installed select-region, with global point geometry for MSS and rejection
of coordinate conflicts or failed selection before resources open. All 268 tests
and static checks pass via just verify; installed CLI refreshed and help/conflict
behavior checked. Interactive selection and receiving-app delivery remain manual
acceptance. Camera/screen switching and ScreenCaptureKit window-following remain
separate implementation work.

Previous review (2026-10-03): user accepted observed blur-edge quality and requested
moving on. Visual quality checkpoint is accepted based on user observation; no
claim of dedicated hair/hand/low-light coverage or live cost measurement is added.
Smoothing remains opt-in. Next existing acceptance gap is OBS/conferencing
reception and 720p effects/output; power presets remain deferred.

Previous review (2026-10-03): user reactivated our blur-edge stabilization and
excluded reliance on macOS Portrait. Removed the global 2% image-motion bypass:
local motion now resets only changed pixels and their one-pixel neighborhood,
keeping stationary edges stabilized during hand movement. Synthetic regression
reproduced the original failure and now verifies immediate hand arrival/departure.
Vision fast fixture static variation reduction stays 65%; translation smoothing
mean/p95 measured 0.57/0.66 ms at 640x480. Live benchmark now accepts
`--mask-smoothing` and records it in workload metadata. All 263 tests and static
checks pass via `just verify`. Smoothing stays opt-in;
live hair/hand/low-light/trail acceptance and whole-pipeline power remain open.
Power presets, remote CI and an own camera extension remain deferred or excluded.

Previous review (2026-10-03): authorized Terminal hardware checks passed. Three
physical-camera -> Vision fast/OpenCV blur -> OBS producer cycles delivered
100 measured frames each at 640x480/30, with 29.88-29.95 FPS and cleanup verified
in every cycle (`dist/benchmarks/lifecycle.json`). Three capture-only auto ->
AVFoundation cycles retained 1280x720/30 after five-second startup pauses,
delivered 120 frames each at 30.01-30.06 FPS and closed every adapter
(`dist/capture-check.json`). These close the repeated producer lifecycle and
capture-only format-retention gaps. Conferencing reception and 720p effects/output
remain unverified. User requested moving on; hardware consumer acceptance stays
open without blocking a new product decision. Power presets, visual polish,
remote CI and an own camera extension remain deferred or excluded. No additional
implementation section is activated.

Previous review (2026-10-03): OpenCV accepted 1280x720 at startup, then returned
864x480 after delegate calibration in the user's session. Default `auto` capture
now prefers native AVFoundation with the existing retained format lock, preserving
the selected OpenCV camera identity. Explicit backend choices remain available.
Midstream drift errors distinguish format loss from unsupported startup requests.
Added a capture-only pause/restart check with partial JSON evidence and safe
permission preflight. All 258 local tests and static checks pass. The installed
CLI was refreshed with `just install`; its source and default backend were verified.
This headless
context lacks Camera authorization, so sustained hardware validation remains
outstanding; the exact external trigger for the OpenCV format change is unverified.

Previous review (2026-10-03): user prioritized independent capture/delivery
resolution and FPS at launch. Existing controls remain; OpenCV negotiation now
checks actual frames and reported FPS instead of accepting unsupported requests.
Launch examples and limits are documented in [quality settings](quality-settings.md).
Automatic battery/AC/Low Power Mode presets are deferred in [TODO](../TODO.md);
runtime format switching remains separate. Hardware format/cadence acceptance
remains outstanding. All 204 local tests and static checks pass; the local
editable CLI was reinstalled and its input/output help verified.

Previous review (2026-10-03): user activated CLI help/option-placement polish and
screen sharing modernization. Grouped help and shared options now cover both
command positions, and MSS screen capture uses shared session/output ownership.
193 local tests and all static checks pass. Headless screen/CLI regression checks
cover these changes. Real macOS screen capture passed three frames through preview
and three through OBS at 640x480/30 with cleanup; consumer reception and sustained
capture acceptance remain. Camera hardware
acceptance remains outstanding. Remote CI and an own camera extension stay excluded.

Previous review (2026-10-03): repeated hardware lifecycle acceptance remains highest
priority. Added `benchmark_live.py --cycles` so an authorized Terminal can exercise
fresh capture/effect/output ownership and retain per-cycle evidence, including
partial failure progress. Headless orchestration checks do not close the hardware
or consumer-reception evidence gap. No priority change.

Previous review: corrected native capture/cadence is confirmed. User activated typing
and boundary work; fixture comparison and opt-in smoothing are complete. Repeated lifecycle and actual OBS/conferencing delivery are
the next acceptance checks; remote CI and an own camera extension
remain excluded.

## Completed

- Grouped CLI help with complete common options in command help; shared options
  work before or after commands with command-side override precedence.
- Modernized MSS screen sharing with complete metadata, typed contiguous BGR
  frames and shared settings, session controls, pacing and output cleanup.
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
- Added repeatable live benchmark cycles with cleanup checks, fresh resources,
  per-cycle metrics and failure/interruption progress reports. Successful
  single-cycle reports retain their existing shape.

## Current checkpoint and next checks

Core session/control ownership, startup settings, native capture/processing adapters,
preview output, pacing, typing and legacy cleanup are implemented. The 640x480
native capture fix is now hardware-confirmed. Type-safety expansion, targeted
effect/output modernization and camera-selection diagnostics are complete.
The typing/stabilization 2026-10-02 checkpoint passed 153 local tests, strict mypy, Black, Flake8 and
compile checks on Python 3.14. Hardware-dependent evidence remains separate.

| Priority | Remaining work | Acceptance evidence |
| --- | --- | --- |
| Completed | Repeated physical-camera/OBS producer starts/stops; 720p capture retention | Three 640x480/30 effect/output cycles passed with cleanup; three 1280x720/30 capture-only pause/restart cycles passed |
| Open acceptance | OBS/conferencing reception and 720p effects/output | Confirm moving video across restarts in receiving client; capture-only 720p evidence does not validate effects/output |
| Completed | Face prediction, geometry and adapter metadata typing | Strict contracts and regression tests; integer pixel division corrected; compatibility helpers retained |
| User quality accepted; measurement remains | Quality/cost comparison and opt-in boundary stabilization | Four real backends/quality configurations compared on fixtures; 65% fast static variation reduction; user accepted observed quality; dedicated stress coverage and live cost remain unmeasured |
| When hardware is available | Linux consumer detection and native output parity | Real V4L2 consumer smoke check; mocked ownership checks already pass |

Ordering reflects work/value: retain remaining hardware acceptance checks, then
make targeted changes supported by concrete defects. Broad rewrites, compatibility
removal without caller evidence, and extra benchmarking stay below current user
needs. Camera-selection diagnostics addressed repeated input-selection failures.

Remote CI validation is explicitly excluded. Python 3.14 is the only supported
runtime. An own signed virtual-camera extension is excluded;
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
  Local motion no longer disables stabilization elsewhere. Moving hair/hands
  and realistic low-light/subject-departure acceptance remain
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

Screen sharing now uses MSS through the shared adapter/session/output lifecycle.
Actual consumer reception and sustained capture acceptance remain; ScreenCaptureKit migration
stays separate future work.

## Portability and verification

Keep native Linux delivery as an adapter and do not replace it before proving
format conversion, pacing and consumer parity. Lazy-load platform dependencies.
Keep kernel setup outside normal startup. Preserve existing config names/path when
changing settings resolution. Adapter hardware checks and CI fixture tests must
remain distinct; fixture throughput is not live-camera FPS.

Retain headless visual fixtures and tests for real CPU models. Add runtime-control
transport tests only once transport is selected. Future migration infrastructure
must follow append-only project instructions if databases are introduced.
