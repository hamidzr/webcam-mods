# macOS menu and local control

The optional SwiftUI menu app provides explicit controls for one camera session.
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

Open the camera icon in the menu bar. Choose a camera and background effect,
optionally enable face tracking, then adjust brightness and press Start. Camera
permission is requested on Start. Enable Webcam Mods under System Settings >
Privacy & Security > Camera if access is denied. OBS extension setup is separate;
see [installation](installation.md).

Status distinguishes Idle, Starting, Running, Stopping and Error. Running follows
the first processed frame delivered to output. Starting can include model download
or uncached CPU/Metal calibration. Stop releases capture and processing before
another session starts. Edit settings while stopped; changes do not apply live.
The menu does not automatically activate when another application opens a camera.

Background choices are original, blur, solid gray and image. Tracking combines
with background and brightness. Effect order: track/crop, fixed-size background
processing, brightness, final output sizing. Tracking uses standard framing
controls; advanced CLI tracking options remain available through `track-face`.
Brightness adds HSV value, 0..255. Advanced settings expose capture size/FPS,
processing FPS, backend choices, repeat delivery and optional mask smoothing.
Requested size/FPS must be supported together by the selected camera.

The menu defaults to explicit AVFoundation capture. Camera inventory uses the
selected backend's indices, including auto's OpenCV-compatible index mapping.
Unavailable cameras and OBS output are excluded. An index can identify a different
physical camera after input enumeration changes; refresh and verify selection.

Save named profiles to reuse settings. Saving an existing name replaces its
configuration. Deletion asks for confirmation in the menu. Profiles are local,
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

`profile-run` uses saved settings and disables interactive crop/replay. Common
startup flags are rejected rather than silently overriding the profile. Edit and
resave configuration to change it. Ctrl-C stops the run. Existing effect commands
continue accepting their common flags normally.

Profile fields and defaults:

| Field | Default | Meaning |
| --- | --- | --- |
| input_device | 0 | Selected backend's camera index |
| width, height | 640, 480 | Requested capture and output dimensions |
| fps | 30 | Capture request and output cap |
| effect | plain | plain, blur, color, image, track |
| track | false | Combine tracking with selected background |
| brightness | 0 | Added HSV value, 0..255 |
| blur_kernel | 31 | Positive odd box-blur kernel or Core Image radius mapping |
| color | 192 | Gray background, 0..255 |
| image_path | empty | Image required for image effect |
| capture | auto | auto, opencv, avfoundation; menu defaults avfoundation |
| segmentation | mediapipe | mediapipe or vision |
| processing | opencv | opencv or coreimage |
| repeat_frames | true | Repeat latest frame at output cadence |
| processing_fps | 30 | Fresh-frame cap in repeat mode |
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
Malformed requests produce an error and leave the helper available.

| Method | Parameters | Result |
| --- | --- | --- |
| hello | {} | protocol and package version |
| cameras.list | capture backend, optional | Array of index/name objects; macOS only |
| profiles.list | {} | Array of name/config objects |
| profiles.save | name, config | true |
| profiles.delete | name | true |
| start | config, or profile name | Current state |
| stop | {} | State after bounded shutdown |
| status | {} | Current state and optional error |
| shutdown | {} | Stop result, then helper exits |

EOF also stops the session. Simultaneous sessions are rejected. Configuration
validation occurs before acquiring resources. The controller refuses restart
following an unsafe shutdown timeout.

## Verification limits

Native compilation, structured transport/model self-tests and Python protocol
regressions do not establish Camera permission inheritance, physical camera
capture, conferencing reception or power behavior. Items 2 and 6 remain deferred.
The menu currently has no embedded video thumbnail; use CLI `--output preview`
when reviewing final video. Standalone distribution/notarization is future work.
