# Current state

Reviewed 2026-10-05. Python 3.14 only. Portable processing and macOS/Linux adapters
remain supported. Native macOS menu is optional; installed CLI works independently.

## Supported behavior

- Camera commands: crop-cam, bg-blur, bg-color, bg-swap, brighten, track-face,
  test-loop. Common options work before or after the command.
- Screen sharing: explicit region or macOS area/screen/visible picker, fresh crop
  state, optional outside border, preview or virtual-camera output.
- Per-run crop/padding, ordered bounded controls and 256 MiB default recording cap.
  Keyboard/stdin adapters start explicitly; import/help starts no listeners.
- Stable face selection/framing with bounded zoom and independent pan/zoom response.
- MediaPipe segmentation, optional Vision/Core Image and opt-in motion-aware smoothing.
- Independent capture/output sizing and FPS; optional repeat mode keeps latest-frame
  delivery independent of processing. See [frame delivery](frame-delivery.md).
- SQLite saved launch profiles shared by CLI and menu. Composition orders tracking,
  background transformation, then brightness. Tracking background inference runs at
  fixed output dimensions to avoid rebuilding models during zoom.
- Local JSONL helper manages one session through explicit Start/Stop and status.
  Configuration changes require a stopped session. Native menu exposes profiles,
  camera/effect selection, settings and errors. Standalone controls, bounded
  scrolling and helper reconnection are available. Saved macOS camera identities
  prevent substitution after enumeration changes; independent profile output
  overrides inherit capture settings when absent. Local protocol accepts bounded
  strict JSON and recovers after malformed/oversized requests.
  See [menu guide](macos-menu.md).
- Persistent exact-shape delegate calibration cache, with hardware/software
  fingerprint, 30-day expiry and 128-entry bound. Probe failures use CPU without
  persisting failure. Cold calibration remains necessary for uncached shapes.

## Configuration and ownership

CLI startup settings resolve once: CLI > environment > defaults. See
[env.example](../env.example). Input/output default to 640x480/30. Crop/padding
retains `~/.webcam-mods.conf`; saved launch profiles use a separate SQLite store.
Native capture selects supported dimensions/FPS, retains its device configuration
lock, excludes OBS from input selection, and fails rather than silently switching
camera/backend. `auto` maps OpenCV camera identity to AVFoundation on macOS.

The processing worker owns capture/effect cleanup in repeat mode. Tracking resources
follow the same ownership contract. A ten-second shutdown timeout cannot safely
interrupt arbitrary native calls; the worker retains resources until processing
returns. The local controller refuses another session after such a timeout.
The menu can terminate its helper during app shutdown after bounded graceful waits.

## Verification evidence

Headless tests cover CLI parsing, profile validation/persistence, local protocol,
session state/restarts, timeout ownership, frame validation, processing, recording,
pacing, native buffer handling and partial startup cleanup. `just verify` runs
static checks and the full suite. `just e2e` writes deterministic real-model
pipeline artifacts; it is not a camera or conferencing test.

Latest local checkpoint: 372 tests, Black, configured Flake8 and strict mypy pass.
Native compilation, model/transport tests with a real Python helper, plist and
signature checks pass. The standalone controls window was inspected through UI
automation: Advanced scrolling, independent output controls, fixed Start/Quit
buttons and clean Quit passed without starting capture. App Camera permission
behavior remains unverified.

2026-10-05 calibration measurement, local macOS ARM64: a materialized 640x480
astronaut fixture selected the segmentation delegate in 4.407751 seconds with
six subprocess probes. A fresh process reused that decision in 0.007089 seconds
with zero probes. Timings cover delegate selection only, excluding imports and
fixture loading. This establishes warm-start probe avoidance, not live FPS or power.

Historical hardware evidence, 2026-10-03, authorized Terminal:

- Three physical-camera -> Vision fast/OpenCV blur -> OBS producer cycles at
  640x480/30 delivered 29.88-29.95 FPS, with cleanup verified.
- Three auto/AVFoundation capture-only 1280x720/30 cycles retained format through
  five-second startup pauses and delivered 30.01-30.06 FPS.
- Screen and preview/OBS adapter smokes passed. Native buffer/model fixture tests
  and real-model headless processing passed.
- User accepted observed segmentation quality after motion-aware stabilization;
  dedicated hair/hand/low-light stress coverage and power remain unmeasured.

See [backend report](macos-backends.md) for older workloads and limits. No claim
of current native-menu camera permission or receiving-client acceptance follows
from these historical Terminal runs.

## Remaining limits

Conferencing reception and 720p effects/output (review item 2), and realistic
quality/latency/power measurements (item 6), are deferred by user. macOS OBS does
not expose reliable receiver count to this output adapter; automatic activation
is deferred. Linux real-device acceptance, current Windows behavior and remote
CI validation remain unverified. Menu app is locally ad hoc signed and depends
on an installed Python runtime; standalone distribution/notarization is future work.

Native saved IDs reach AVFoundation directly and are revalidated at acquisition.
Explicit OpenCV capture still opens a numeric index; a hotplug between identity
lookup and acquisition can change that index. Prefer native capture for stable
identity selection. Non-macOS profiles continue using numeric indices.

No hot input switching, window-following screen capture, remote HTTP endpoint,
custom camera extension or native-frame/zero-copy abstraction is implemented.
See [improvement plan](improvement-plan.md) and [backlog](../TODO.md).
