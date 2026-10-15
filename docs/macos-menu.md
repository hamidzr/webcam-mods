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
The bundle icon is the committed `macos/AppIcon.icns`; after editing the
`assets/icon.svg` master, regenerate it with `just menu-icon` (needs
`rsvg-convert` from librsvg).

## Controls

Launch Webcam Mods to open its resizable main window. Choose a camera and
background effect, optionally enable face tracking, then adjust brightness and
press Start camera. Settings and saved profiles live beside the video preview in wide windows,
and below it in narrow windows.
The menu bar contains status, Start/Stop, Pause video, Profile, Open window and
Quit; Open window or reopening the app brings back the same window. Profile lists
saved profiles. Choosing one applies it at once, replacing unsaved edits in the
window; a running camera restarts by itself when the profile changes camera or
output shape.

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

The preview header switches views. **Output** is what calls receive. **Camera**
shows the full camera picture after rotation and flips but before framing and effects; with
tracking on, a yellow box marks the detected face and green dashes mark the auto
framing crop. **Mask** appears with blur, color, image or spotlight backgrounds and shows the
segmentation confidence aligned with the output: white is kept, black is replaced.
Guides are drawn by the app over the preview and never enter the video. In Output
view, press and hold Compare to see the same framing without background or image
effects, marked Original; release to return. VoiceOver toggles it instead.

Source switches between Camera and Screen. Screen shares a whole display, picked
from the connected displays by name and size, at the capture FPS; zoom and drag the
crop box in the preview's Screen view to share part of it. The area is saved as
global screen points, so a profile keeps its display; Start is blocked with a
message when that area is on no connected display. The first screen start asks for
Screen Recording permission (System Settings > Privacy & Security > Screen & System
Audio Recording); the worker inherits it from the app. Output defaults to the
display size; Shape picks a smaller preset. Changing source or display restarts the
session. With Screen, labels that say Camera read Screen. Screens skip background
effects, face tracking and orientation; brightness, color, look and overlays apply.

Show camera puts a camera over the shared screen, with its own camera picker. Bubble
shows the middle of the camera picture in a circle; Cutout shows only the person,
standing on the bottom edge, using the profile's segmentation (Green screen keys a
backdrop instead). Corner and Size (camera height, 10..80 percent of the picture)
apply live; turning it on or off restarts. Mirror, flip, rotation, denoise, low
light, eye contact, touch up, brightness, color and look apply to the camera
picture, never to the screen; gesture reactions read the camera and play over the
whole picture. The camera opens and closes with the session, so Pause turns it off.

Zoom (1x..4x) crops the camera to what calls see. The crop keeps the output aspect,
so output fills without bars. In Camera view the crop is a white box with the rest
dimmed: drag to move it or pinch to zoom. Center recenters it; Show whole camera
removes it. Crop is saved per profile as frame fractions and applies live. With face
tracking on, tracking frames you inside the crop; detection still sees the whole
frame, so moving the crop never reloads the face model. Interactive CLI crop in
`~/.webcam-mods.conf` is separate.
Desk view (camera source) straightens a desk, whiteboard or page seen at an angle.
Turning it on shows Camera view with four corner handles; drag each onto the
matching corner of the area. A corner never moves where the area would fold or
cover less than 1% of the frame. The area is warped to an upright rectangle with
the shape of its mean edge lengths, then fit to the output with bars, for about
0.3 ms per 720p frame. It applies live and is saved per profile as corner
fractions of the oriented camera frame. While it is on, crop and face tracking
pause and Camera view shows no crop box; Mirror video still flips the picture
first, so turn it off for readable writing. Only the
selected view is encoded. Below the preview, stats refresh about once a second:
processed frames per second, sent frames per second and mean effect time.

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
another session starts. Effect settings apply live while the camera runs: background,
blur, color, tracking, brightness, color adjustments, mirror, vertical flip, crop,
framing, segmentation, processing and smoothing.
Background mode changes keep the loaded segmentation model; segmentation, processing
or smoothing changes reload it, and tracking loads or releases face detection.
Camera, capture size/FPS, capture backend, rotation, output destination, output
size/FPS, processing FPS, repeat mode and loading picture shape the session. Editing them
while running shows Restart camera, which stops, refreshes camera inventory and
starts with the edited settings.
The menu does not automatically activate when another application opens a camera.

