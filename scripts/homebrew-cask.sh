#!/bin/sh
set -eu
# render the latentbyte/homebrew-tap cask for the menu app built by scripts/dist-menu-app.sh
# usage: scripts/homebrew-cask.sh VERSION ZIP_PATH [ZIP_URL] > Casks/webcam-mods-app.rb
VERSION=${1:?usage: $0 VERSION ZIP_PATH [ZIP_URL]}
ZIP=${2:?usage: $0 VERSION ZIP_PATH [ZIP_URL]}
URL=${3:-https://github.com/latentbyte/homebrew-tap/releases/download/webcam-mods-v$VERSION/webcam-mods-app-$VERSION.zip}
SHA256=$(shasum -a 256 "$ZIP" | cut -d' ' -f1)
cat <<RUBY
cask "webcam-mods-app" do
  version "$VERSION"
  sha256 "$SHA256"

  url "$URL"
  name "Webcam Mods"
  desc "Menu bar app for Webcam Mods virtual camera effects"
  homepage "https://latentbyte.com/products/webcam-mods"

  depends_on arch: :arm64
  depends_on macos: ">= :ventura"
  depends_on formula: "latentbyte/tap/webcam-mods"

  app "WebcamMods.app"

  zap trash: [
    "~/.config/webcam_mods",
    "~/.webcam-mods.conf",
  ]
end
RUBY
