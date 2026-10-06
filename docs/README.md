# Documentation

Webcam Mods captures uint8 BGR frames, applies effects, and sends the final video
to OBS Virtual Camera, Linux V4L2, or a preview window.

- [Installation](installation.md): installed CLI, development commands, native app.
- [Architecture](architecture.md): processing, ownership, controls and adapters.
- [Current state](current-state.md): supported behavior and verification limits.
- [Improvement plan](improvement-plan.md): current priorities and deferred work.
- [macOS menu](macos-menu.md): native controls, profiles and local protocol.
- [Quality settings](quality-settings.md): independent input/output resolution and FPS.
- [Frame delivery](frame-delivery.md): repeat mode, pacing and shutdown limits.
- [macOS backends](macos-backends.md): adapter choices and dated benchmark evidence.
- [Segmentation comparison](segmentation-comparison.md): fixture quality evidence.
- [macOS on-demand](macos-on-demand.md): receiver-detection limitations.

Current behavior reviewed 2026-10-05. Benchmark reports retain their original
measurement context; they do not establish current conferencing reception or
power consumption. Update relevant documents when changing runtime behavior.