Pause video, in the window, the menu bar or Control-Option-P from any app, keeps
the session and output open but closes the camera, so its light turns off, and
sends the loading picture at output FPS. Resume video reopens the camera; Stop
ends the pause. The menu bar icon shows a crossed-out camera while paused. The
shortcut is registered when the app launches; if macOS refuses it, use the menu bar.

Below a running preview, Snapshot saves the frame calls last received as a PNG in
Pictures > Webcam Mods, named for the time and never replacing a file; Show in
Finder reveals it. Record loop keeps what calls see in memory as JPEG frames, up to
256 MiB (about a minute at 720p), and stops on its own when full. Play loop sends
the recording on repeat instead of the camera, for stepping away, and skips the
effect pipeline meanwhile; Back to live returns. The preview marks Recording and
Playing loop. Recordings last until the camera stops or restarts. Narrow windows
show these buttons as icons.

Background choices are original, blur, solid color, image or video and spotlight.
Choose your own accepts pictures and videos; a video loops at its own frame rate,
without sound, decoded on the processing thread. Solid
color takes any color from the color picker; the eyedropper button samples any
pixel on screen, such as your wall in the camera preview. Image backgrounds fill
the picture without stretching; Horizontal and Vertical choose which part of the
image shows when its shape differs from the video. Both apply live. With a
background effect on, Green screen keys out a solid backdrop instead of detecting
you: pick its Screen color (the eyedropper can sample the backdrop in the camera
preview), widen the keyed range with Tolerance and its soft edge with Softness,
and remove backdrop color reflected onto hair and edges with Spill. Key settings
apply live without rebuilding segmentation; Green screen is also the Segmentation
choice under advanced settings. Spotlight
keeps the room but darkens it by Dim room percent and brightens you with a gentle
curve set by Lift you, where black and white stay put; both apply live without
reloading segmentation. Tracking combines
with background and brightness. Effect order: rotation, mirror and vertical flip,
denoise, desk view or manual crop with tracking inside the crop, auto light, eye
contact, touch up, fixed-size background processing, brightness, color, look,
overlays, gesture reactions, final output sizing. Mirror video flips the
camera left to right for both preview and OBS output, so receivers see the
mirrored view; background images stay readable. Background effects keep the
picture orientation, so only Mirror video flips it. Flip upside down turns the picture
over for a camera mounted upside down; Rotate turns it 90, 180 or 270 degrees
clockwise. Mirror and flip apply to the rotated picture as you see it. A quarter turn
swaps the default output size, so a sideways camera sends a portrait picture.
Shape sets the output to the camera shape, Wide 16:9, Standard 4:3, Square 1:1 or
Portrait 9:16 at the largest size that fits the rotated camera without upscaling;
typed sizes under Advanced show as Custom. Without tracking, a shape that differs
from the camera adds a centered crop so output fills without bars; Show whole camera
removes it and pads instead. With tracking, framing follows the new shape. Rotation
and shape restart the session. With tracking on, framing
controls tune face size, head height, maximum zoom, follow time and steadiness live
without reloading the face model; Default framing restores them. Follow time sets the
pan response; zoom responds 2.4 times slower, matching the CLI defaults. Steadiness
is the drift ignored before framing moves, for both pan and zoom. Legacy padding,
horizontal target and loss timeout remain CLI-only through `track-face`.
Color sets exposure, contrast, saturation, warmth, tint and sharpness for the whole
picture, background included, after brightness; all apply live and Reset color
restores neutral. Pick white switches to Camera view; click something white or gray
and the worker samples a small patch of the raw camera frame, then sets warmth and
tint so it turns neutral. Cancel or stopping the camera ends picking. Low light
(0..100, 0 off) brightens dark framed pictures toward a mid-tone target over about a
second, rolling off highlights; it never darkens. It runs before segmentation, so
masks see the brighter picture while background images stay as chosen. Eye
contact (0..100, 0 off, experimental) finds the face mesh in the framed camera
picture after low light and slides each iris up inside its eye opening, so eyes
reading the screen seem to meet a camera above it; at 100 an iris moves up to 0.6
of its radius, less where the opening is narrow. Lids, brows and skin keep their
pixels, closed eyes and frames without a face pass unchanged, and the iris top
slides under the upper lid while the sclera below stretches. It costs about 4 ms
per 720p frame, downloads the MediaPipe face landmarker (3.8 MB) on first use and
applies live. Touch up (0..100, 0 off) smooths skin tones with an edge-preserving
filter after eye contact; strong edges such as eyes, brows and lips keep their
detail, and non-skin colors stay untouched. It costs about 7 ms per 720p frame and applies live. Denoise
(0..100, 0 off) averages each pixel over recent frames where the picture holds
still, right after orientation and before framing, so zooming or tracking never
restarts it; moving areas and scene changes pass through without ghosts. It costs
about 4 ms per 720p frame (9 ms at 1080p) and applies live; turning it off drops
the history. Camera view and white balance use the raw picture; Compare keeps
noise reduction on. Gesture reactions watch the lit camera picture about ten
times a second with the MediaPipe gesture recognizer (8.4 MB, downloaded on first
use; about 5 ms per look at 720p). Holding a thumbs up, thumbs down, peace sign
or I-love-you sign for 0.4 s sets off a thumbs-up or thumbs-down bubble at the
upper right, rising balloons or rising hearts; two thumbs up throw confetti. One
reaction plays at a time for 2 to 3.2 s, and a gesture fires again only after the
hand drops or changes. Reactions are drawn last, over overlays, so calls and
recordings see them and Mirror never flips them. Emoji come from the system color
emoji font (Apple Color Emoji, or Noto Color Emoji on Linux); without one, only
confetti shows and the app warns once. Two hands showing different reaction
gestures set off nothing.
Camera hardware sets exposure time, focus and anti-flicker on the camera itself
through CoreMediaIO, for cameras whose driver publishes those controls (most USB
webcams, such as the Logitech C920; built-in Mac cameras publish none, and the
section says so). Manual exposure and Manual focus fix the setting at a slider
position, 0..100 across the camera's range; exposure steps through it in even
stops. Anti-flicker filters 50 Hz or 60 Hz mains lighting, or turns filtering
off; Camera setting leaves it alone. Settings apply once the first frame arrives
and change live; turning one off, or ending the session, puts that control back
how the session found it, so a crash can leave a manual setting on the camera
until it is unplugged or another app changes it. The app asks the worker which
controls a camera has when the section first shows for it. Elsewhere than macOS,
or without a chosen camera, a set control warns instead; a shared screen without
the camera leaves camera hardware alone.
Look is a final color grade: None, Warm, Cool, Mono, Fade, Vivid, Film, or Custom LUT,
which opens a `.cube` 3D lookup table (sizes 2..65, up to 16 MiB; domain headers
honored, 1D tables rejected). Strength blends it with the picture, 0..100. Looks
apply live; an unreadable or invalid file is refused and the current look stays.
Overlays draw a name caption and a logo into the video calls see, after the look,
so color settings never tint them and Mirror video never reverses them. Name and
Title (one line each, up to 80 characters) form a lower-third panel of white text on
translucent black in a chosen corner; Title alone draws nothing. Choose picks a
logo picture, keeping PNG transparency; Size sets its width as 5..60 percent of
the picture and Opacity blends it. A caption sharing the logo's corner stacks
toward the middle, clear of it. Text scales with the output height and shrinks,
then trims with an ellipsis, to fit the width. All overlay settings apply live; an
unreadable logo is refused and the current overlay stays.
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
virtual-camera output receive the same picture-only loading frames while
capture, model initialization and calibration run; status stays in the window. Live frames replace them
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
| source | camera | camera or screen; restarts |
| screen_region | null | [left, top, width, height] in global screen points, required for screen; width and height 16..8192 replace the capture size |
| presenter | false | Screen sources only: open the camera too and place it over the screen; restarts |
| presenter_style | bubble | bubble or cutout |
| presenter_position | bottom-right | Corner, as caption_position |
| presenter_size | 30 | Camera height as 10..80 percent of the picture |
| output_width, output_height | null | Independent delivery dimensions; inherit rotated capture when null |
| output_fps | null | Independent delivery cap; inherit capture when null |
| effect | plain | plain, blur, color, image, spotlight, track |
| track | false | Combine tracking with selected background |
| brightness | 0 | Added HSV value, 0..255 |
| blur_kernel | 31 | Positive odd box-blur kernel or Core Image radius mapping |
| color | 192 | Gray background, 0..255, used when background_color is absent |
| background_color | absent | Solid background as #RRGGBB; stored uppercase |
| image_path | empty | Image or video required for image effect; videos loop |
| image_blur | false | Cache image background blur using blur_kernel |
| image_x, image_y | 0.5 | Image point kept in view while the image fills the picture, fractions from left and top |
| spotlight_dim | 60 | Spotlight background darkening percent, 0..100 |
| spotlight_lift | 20 | Spotlight person brightening, 0..100; black and white stay put |
| capture | auto | auto, opencv, avfoundation; menu defaults avfoundation |
| segmentation | mediapipe | mediapipe, vision or chroma (green screen keying) |
| key_color | #00B140 | Green screen backdrop as #RRGGBB; stored uppercase |
| key_tolerance, key_softness | 40, 30 | 0..100: keyed color range and soft edge width |
| key_spill | 50 | 0..100: backdrop color removed from edges near the backdrop |
| processing | opencv | opencv or coreimage |
| repeat_frames | true | Repeat latest frame at output cadence |
| processing_fps | 30 | Fresh-frame cap in repeat mode |
| signal_pattern | color-bars | Loading/paused picture: color-bars or noise |
| mirror | false | Flip camera left to right before effects |
| flip_vertical | false | Flip camera top to bottom before effects; applies live |
| rotate | 0 | Clockwise camera rotation: 0, 90, 180 or 270; restarts, and quarter turns swap default output size |
| track_face_height | 0.4 | Target face height as an output fraction, 0.1..0.9 (`--face-height`) |
| track_target_y | 0.42 | Face center from the top as an output fraction, 0.2..0.8 (`--target-y`) |
| track_max_zoom | 2.0 | Maximum zoom over the widest view, 1..4 (`--max-zoom`) |
| track_follow_seconds | 0.25 | Pan time constant, 0.05..3; zoom uses 2.4 times this |
| track_deadzone | 0.08 | Ignored pan and zoom drift as a crop fraction, 0..0.4 |
| crop | null | Manual crop `[x, y, width, height]` as fractions of the oriented camera frame; each size at least 0.02 and inside the frame |
| perspective | null | Desk view corners `[[x, y], ...]` clockwise from top-left as fractions of the oriented camera frame; a convex area over 1% of the frame, straightened to fill the picture. Replaces crop and tracking; camera source only |
| exposure | 0 | Exposure in stops, -2..2; +1 doubles the light |
| contrast, saturation | 0 | -100..100 around the unchanged picture; saturation -100 is grayscale |
| temperature, tint | 0 | White balance, -100..100: positive warmer, positive tint magenta |
| sharpness | 0 | Unsharp mask amount, 0..100 |
| auto_light | 0 | Low-light lift strength, 0..100; 0 off, never darkens |
| eye_contact | 0 | Experimental iris lift toward a camera above the screen, 0..100; 0 off. Camera picture only |
| touchup | 0 | Skin smoothing strength, 0..100; 0 off |
| reactions | false | Held hand gestures set off animations drawn over the finished picture. Camera picture only |
| denoise | 0 | Temporal noise reduction strength, 0..100; 0 off |
| camera_exposure, camera_focus | null | Exposure time and focus set on the camera, 0..100 across its range (exposure in even stops); null keeps the camera's own, usually automatic, setting. macOS with camera_id |
| anti_flicker | null | Mains flicker filter set on the camera: off, 50hz or 60hz; null keeps the camera's setting |
| look | none | none, warm, cool, mono, fade, vivid, film or custom |
| look_path | empty | `.cube` file required for the custom look; saved as an absolute path |
| look_strength | 100 | Look blend, 0..100 |
| caption, caption_detail | empty | Caption name and second line, at most 80 characters, no control characters |
| caption_position | bottom-left | top-left, top-right, bottom-left or bottom-right |
| logo_path | empty | Logo or watermark picture; saved as an absolute path |
| logo_position | top-right | Logo corner, as caption_position |
| logo_scale, logo_opacity | 15, 100 | Logo width as 5..60 percent of the picture; opacity 0..100 |
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
| cameras.controls | {id} from cameras.list | Read-only {exposure, focus: {auto, value 0..100}, anti_flicker: off, 50hz, 60hz, auto or other}, each present only when the camera can set it; macOS only |
| profiles.list | {} | Array of valid name/config objects |
| profiles.seed_defaults | {} | Save starter pack once without replacing existing names; true |
| profiles.errors | {} | Array of name/error objects for damaged profiles |
| profiles.save | name, config | true |
| profiles.delete | name | true |
| start | config, or profile name; optional output: virtualcam (default) or preview | Current state |
| preview.get | optional view: output (default), source, mask or original | Latest {jpeg: base64, width, height, view, optional guides}, or null |
| session.update | config | Current state; applies live fields to the running session |
| session.stats | {} | {processed_fps, sent_fps, effect_ms}, each null until measured, plus recorder and recorded_seconds as in session.record; null when idle |
| session.snapshot | {} | {path} of a new PNG of the frame last sent, in ~/Pictures/Webcam Mods. Fails before the first frame or while paused |
| session.record | {action: record, stop or replay} | {recorder: idle, recording or replaying, recorded_seconds}. Record starts over; replay fails without a recording |
| session.pause | {paused: true or false} | Current state; a paused session closes capture and sends the loading picture at output FPS. Requires a running session |
| session.white_balance | {x, y} fractions of the camera view, 0..1 | {temperature, tint} that make a small patch of the latest camera frame neutral; the app applies them as a live update |
| stop | {} | State after bounded shutdown |
| status | {} | Current state, optional error, negotiated output_fps once output opens and paused: true while paused |
| shutdown | {} | Stop result, then helper exits |

