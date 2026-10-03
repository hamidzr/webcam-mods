# macOS on-demand standby proposal

Status: deferred on 2026-10-03. No implementation planned for now. Startup-time
optimization is a possible next task, pending measurement and a separate request.

## Goal

Keep the process available while releasing the physical camera and skipping
capture/effect processing when no application receives virtual-camera frames.
Resume automatically when a receiver starts. Brief camera access at startup is
acceptable; battery use and idle processing cost are the main concerns.

Current macOS output always reports itself in use, so `--on-demand` does not
provide this behavior with OBS/pyvirtualcam.

## Proposed approach with existing OBS

OBS exposes separate producer sink and receiver source streams, but no public
receiver-count property. The macOS device-running flag includes our producer.
Checking it continuously while producing frames cannot distinguish receivers.

Periodically stop the producer sink briefly, then check whether the device still
runs because a receiver remains active. Restart the producer if a receiver is
present. Otherwise, leave the producer stopped, release the physical camera and
skip effects. Keep the process and loaded models available.

While idle, poll receiver activity with the producer stopped. OBS remains
selectable and supplies its own placeholder. When a receiver starts, reopen the
physical camera and restart production and effects.

The polling interval trades wake/standby latency against probe frequency. During
active video, stopping the producer may expose OBS's placeholder and cause a
visible flash. No safe interval or pause duration has been established.

## Evidence and remaining checks

Local probes confirmed that the producer sink can stop and restart, and that
device-running status includes the producer. AVFoundation's
`isInUseByAnotherApplication` remained false with a separate receiver running,
so it is not a reliable detector in the tested setup. Status updates are
asynchronous; immediate reads after stopping the sink can still report activity.

These probes do not establish a reliable automatic standby implementation.
Before implementing, verify repeated idle/receive/stop cycles, multiple receivers,
receiver crashes, status propagation delays, output recovery and visible frame
quality in conferencing applications. Measure idle CPU and power against the
current behavior on the same workload. Avoid treating a transient false status
or a detection error as proof that all receivers stopped.

## Alternatives

- Manual standby/wake would release the camera and skip effects while retaining
  the process and models, avoiding relaunch/model-loading costs. It would require
  user action and would not satisfy automatic receiver-triggered wake.
- A custom camera extension could expose receiver activity directly for seamless
  automatic standby, but adds extension implementation, installation and signing
  work.

## Source references

- [OBS camera extension lifecycle](https://github.com/obsproject/obs-studio/blob/master/plugins/mac-virtualcam/src/camera-extension/OBSCameraDeviceSource.swift)
- [pyvirtualcam OBS producer](https://github.com/letmaik/pyvirtualcam/blob/main/pyvirtualcam/native_macos_obs_cmioextension/virtual_output.hpp)
- [Apple device-running property](https://developer.apple.com/documentation/coremediaio/kcmiodevicepropertydeviceisrunningsomewhere)
