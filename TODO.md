# TODO

Active improvement roadmap: [docs/improvement-plan.md](docs/improvement-plan.md).

## Deferred visual polish

- Stabilize jittering background-blur boundary in Vision fast preview. Evaluate
  segmentation quality, spatial edge feathering and motion-aware temporal smoothing.
  Preserve fine detail, avoid motion trails, and measure the cost at 640x480/30.
  Deferred by user on 2026-10-02.

## Historical feature ideas

- stich webcams together to have a bigger source cam
- zoom support
- CLI args for orientation
- add eye tracking
- figure our v4l2 compatibility for python 3
- animation support
  - glasses?
- reduce remaining legacy helper globals
- cli interface to stack different mods eg bg-swap and track face or blur

## Done

- bounded in-memory record and replay
- capture/output resolution and FPS CLI options

- interactive control
- separate thread for prediction (historical; supported effects now run synchronously)
