set shell := ["bash", "-cu"]
set positional-arguments

extra := if os() == "macos" { "macos" } else if os() == "linux" { "linux" } else { "" }
extra_flags := if extra == "" { "" } else { "--extra " + extra }
uv_flags := env_var_or_default("UV_FLAGS", "")
uv_run := "uv run --locked --python 3.14 " + extra_flags + " " + uv_flags

# list available commands; setup instructions: docs/installation.md
default:
    @just --list

# install locked development dependencies and platform extras
deps:
    uv sync --locked --python 3.14 {{ extra_flags }} {{ uv_flags }}

alias get-deps := deps

# run the live checkout without changing the installed PATH snapshot
run *args:
    {{ uv_run }} webcam_mods "$@"

# download and verify models ahead of first use
models:
    {{ uv_run }} python -m webcam_mods.models

# build wheel and source distributions through uv
build:
    uv build --python 3.14

# install a wheel snapshot, matching Mao's user-level tool installation
install:
    #!/usr/bin/env bash
    set -euo pipefail
    stage=$(mktemp -d)
    trap 'rm -rf "$stage"' EXIT
    uv build --python 3.14 --wheel --out-dir "$stage"
    wheels=("$stage"/webcam_mods-*.whl)
    package="${wheels[0]}"
    if [[ -n '{{ extra }}' ]]; then
        package+="[{{ extra }}]"
    fi
    install_args=(--python 3.14 --force --reinstall)
    # wheel metadata does not carry uv's project-only source override
    if [[ $(uname -s) == Darwin && $(uname -m) == arm64 ]]; then
        install_args+=(--with "$PWD/vendor/mediapipe/mediapipe-1.0.1+git32d0e5b.metal-py3-none-macosx_11_0_arm64.whl")
    fi
    uv tool install "${install_args[@]}" "$package"
    echo 'Installed webcam_mods snapshot. Live checkout: just run --help'

fmt:
    {{ uv_run }} black src tests scripts

alias format := fmt
alias fix := fmt

# non-mutating static analysis, matching the existing Makefile checks
check:
    {{ uv_run }} flake8 --select=E9,F63,F7,F821 src tests scripts
    {{ uv_run }} black --check src tests scripts
    {{ uv_run }} mypy

alias lint := check

test:
    {{ uv_run }} python -m unittest discover -s tests

# save repeatable headless pipeline outputs under dist/e2e
e2e:
    {{ uv_run }} python tests/test_pipeline.py --artifacts dist/e2e

verify: check test
