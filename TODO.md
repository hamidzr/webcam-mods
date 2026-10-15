# Backlog

Priorities and verification requirements: [improvement plan](docs/improvement-plan.md).
Current supported behavior: [current state](docs/current-state.md).

## Deferred acceptance

- Conferencing reception and 720p effects/output (review item 2).
- Moving-person quality, hair/hands/low light, latency and power (review item 6).
- Battery/AC/Low Power Mode presets after power measurements.
- Real Linux V4L2 consumer/output acceptance.

## Desktop app roadmap

Ordered build plan, 2026-10-15. Each item ships with profile fields, app controls,
headless tests and docs. Effort: S small, M medium, L large.

Shared design:

- New tunable settings are profile fields, so the CLI `profile-run` and the app
  produce the same output.
- Settings that change capture or output shape (camera, capture size/FPS, output
  size/FPS, repeat mode, rotation) restart; everything else applies live.
- Profile effects run on the processing thread in this order: orientation, denoise,
  crop or desk view, tracking and background, output sizing, color, overlays.
- Preview guides are drawn by the app, never into the output video.
- Manual crop is stored per profile as fractions of the frame; with tracking on,
  tracking stays inside the crop. CLI interactive crop keeps `~/.webcam-mods.conf`;
  padding stays CLI-only.

Phase 0, foundation:

1. Live settings updates while running (M). Done.
2. Preview views: output, raw camera, mask; app-drawn guides (M). Done.
3. Stats: input/output FPS, processing time (S). Done.

Phase 1, framing:

4. Manual crop, zoom, pan and recenter in the preview (M). Done.
5. Auto-framing tuning: face size, max zoom, eye line, follow speed, steadiness (S). Done.
6. Vertical flip, rotate 90/180/270 and output shape presets such as 9:16 (M). Done.

Phase 2, image look:

7. Hold-to-compare raw and processed preview (S). Done.
8. Color: exposure, contrast, saturation, temperature, tint, sharpness,
   click-to-white-balance (S). Done.
9. Auto low-light and exposure (S-M). Done.
10. Spotlight: dim background, lift person (S). Done.
11. Looks: built-in color filters and `.cube` LUT import with strength (M). Done.

Phase 3, call controls:

12. Pause video from the menu bar and a global hotkey (S). Done.
13. Switch profiles from the menu bar (S). Done.

Phase 4, backgrounds:

14. Any background color, eyedropper, background image position (S). Done.
15. Green screen keying as a segmentation choice (M). Done.
16. Looping video backgrounds (M). Done.

Phase 5, composition:

17. Overlays: logo or watermark, name caption (M). Done.
18. Screen capture input in the app (M). Done.
19. Presenter overlay: camera cutout over a shared screen (M-L). Done.
20. Snapshot and record/replay buttons (S). Done.

Phase 6, enhancement:

21. Skin touch-up (M). Done.
22. Temporal noise reduction (M).

Phase 7, large or research:

23. Hardware camera controls: exposure, focus, anti-flicker (support varies by camera).
24. Desk or whiteboard view: perspective correction of a chosen area.
25. Eye-contact correction.
26. Gesture reactions.
27. Makeup filters.

## Other ideas

- Window-following screen capture.
- Eye tracking, webcam stitching and animation, pending concrete demand.
- Native-frame processing, pending measured end-to-end benefit.

## Existing features

Zoom, brightness, horizontal mirror, bounded recording/replay, CLI capture/output settings,
screen input, stable face framing and optional segmentation smoothing are implemented.
The native menu, local session control and saved profiles are documented separately
in [macOS menu](docs/macos-menu.md). Avoid duplicating completed work as open tasks.
