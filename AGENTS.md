# Agent notes

Python 3.14-only virtual-camera processor (face tracking, background blur/swap,
crop, brightness, replay) plus an optional single-file SwiftUI macOS menu app.
Read `docs/README.md` first; `docs/architecture.md` has the module map and
ownership/lifecycle rules.

## Commands

Use `just` (uv-backed, `--locked --python 3.14`, auto-adds `macos`/`linux` extra).

- `just deps` sync env. `just run <args>` runs the checkout (`just run --help`).
- `just check` flake8 (errors only) + black --check + strict mypy. ~5s.
- `just test` unittest discover over `tests/` (~420 tests, ~30s, headless).
- `just fmt` black. `just e2e` real models on fixture image, writes `dist/e2e`.
- `just install` reinstalls the wheel snapshot as the user `uv tool`; PATH
  `webcam_mods` and the menu app run that snapshot, not the checkout.
- `just menu-check` (macOS) builds `dist/Webcam Mods.app` against the installed
  tool runtime, runs Swift `--self-test`, plist lint, codesign verify. Needs a
  prior `just install`.
- CI (`.github/workflows/verify.yml`, ubuntu + macOS) runs `make verify`, whose
  `check` also runs `compileall`; keep Makefile and justfile check/test in sync.

## Gotchas

- mypy checks only files listed in `mypy.ini` (strict). Add new typed modules
  there; `tests/type_contracts.py` holds typing contract checks.
- Tests must not touch real cameras, displays, OBS or terminals. CLI tests
  subclass `tests/cli_fixtures.py::HeadlessCliTestCase` to fake camera
  inventory, non-interactive TTY and OpenCV backend.
- Frames are uint8 BGR end to end. PyObjC (`macos` extra) and Linux deps
  (`linux` extra) are lazy imports; base install must still import and run.
- macOS ARM64 uses the vendored patched Metal MediaPipe wheel in
  `vendor/mediapipe/` via `[tool.uv.sources]` and `just install --with`;
  rebuild only per `vendor/mediapipe/README.md` and update `SHA256SUMS`.
- Startup settings: CLI > env > defaults, resolved once in `settings.py`.
  New env vars go in `env.example`. Runtime crop/padding persists in
  `~/.webcam-mods.conf`; profiles in `$XDG_CONFIG_HOME/webcam_mods/profiles.sqlite3`
  (schema v1, no migration chain; adding one requires append-only checks).
- Menu app talks to `python -m webcam_mods.control` over stdin/stdout JSONL
  (protocol in `docs/macos-menu.md`). Keep Swift and Python sides in step and
  logs on stderr only. No network listeners.
- Common CLI options are shared via `cli.py`; they work before or after the
  command, command-side wins. Check both placements when adding options.
- Docs describe current behavior precisely; update the relevant `docs/*.md`,
  README and `TODO.md` when runtime behavior changes (history pairs feat/fix
  commits with docs commits).
- `Makefile` `track-face`/`crop-cam` targets are deprecated stubs; `output/file.py`
  is intentionally empty.
