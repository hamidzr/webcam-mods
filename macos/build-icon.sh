#!/bin/sh
set -eu
# regenerate macos/AppIcon.icns from the assets/icon.svg master (needs rsvg-convert, iconutil)
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/assets/icon.svg"
OUT="$ROOT/macos/AppIcon.icns"
for tool in rsvg-convert iconutil; do
    command -v "$tool" >/dev/null || { echo "$tool not found; rsvg-convert comes from librsvg" >&2; exit 1; }
done
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SET="$WORK/AppIcon.iconset"
mkdir "$SET"
for size in 16 32 128 256 512; do
    rsvg-convert -w "$size" -h "$size" "$SRC" -o "$SET/icon_${size}x${size}.png"
    rsvg-convert -w $((size * 2)) -h $((size * 2)) "$SRC" -o "$SET/icon_${size}x${size}@2x.png"
done
iconutil --convert icns --output "$OUT" "$SET"
echo "$OUT"
