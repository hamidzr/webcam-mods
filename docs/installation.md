# Install and develop with uv

Requires [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/).
uv provisions Python 3.14 when needed. Linux's v4l2 dependency also requires Git.
Run these commands from the repository checkout.

## Install the CLI

```sh
just install
webcam_mods --help
```

Like Mao, `just install` builds a wheel in a temporary directory and installs it
with `uv tool install --force --reinstall`. The `webcam_mods` command works outside
the checkout. Editing source does not change the installed snapshot; rerun
`just install` to update it. Temporary build files are removed automatically.
Tool dependencies resolve from package metadata; development commands use `uv.lock`.

If `webcam_mods` is missing from PATH, run `uv tool update-shell` and restart your
shell. `uv tool uninstall webcam-mods` removes the installed CLI.

Platform extras are automatic: `macos` on macOS, `linux` on Linux. Override with
`just extra="" install` for base dependencies only. On macOS ARM64, installation
explicitly includes the bundled patched MediaPipe wheel because wheel metadata
does not include uv's project source overrides. This also applies to base installs.

Camera output still needs OBS Virtual Camera on macOS/Windows or v4l2loopback on
Linux. See [virtual camera setup](../README.md#installation). Preview output needs
no virtual camera. Camera and screen capture require OS permissions as usual.
Models download on first use into `~/.cache/webcam-mods/models` (or `$XDG_CACHE_HOME`).

## Develop from the checkout

```sh
just deps
just models
just run --help
just run --no-controls --output preview bg-blur
just check
just test
just e2e
just build
```

`just run` uses current source in the uv project environment. `just deps` installs
locked dependencies, development tools, and platform extras. `get-deps` aliases
`deps`. `just fmt` applies Black; `format` and `fix` alias it. `just check` runs
Flake8, Black's format check, and mypy; `lint` aliases it. `just verify` runs checks
and the full test suite. E2E outputs go to `dist/e2e`; builds go to `dist`.

`UV_FLAGS` passes additional options to project sync/run commands, for example
`UV_FLAGS=--no-sync just check` after syncing. It does not affect build or tool
installation. Use `just extra="" deps` and `just extra="" run --help` to work
without platform extras. Existing Makefile targets remain available.