`session.update` takes a complete configuration. It fails without a starting or
running session, and when capture/output fields differ from the running session
(`RESTART_FIELDS` in `profiles.py`). Unreadable background images fail the request.
Accepted updates apply on the processing thread before the next frame; the latest
update wins. If applying fails there, the session keeps running with its previous
components and emits `{"event":"warning","data":{"message":...}}`.

`preview.get` encodes only the requested view; requesting a different view drops the
held frame. Source frames carry `guides`, a map of name to normalized
`[x, y, width, height]` boxes in source-frame fractions: `crop` for the applied manual
crop, `face` and `framing` while tracking. Mask frames exist only while a background
effect runs. Original frames use the output framing before background and image
effects, unpadded at the framed size. Stats cover the
last two seconds: `processed_fps` counts frames through the effect pipeline,
`sent_fps` counts frames delivered to output, `effect_ms` is mean pipeline time.

EOF also stops the session. Simultaneous sessions are rejected. Configuration
validation occurs before acquiring resources. The controller refuses restart
following an unsafe shutdown timeout. Status then includes `restart_required:
true`; late cleanup cannot clear the terminal error. Quit/reopen the app or
replace the helper process before another session.

## Verification limits

`just menu-check` compiles and runs native transport/model tests, including JPEG
decoding, single in-flight preview requests, stale-response rejection, stop/hide
cleanup, preview views and guides, stats cadence, OBS readiness, negotiated preview
cadence and timeouts. `just menu-snapshot` renders the main window in sample states
to `dist/snapshots/*.png` (desktop and narrow widths) using an off-display window that
never activates the app, starts the worker or opens a camera. Python regressions
verify final-frame routing in direct and repeat modes, preview-only output without
OBS, bounded encoding and session
cleanup. These checks do not establish physical-camera permission behavior,
conferencing reception, realistic quality or power behavior.

Settings scroll; Start/Stop and Quit remain outside the scrolling area. A
disconnected helper exposes Reconnect after its old process exits. The footer
shows app build identity and connected backend version. Launching normally opens
the main window; the older `--show-controls` launch argument remains harmless.
Standalone distribution/notarization is future work.
