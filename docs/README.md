# Developer documentation

Webcam Mods captures frames, applies effects, and sends video to a virtual camera
or preview window. Python processing is shared across macOS and Linux; device
delivery and desktop permissions vary by platform.

- [Current architecture](architecture.md): modules, frame flow, lifecycle, state,
  and existing control paths.
- [Current state](current-state.md): capabilities, configuration, portability,
  verification coverage, and known gaps.
- [Improvement plan](improvement-plan.md): prioritized findings and a proposed
  shared control path for CLI and future API access.

These documents describe source reviewed on 2026-10-02. Proposals are explicitly
labeled and are not implemented features. See the [project README](../README.md)
for installation and user commands. Update these documents when changing the
runtime, configuration, controls, or supported adapters.
