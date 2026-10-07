# Remote cameras and microphones

Status: proposal, 2026-10-07. No remote receiver or microphone pipeline is
implemented. This document captures an extension idea, not a committed roadmap.

## Idea

Use an Android phone as a network camera and, optionally, a network microphone.
Webcam Mods receives the media on the computer and exposes it to applications
through local virtual devices. Video retains the existing crop, tracking,
background and brightness effects. Audio follows a separate path.

Define a connection contract that can represent video only, audio only, or both.
Implement video first. The first version can use the computer's existing
microphone while the phone supplies the camera.

```text
Android camera -> network receiver -> decoded BGR frames -> effects -> virtual camera
Android mic    -> network receiver -> decoded audio -> audio output -> virtual mic
```

Applications select the camera and microphone independently. Receiving network
audio alone does not make it available as a system microphone.

## Fit with the current project

The existing `FrameInput` interface supplies frames and negotiated dimensions/FPS
to the processing loop. A remote input adapter could supply decoded uint8 BGR
frames through that interface, reusing effects, sizing, preview and virtual-camera
output. macOS output already uses pyvirtualcam with OBS Virtual Camera; Linux uses
V4L2. See [current architecture](architecture.md).

The local JSONL helper controls sessions over stdin/stdout. It is not a network
API. Remote pairing and signaling need a separate, authenticated boundary rather
than exposing the helper directly. Android sender implementation and desktop
receiver implementation are separate deliverables.

## Transport and API direction

Prefer WebRTC for live media. It supports audio and video tracks, while connection
signaling is supplied by the application. HTTP or WebSocket can carry offers,
answers and ICE candidates. See [WebRTC peer connections](https://webrtc.org/getting-started/peer-connections).

Our API should manage connection setup and control; media travels through WebRTC.
Keep the contract independent of Android so other senders can implement it later.
Exact endpoint names, signaling schema, codecs and receiver library remain open.

The contract should cover:

- Protocol version, sender identity and supported tracks/capture settings.
- Pairing and authorization, with explicit approval of a sender.
- Session creation with requested video/audio tracks and negotiated settings.
- WebRTC signaling, including connection failure and reconnection.
- Start, stop and status, including which tracks are actually delivering media.
- Supported controls such as camera selection, orientation and microphone mute.

Capabilities describe both what the phone can send and what the desktop can
consume. A video-only receiver must reject unsupported audio requests explicitly.
Supporting optional audio in the contract does not promise an audio implementation.

First version targets one phone on the same local network. Pairing could use a QR
code containing a short-lived connection invitation. Pairing must authenticate
the signaling channel and bind the media connection to the approved sender.
Stop must cancel waits and release receiver resources. Disconnect must visibly
end live delivery or show no-signal, with a defined reconnect window.

Internet support is a later step. NAT traversal can require STUN and TURN, with
relay deployment and operating costs beyond the local-network prototype.

## Receiver behavior

Decode video into a bounded newest-frame buffer so slow effects do not accumulate
an ever-growing queue. Preserve source timestamps and orientation alongside
frames for latency measurement and future synchronization. The current frame
interface carries an array without media timestamps, so that metadata needs an
explicit design before combined audio/video support.

Negotiate capture size/FPS and bound decoded dimensions before processing. Keep
network reception separate from effect execution and reuse existing cancellation
and cleanup ownership. Initial scope uses one remote source per session; hot
switching and multiple simultaneous sources are deferred.

## Optional microphone output

Audio requires its own output adapter and pacing. It cannot use pyvirtualcam or
the video frame loop. Continuous audio needs jitter buffering, sample-rate
conversion, clock-drift handling and defined underrun behavior. Processed video
can arrive later than audio, so combined output also needs measured lip-sync
compensation with bounded buffering.

On macOS, a practical prototype would write decoded PCM audio to an independently
installed BlackHole device. The receiving application selects BlackHole as its
microphone. This reuses an existing virtual audio driver; it still requires audio
playback integration and user device selection. See [BlackHole routing](https://github.com/ExistentialAudio/BlackHole#route-audio-between-applications).

Custom audio drivers, bundled driver distribution and other platform audio
backends remain separate decisions. Microphone-only sessions can reuse the same
connection contract when an audio backend exists. Speaker return audio and echo
cancellation are outside the initial scope.

## Suggested stages and acceptance

1. **Remote camera:** Android sender, local-network pairing, video receiver,
   existing effects and preview/virtual-camera output. Verify reception in an
   actual calling application, orientation, bounded buffering, disconnect,
   reconnect and Stop cleanup. Measure latency and sustained FPS on real devices.
2. **Optional microphone:** audio track reception and existing virtual audio
   device integration. Verify microphone selection, underruns, long-run drift,
   mute/disconnect behavior and synchronization with processed video.
3. **Broader connectivity:** internet connections, relay infrastructure, other
   senders and platform audio adapters if needed.

Before implementation, choose the first desktop target, Android capture/WebRTC
integration, compatible desktop receiver library and signaling/pairing design.
Keep the first milestone camera-only unless phone microphone input is essential.
