# Webcam Mods Camera for macOS

Native virtual camera built with Apple's Core Media I/O Camera Extension API.
Minimum macOS version: 12.3.

This first stage publishes a 640x480, 30 fps test pattern. It does not yet receive
frames from the Python pipeline. The Python output adapter and frame transport come
next; the existing Linux output stays separate.

## Build

Open `WebcamModsCamera.xcodeproj` in Xcode. Set the development team for both
targets, then build the `WebcamModsCamera` scheme. For a compile-only check without
signing:

```sh
xcodebuild -project macos/WebcamModsCamera.xcodeproj \
  -scheme WebcamModsCamera -configuration Debug \
  CODE_SIGNING_ALLOWED=NO build
```

## Activate

Copy the signed app to `/Applications`, launch it there, and select **Activate
Camera**. Approve the extension in System Settings > Privacy & Security if macOS
asks. Select **Webcam Mods** in a camera app to check the moving test pattern.

Select **Deactivate Camera** in the app to remove the device. The app and extension
must use the same Apple development team. For distribution outside the Mac App
Store, sign and notarize the app and embedded extension.
