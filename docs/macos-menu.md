# macOS app and local control

The optional SwiftUI app provides a main window and menu bar controls for one
camera session.
It uses the existing Python effects and OBS Virtual Camera output. Requires macOS
13 or newer, Xcode command-line tools and an installed Webcam Mods Python runtime.

```sh
just menu-install
open "$HOME/Applications/Webcam Mods.app"
```

`menu-install` refreshes the Python snapshot and builds a locally ad hoc signed
bundle. `menu-build` builds under `dist`; `menu-check` compiles and runs native
transport/model self-tests, validates the plist and checks the signature. The app
references the uv-tool runtime rather than embedding Python. Reinstall/rebuild
both after changes; removing the uv tool makes the app's runtime unavailable.

## Controls

Launch Webcam Mods to open its resizable main window. Choose a camera and
background effect, optionally enable face tracking, then adjust brightness and
press Start camera. Settings and saved profiles live beside the video preview in wide windows,
and below it in narrow windows.
The menu bar contains status, Start/Stop, Open window and Quit; Open window or
reopening the app brings back the same window.

Output defaults to **Preview only**, which tests camera and effects without OBS.
Choose **OBS Virtual Camera** to publish video to conferencing clients while
previewing the same processed output in the window. Output mode is selected per
app launch and is separate from saved effect profiles. Closing or minimizing the
window pauses preview requests and encoding; a running camera session continues
until Stop or Quit. Preview keeps only the latest JPEG in memory, fits within
640x480 and follows delivered output frames. The window polls at the negotiated
output FPS, including independent output rates and nearby native rates such as
29.97 FPS. It shows final output framing and effects at
reduced resolution; output delivery retains configured dimensions and FPS.

Camera permission is requested on Start. Enable Webcam Mods under System Settings >
Privacy & Security > Camera if access is denied. OBS extension setup is separate;
see [installation](installation.md). The window checks for the modern OBS camera
extension without opening a camera. When detected, it shows an OBS readiness
checkmark. Otherwise, it shows download/setup links and extension approval steps
for the installed macOS version. Preview remains available without OBS; virtual
output requires the extension. Check again or return to the app after setup to
refresh readiness. OBS must stop its own Virtual Camera before Webcam Mods starts
publishing; extension detection does not test exclusive output access.

Status distinguishes Idle, Starting, Running, Stopping and Error. Running follows
the first processed frame delivered to output. Starting can include model download
or uncached CPU/Metal calibration. Stop releases capture and processing before
another session starts. Edit settings while stopped; changes do not apply live.
The menu does not automatically activate when another application opens a camera.

Background choices are original, blur, solid gray and image. Tracking combines
with background and brightness. Effect order: track/crop, fixed-size background
processing, brightness, final output sizing. Tracking uses standard framing
controls; advanced CLI tracking options remain available through `track-face`.
Image mode includes an offline thumbnail gallery: Warm study, Quiet office and
Soft shelves. Entering Image with no previous image selects Warm study; click a
thumbnail to switch, or Choose your own to open an image file. Saved profiles
retain the selected image path. Built-in images live inside the app bundle, so
keep it at the same location when reusing saved profiles. Image provenance and
generation prompts are in [background credits](../macos/Backgrounds/README.md).
Image mode also offers Blur image background and the same blur strength control.
Image blur uses a box filter with either processing backend. The resized, blurred
image is cached per session and rebuilt only when background settings or processing
dimensions change. CLI equivalent: `webcam_mods bg-swap --blur --blur-kernel-size 31`.
Brightness adds HSV value, 0..255. Advanced settings expose capture size/FPS,
processing FPS, backend choices, repeat delivery and optional mask smoothing.
Loading picture selects TV color bars or animated TV static. Both preview and
virtual-camera output receive the same loading frames with a startup message
while capture, model initialization and calibration run. Live frames replace them
automatically; startup preview remains available while the session is starting.
Requested capture size/FPS must be supported together by the selected camera.
Native capture prefers an exact FPS match and accepts supported rates within 1%
of the request, including 29.97/30. It reports the negotiated input FPS; repeat
delivery retains the independently requested output cadence.
Output inherits capture dimensions/FPS by default; disable "Use capture settings for output" in
Advanced to set independent delivery dimensions and cadence. Repeat mode maintains
output cadence using the latest processed frame.

The menu defaults to explicit AVFoundation capture. Camera selection and saved
profiles retain a stable device identity; reordered indices do not select another
camera. Missing or excluded saved devices block Start instead of falling back.
Legacy index-only profiles still load and acquire an identity when selected in
the menu. Inventory follows the chosen backend, including auto's OpenCV-compatible
index mapping. Unavailable cameras and OBS output are excluded. Native capture forwards the saved
identity to AVFoundation and revalidates it when opening. Explicit OpenCV still
opens an index, so a hotplug between lookup and acquisition can change selection;
prefer native capture for stable identity guarantees.

On first connection, the desktop app saves five starter profiles: Natural,
Soft Background Blur, Auto Framing, Blur + Auto Framing and Studio Gray. Each uses
640x480 at 30 FPS. They are editable local profiles; existing names are preserved,
and later launches retain edits and do not restore deleted starters.

Save named profiles to reuse settings. A selected profile shows "(modified)"
when current settings differ from its saved configuration; editing does not
automatically persist changes. Camera enumeration-only index changes do not mark
an identity-bound profile modified. Start remains disabled while inventory is
refreshing; stale replies from another refresh/backend are ignored.

Save named profiles to reuse settings. Saving an existing name replaces its
configuration. Deletion asks for confirmation in the window. Profiles are local,
validated and stored transactionally in
`$XDG_CONFIG_HOME/webcam_mods/profiles.sqlite3`, defaulting to
`~/.config/webcam_mods/profiles.sqlite3`. Crop/replay settings remain separate in
`~/.webcam-mods.conf`.

