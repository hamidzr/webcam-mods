# Independent frame delivery

Use repeat mode when a receiving client expects 30 FPS but capture or effects run
at a lower rate:

```sh
webcam_mods bg-blur --repeat-frames --processing-fps 15 --output-fps 30
```

Capture still requests `--input-fps` (30 by default). Processing runs at most
`min(processing FPS, negotiated input FPS, output FPS)`. To request 15 FPS from a
camera that supports it, also set `--input-fps 15`. Output advertises and delivers
30 FPS independently, repeating the latest completed frame until a fresh frame
arrives. Repeated frames do not rerun effects, controls, or recording. They do not
add motion information or interpolate movement.

`REPEAT_FRAMES=true`, `PROCESSING_FPS=15`, and `MAX_OUT_FPS=30` are equivalent
environment settings. CLI overrides environment values. Repeat mode is opt-in;
without it the existing delivery cap and synchronous processing behavior remain.
`--processing-fps` applies only in repeat mode.

One worker owns capture setup, capture, effects, and between-frame commands.
Output and preview events remain on the calling thread. An owned latest-frame
snapshot replaces the previous snapshot; completed frames never build a queue.
Before the first completed frame, output repeats the no-signal image. Empty input
keeps repeating the previous frame; strict or bounded runs raise instead.
Effect failures retain the existing error-image / `--freeze-on-error` policy.
Capture and output failures stop the run.

On-demand mode closes paused capture and continues delivering the no-signal image
at output FPS. Shutdown signals the worker and waits for an in-flight capture or
effect call before closing effect resources. A blocked native call can delay
shutdown until it returns. Output timing remains best effort: OS scheduling,
blocking output writes, or native work holding Python's GIL can cause missed
frames. Missed delivery deadlines are skipped rather than sent in a burst.

Lower processing rates reduce effect invocations. Battery savings have not been
measured; repeated output still incurs transfer and backend conversion costs.
