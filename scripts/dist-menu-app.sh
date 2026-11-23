#!/usr/bin/env bash
set -euo pipefail
# build the release menu app for the Homebrew cask: runs the Homebrew formula's Python,
# signed with the shared self-signed "Latent Byte" cert so camera grants survive upgrades
# usage: scripts/dist-menu-app.sh  -> dist/release/webcam-mods-app-<version>.zip
cd "$(dirname "$0")/.."

sign_identity="Latent Byte"
sign_cert="6b10ed2b5964b8c9afdd02b832dffce799548641"
bundle_id="com.latentbyte.webcammods"
brew_python="/opt/homebrew/opt/webcam-mods/libexec/bin/python"

version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
out="dist/release"
app="$out/WebcamMods.app"
zip="$out/webcam-mods-app-$version.zip"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "working tree has uncommitted changes; commit before a release build" >&2
    exit 1
fi

sign_kc="${LB_SIGN_KEYCHAIN:-$HOME/.ssh/lb-macos-signing.keychain-db}"
sign_pass="${LB_SIGN_PASS_FILE:-$HOME/.ssh/lb-macos-signing.pass}"
if [[ ! -f "$sign_kc" || ! -f "$sign_pass" ]]; then
    echo "signing keychain or password file missing: $sign_kc, $sign_pass" >&2
    exit 1
fi

rm -rf "$app" "$zip"
mkdir -p "$out"
# self-test a copy that runs the checkout venv; the release copy records the Homebrew
# path, which need not exist on the build Mac
uv sync --locked --python 3.14 --extra macos >/dev/null
selftest="$out/selftest/WebcamMods.app"
rm -rf "$out/selftest"
sh macos/build-menu-app.sh --python "$PWD/.venv/bin/python" --output "$selftest" >/dev/null
"$selftest/Contents/MacOS/WebcamMods" --self-test >/dev/null
rm -rf "$out/selftest"
sh macos/build-menu-app.sh --python "$PWD/.venv/bin/python" --record-python "$brew_python" --output "$app" >/dev/null

# the password goes through a file, never argv (security -p shows up in ps); relock on exit
trap 'security lock-keychain "$sign_kc" >/dev/null 2>&1 || true' EXIT
/usr/bin/python3 -I scripts/unlock-keychain.py "$sign_kc" "$sign_pass"
codesign --force --sign "$sign_identity" --keychain "$sign_kc" --identifier "$bundle_id" \
    --timestamp=none "$app"
req="$(codesign -d -r- "$app" 2>&1)"
if [[ "$req" != *"= H\"$sign_cert\""* ]]; then
    echo "app signed with an unexpected cert (want $sign_cert)" >&2
    exit 1
fi
codesign --verify --strict "$app"

ditto -c -k --keepParent "$app" "$zip"
shasum -a 256 "$zip"
