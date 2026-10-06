#!/bin/sh
set -eu
# build local native shell around an installed webcam-mods Python runtime
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=""
OUTPUT="$ROOT/dist/Webcam Mods.app"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --python) PYTHON=$2; shift 2 ;;
        --output) OUTPUT=$2; shift 2 ;;
        *) echo "Usage: $0 [--python /path/to/python] [--output /path/to/Webcam Mods.app]" >&2; exit 2 ;;
    esac
done
if [ "$(uname -s)" != Darwin ]; then echo "Menu app requires macOS." >&2; exit 1; fi
if [ -z "$PYTHON" ]; then PYTHON="$(uv tool dir)/webcam-mods/bin/python"; fi
if [ ! -x "$PYTHON" ]; then echo "Python runtime missing. Run just install or pass --python." >&2; exit 1; fi
"$PYTHON" -c 'import webcam_mods.control' >/dev/null
VERSION=$("$PYTHON" -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/pyproject.toml")
COMMIT=$(git -C "$ROOT" describe --always --dirty)
BUILD_DATE=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
mkdir -p "$OUTPUT/Contents/MacOS" "$OUTPUT/Contents/Resources"
swiftc -parse-as-library -swift-version 5 -O -target "$(uname -m)-apple-macosx13.0" \
    "$ROOT/macos/MenuBar/WebcamMods.swift" -o "$OUTPUT/Contents/MacOS/WebcamMods"
printf '%s\n' "$PYTHON" > "$OUTPUT/Contents/Resources/backend-python.txt"
cat > "$OUTPUT/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.latentbyte.webcammods</string>
<key>CFBundleName</key><string>Webcam Mods</string>
<key>CFBundleDisplayName</key><string>Webcam Mods</string>
<key>CFBundleExecutable</key><string>WebcamMods</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundleVersion</key><string>$VERSION</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>LSUIElement</key><true/>
<key>NSCameraUsageDescription</key><string>Webcam Mods uses your selected camera only when you start a camera session.</string>
<key>BuildCommit</key><string>$COMMIT</string>
<key>BuildDate</key><string>$BUILD_DATE</string>
</dict></plist>
PLIST
codesign --force --sign - "$OUTPUT"
echo "$OUTPUT"