Quit sends a graceful helper shutdown. If native processing blocks beyond bounded
waits, the app terminates its managed helper. A worker timeout prevents another
session from starting in that helper; quit and reopen the app. No camera frames
or telemetry are sent to a service by the control interface.

## CLI profiles

```sh
printf '%s\n' '{"effect":"blur","track":true,"brightness":20,"capture":"avfoundation"}' > /tmp/call-profile.json
webcam_mods profile-save Call /tmp/call-profile.json
webcam_mods profiles-list
webcam_mods profile-run Call
```

Back up or edit a saved profile with:

```sh
webcam_mods profile-export Call /tmp/call-backup.json
webcam_mods profile-save Call /tmp/call-backup.json
webcam_mods profile-delete Unused
```

Export writes a complete JSON configuration atomically. Existing files are
preserved unless `--overwrite` is passed. Invalid stored profiles cannot export.
Stored configuration decoding is limited to 64 KiB; deep/malformed JSON and
invalid settings produce sanitized errors. Corrupt records do not prevent listing valid profiles: `profiles-list` writes
valid JSON to stdout and named diagnostics to stderr. The menu displays separate
warnings. Use `profile-delete NAME` to remove a damaged record, or `profile-save`
to replace it with a validated configuration. No damaged content is echoed.

`profile-run` uses saved settings and disables interactive crop/replay. Common
startup flags are rejected rather than silently overriding the profile. Edit and
resave configuration to change it. Ctrl-C stops the run. Existing effect commands
continue accepting their common flags normally.

Profile fields and defaults:

| Field | Default | Meaning |
| --- | --- | --- |
| input_device | 0 | Selected backend's camera index |
| width, height | 640, 480 | Requested capture dimensions |
| fps | 30 | Capture request |
| camera_id | null | Stable macOS device identity; legacy index selection when absent |
| output_width, output_height | null | Independent delivery dimensions; inherit capture when null |
| output_fps | null | Independent delivery cap; inherit capture when null |
| effect | plain | plain, blur, color, image, track |
| track | false | Combine tracking with selected background |
| brightness | 0 | Added HSV value, 0..255 |
| blur_kernel | 31 | Positive odd box-blur kernel or Core Image radius mapping |
| color | 192 | Gray background, 0..255 |
| image_path | empty | Image required for image effect |
| image_blur | false | Cache image background blur using blur_kernel |
| capture | auto | auto, opencv, avfoundation; menu defaults avfoundation |
| segmentation | mediapipe | mediapipe or vision |
| processing | opencv | opencv or coreimage |
| repeat_frames | true | Repeat latest frame at output cadence |
| processing_fps | 30 | Fresh-frame cap in repeat mode |
| signal_pattern | color-bars | Loading/paused picture: color-bars or noise |
| smoothing | false | Opt-in motion-aware mask stabilization |

## Local protocol

Launch `python -m webcam_mods.control` using the installed environment. Transport
is stdin/stdout JSONL, protocol version 1. Logs use stderr. No network listener
or authentication endpoint exists; the caller owns the helper process and pipes.

```json
{"id":1,"method":"hello","params":{}}
{"id":1,"result":{"protocol":1,"version":"0.2.0"}}
{"id":2,"method":"start","params":{"config":{"effect":"blur","capture":"avfoundation"}}}
{"event":"status","data":{"state":"starting"}}
{"id":2,"result":{"state":"starting"}}
```

Responses use `result` or `error` with the same request ID. Events may arrive
between responses; correlate by ID rather than position. A start response means
accepted, not running. Status events reflect actual lifecycle progress.
Requests are limited to 64 KiB UTF-8. Oversized lines are drained in bounded
chunks; the next request remains usable. IDs must be safe-range integers or
nonempty strings of at most 128 characters. Non-finite numbers, duplicate members
and malformed objects are rejected without echoing payload contents. Errors leave
the helper available.

| Method | Parameters | Result |
| --- | --- | --- |
| hello | {} | protocol and package version |
| cameras.list | capture backend, optional | Array of id/index/name objects; macOS only |
| profiles.list | {} | Array of valid name/config objects |
| profiles.seed_defaults | {} | Save starter pack once without replacing existing names; true |
| profiles.errors | {} | Array of name/error objects for damaged profiles |
| profiles.save | name, config | true |
| profiles.delete | name | true |
| start | config, or profile name; optional output: virtualcam (default) or preview | Current state |
| preview.get | {} | Latest {jpeg: base64, width, height}, or null |
| stop | {} | State after bounded shutdown |
| status | {} | Current state, optional error and negotiated output_fps once output opens |
| shutdown | {} | Stop result, then helper exits |

EOF also stops the session. Simultaneous sessions are rejected. Configuration
validation occurs before acquiring resources. The controller refuses restart
following an unsafe shutdown timeout. Status then includes `restart_required:
true`; late cleanup cannot clear the terminal error. Quit/reopen the app or
replace the helper process before another session.

## Verification limits

`just menu-check` compiles and runs native transport/model tests, including JPEG
decoding, single in-flight preview requests, stale-response rejection, stop/hide
cleanup, OBS readiness, negotiated preview cadence and timeouts. Python regressions
verify final-frame routing in direct and repeat modes, preview-only output without
OBS, bounded encoding and session
cleanup. These checks do not establish physical-camera permission behavior,
conferencing reception, realistic quality or power behavior.

Settings scroll; Start/Stop and Quit remain outside the scrolling area. A
disconnected helper exposes Reconnect after its old process exits. The footer
shows app build identity and connected backend version. Launching normally opens
the main window; the older `--show-controls` launch argument remains harmless.
Standalone distribution/notarization is future work.
