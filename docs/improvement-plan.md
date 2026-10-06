# Improvement plan

Updated 2026-10-05. Preserve Python processing, existing CLI commands, macOS/Linux
adapters and OBS output. Prefer bounded changes supported by concrete defects.

## Completed implementation and remaining acceptance

| Priority | Implemented work | Evidence / remaining acceptance |
| --- | --- | --- |
| 1 | Tracking cleanup ownership | Direct CLI timeout regression confirms detector, tracker and background stay owned until worker cleanup |
| 3 | Native macOS menu and local control | Native build, real-helper transport/model tests, plist and signature checks pass; visual layout and Camera permission remain unverified |
| 4 | Saved profiles and effect combinations | Validated SQLite persistence, CLI commands, composition-order and cleanup regressions pass |
| 5 | Predictable startup calibration | Persistent-cache and shape regressions pass; 640x480 fixture selection 4.408 s cold vs 0.007 s fresh-process cache hit |
| Documentation | Reconcile user/developer guidance | Current behavior, dated historical evidence and deferred items consolidated; installed commands checked |

The numbers retain the ordering from the project review. See [current state](current-state.md)
for implemented behavior and verified limits. The native menu is an optional
SwiftUI shell around the shared Python worker. It owns one explicit session;
changing a running configuration requires Stop followed by Start.

## Deferred by user

- Item 2: conferencing-client reception and 1280x720 effects/output acceptance.
  Existing 720p capture-only evidence does not validate the complete output path.
- Item 6: realistic moving-person quality, latency and whole-pipeline power.
  Keep smoothing opt-in; fixture timings do not establish battery savings.
- Automatic battery/AC/Low Power Mode presets, pending whole-pipeline evidence.
- Remote CI validation. CI configuration exists; local success is separate evidence.
- Automatic receiver-triggered activation. OBS/pyvirtualcam provides no reliable
  portable receiver count on macOS; explicit Start/Stop remains supported.

## Later product decisions

- Camera/screen switching and window-following capture.
- Stable camera identity across changes to physical input enumeration.
- Visual overlays, orientation controls, eye tracking, webcam stitching and animation.
- Native-frame/zero-copy experiments only after a measured workload justifies them.
- Linux real-device consumer monitoring and output parity acceptance.

An own signed virtual-camera extension remains excluded. OBS supplies the macOS
extension. No remote HTTP control endpoint is needed for the local menu.

## Completed foundation

- Immutable validated startup settings; shared options before/after commands.
- Per-run effects, crop state, bounded ordered controls and bounded record/replay.
- Typed frame/mask contracts, input validation and atomic crop persistence.
- Native AVFoundation capture with retained format lock and OBS-input exclusion.
- Optional Vision/Core Image, portable defaults and opt-in motion-aware smoothing.
- Bare final-frame preview and independent repeated-frame delivery.
- Interruptible capture retries and worker-owned deferred cleanup.
- Screen selection/border integration with fresh screen crop state.
- Locked Python 3.14 development, installed wheel snapshots and headless E2E checks.

Historical hardware evidence from 2026-10-03: three 640x480/30 physical-camera,
Vision fast/OpenCV blur, OBS producer cycles delivered 29.88-29.95 FPS with cleanup.
Three 1280x720/30 capture-only cycles retained format after five-second startup
pauses and delivered 30.01-30.06 FPS. Producer completion does not prove reception.
