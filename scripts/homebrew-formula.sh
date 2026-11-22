#!/bin/sh
set -eu
# render the latentbyte/homebrew-tap formula for a tagged source release
# usage: scripts/homebrew-formula.sh VERSION [TARBALL_URL] > Formula/webcam-mods.rb
VERSION=${1:?usage: $0 VERSION [TARBALL_URL]}
URL=${2:-https://github.com/hamidzr/webcam-mods/archive/refs/tags/v$VERSION.tar.gz}
SHA256=$(curl -fsSL "$URL" | shasum -a 256 | cut -d' ' -f1)
cat <<RUBY
class WebcamMods < Formula
  desc "Face tracking, background blur and replacement for a virtual camera"
  homepage "https://latentbyte.com/products/webcam-mods"
  url "$URL"
  version "$VERSION"
  sha256 "$SHA256"
  license "GPL-2.0-only"

  depends_on "uv" => :build
  depends_on arch: :arm64
  depends_on :macos
  depends_on "python@3.14"

  def install
    ENV["UV_PYTHON_DOWNLOADS"] = "never"
    ENV["UV_NO_CONFIG"] = "1"
    venv_python = libexec/"bin/python"
    system "uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--extra", "macos",
           "--output-file", "requirements.txt"
    system "uv", "venv", "--python", formula_opt_bin("python@3.14")/"python3.14", libexec
    system "uv", "pip", "install", "--python", venv_python, "--require-hashes", "-r", "requirements.txt"
    system "uv", "pip", "install", "--python", venv_python, "--no-deps", "."
    bin.install_symlink libexec/"bin/webcam_mods"
  end

  def caveats
    <<~EOS
      Output goes to the OBS Virtual Camera. Install OBS 30+, start its
      Virtual Camera once to enable the camera extension, then quit OBS:
        brew install --cask obs

      Optional menu bar app (uses this install):
        brew install --cask latentbyte/tap/webcam-mods-app

      Try it without OBS:
        webcam_mods bg-blur --output preview
    EOS
  end

  test do
    assert_match "Usage", shell_output("#{bin}/webcam_mods --help")
    system libexec/"bin/python", "-c", "import webcam_mods.control, cv2, mediapipe, pyvirtualcam"
  end
end
RUBY
