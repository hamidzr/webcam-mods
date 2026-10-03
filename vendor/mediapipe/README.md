# Patched MediaPipe for macOS ARM64

CPU-only source snapshot `1.0.1+git32d0e5b`, built from upstream commit
[`32d0e5b1317be070083c630240b274218ce9ed52`](https://github.com/google-ai-edge/mediapipe/commit/32d0e5b1317be070083c630240b274218ce9ed52).
This snapshot contains the fix for
[MediaPipe #6356](https://github.com/google-ai-edge/mediapipe/issues/6356), which
aborts face detector initialization on macOS even with the CPU delegate.
It is a local source build, not an official MediaPipe release.

The wheel includes the source snapshot's Python code, generated metadata,
native library, OpenCV libraries, and OpenCV dependency license notices.
GPU delegates are disabled. OpenCV GUI, camera capture, FFmpeg, and GStreamer
backends are disabled in the native library; webcam-mods uses its own capture
and preview backends and explicitly selects MediaPipe's CPU delegate.

## Rebuild

Requires macOS ARM64, Xcode, `git`, `uv`, and substantial free disk space.
The script downloads and verifies Bazel 7.7.0 independently of system Bazel.

```sh
./scripts/build_mediapipe.py
```

Source and intermediate files stay under
`~/Library/Caches/webcam-mods/mediapipe-patched`; final wheel goes here.
The script stops native compilation below 3 GiB free. Cold builds can exceed
20 minutes. A rebuilt wheel may have a different checksum; run
`uv lock --refresh-package mediapipe`, update `SHA256SUMS`, then rerun `make verify` and `make e2e` after replacing it.

Experimental Metal-enabled wheels can be built separately for CPU/GPU comparisons:

```sh
./scripts/build_mediapipe.py --gpu
```

These go to `dist/mediapipe-metal`, leaving the checked-in CPU wheel unchanged.
Both builds currently carry the same source version; compare isolated environments
and record the wheel SHA256 plus build flags. GPU inputs on macOS require RGBA.

Build patches:

- `620ce401.patch`, `1d6e3acd.patch`: upstream LLVM mirror fixes, preserving the
  original archive checksum
- `opencv-linker.patch`: CMake linker path correction, parallel compilation,
  and disabled unused native capture/GUI/media backends
- `opencv-sdk.patch`: prevent old bundled zlib/libpng headers from treating
  modern Apple SDKs as classic Mac OS, and make the Cocoa-disable setting
  effective on OpenCV 3.4.11

Repository checkout installs use this wheel through `tool.uv.sources` on macOS ARM64.
Other platforms use official MediaPipe 1.0.1. Those source overrides apply to
`uv` project installs; a standalone `pip install webcam-mods` does not receive
this patched dependency. Remove the override when a tested official release
contains the upstream fix.
