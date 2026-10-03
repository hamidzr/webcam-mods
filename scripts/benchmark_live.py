#!/usr/bin/env python3
"""Measure live capture, background blur and final-frame delivery through live_loop."""

import argparse
from collections.abc import Callable
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import resource
import sys
import tempfile
import time
from typing import Any

import cv2
import numpy as np

from webcam_mods.input.input import FrameInput, FrameOutput
from webcam_mods.loopback import default_frame_output, live_loop
from webcam_mods.mods.person_segmentation import PersonEffects
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.utils.video import Frame


class MeasuredInput(FrameInput):
    def __init__(self, source: FrameInput) -> None:
        super().__init__(
            width=source.width,
            height=source.height,
            fps=source.fps,
            device=source.device,
        )
        self.source = source
        self.started = 0.0
        self.capture_ms: list[float] = []
        self.properties: dict[str, Any] = {}

    def setup(self) -> dict[str, Any]:
        self.properties = self.source.setup()
        return self.properties

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.source.teardown(*args, **kwargs)

    def is_setup(self) -> bool:
        return self.source.is_setup()

    def frame(self) -> Frame | None:
        self.started = time.perf_counter()
        frame = self.source.frame()
        self.capture_ms.append((time.perf_counter() - self.started) * 1000)
        return frame


class MeasuredOutput(FrameOutput):
    def __init__(
        self,
        source: MeasuredInput,
        factory: Callable[[float], FrameOutput],
        settings: StartupSettings,
        save_frame: Path | None,
    ) -> None:
        super().__init__(
            width=settings.out_width,
            height=settings.out_height,
            fps=settings.max_out_fps,
            device=settings.video_out,
        )
        self.source, self.factory, self.save_frame = source, factory, save_frame
        self.output: FrameOutput | None = None
        self.send_ms: list[float] = []
        self.pipeline_ms: list[float] = []
        self.sent_at: list[float] = []
        self.last_frame: Frame | None = None
        self.properties: dict[str, Any] = {}

    def setup(self) -> dict[str, Any]:
        self.output = self.factory(self.source.properties["fps"])
        self.properties = self.output.setup()
        self.width, self.height, self.fps = (
            self.properties[key] for key in ("width", "height", "fps")
        )
        return self.properties

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        if self.output is not None:
            self.output.teardown(*args, **kwargs)

    def is_setup(self) -> bool:
        return self.output is not None and self.output.is_setup()

    def send(self, frame: Frame) -> None:
        assert self.output is not None
        started = time.perf_counter()
        self.output.send(frame)
        finished = time.perf_counter()
        self.send_ms.append((finished - started) * 1000)
        self.pipeline_ms.append((finished - self.source.started) * 1000)
        self.sent_at.append(finished)
        if self.save_frame is not None:
            self.last_frame = frame.copy()

    def process_events(self) -> None:
        assert self.output is not None
        self.output.process_events()

    def should_stop(self) -> bool:
        return self.output is not None and self.output.should_stop()


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "median_ms": float(np.median(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
    }


def run_benchmark(
    source: FrameInput,
    effect: Callable[[Frame], Frame],
    output_factory: Callable[[float], FrameOutput],
    settings: StartupSettings,
    *,
    frames: int = 100,
    warmup: int = 10,
    save_frame: Path | None = None,
    pace: bool = True,
) -> dict[str, Any]:
    if frames < 2 or warmup < 0:
        raise ValueError("frames must be at least two; warmup must be nonnegative")
    measured_input = MeasuredInput(source)
    measured_output = MeasuredOutput(
        measured_input, output_factory, settings, save_frame
    )
    processing_ms: list[float] = []

    def process(frame: Frame) -> Frame:
        started = time.perf_counter()
        result = effect(frame)
        processing_ms.append((time.perf_counter() - started) * 1000)
        return result

    live_loop(
        mod=process,
        fIn=measured_input,
        fOut=measured_output,
        interactive_listener=None,
        on_demand=False,
        max_frames=warmup + frames,
        strict_errors=True,
        settings=settings,
        pace=pace,
    )
    if measured_input.is_setup() or measured_output.is_setup():
        raise RuntimeError("benchmark adapters remain open after teardown")
    delivered = measured_output.sent_at[warmup:]
    if len(delivered) != frames:
        raise RuntimeError("output closed before benchmark completed")
    if save_frame is not None:
        save_frame.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(save_frame), measured_output.last_frame):
            raise OSError("cannot write requested final frame")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "live capture wait + background blur + final resize/padding + output send; no controls or recording",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "input": measured_input.properties,
        "output": measured_output.properties,
        "frames": frames,
        "warmup": warmup,
        "paced": pace,
        "cleanup_verified": True,
        "capture_wait": summarize(measured_input.capture_ms[warmup:]),
        "processing": summarize(processing_ms[warmup:]),
        "output_send": summarize(measured_output.send_ms[warmup:]),
        "capture_to_send": summarize(measured_output.pipeline_ms[warmup:]),
        "delivered_fps": (len(delivered) - 1) / (delivered[-1] - delivered[0]),
        "delivery_interval": summarize(
            [1000 * (b - a) for a, b in zip(delivered, delivered[1:])]
        ),
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "limits": "capture wait is not exposure latency; send completion is not conferencing reception; RSS is process lifetime high-water and includes warmup; power unmeasured",
    }


def run_cycles(
    run: Callable[[int], dict[str, Any]],
    cycles: int,
    checkpoint: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Keep per-cycle evidence, stopping on the first failure or interruption."""
    if cycles < 1:
        raise ValueError("cycles must be positive")
    report: dict[str, Any] = {
        "status": "running",
        "cycles_requested": cycles,
        "cycles_completed": 0,
        "runs": [],
    }
    checkpoint(report)
    for cycle in range(1, cycles + 1):
        try:
            result = run(cycle)
        except BaseException as error:
            report.update(
                status=(
                    "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
                ),
                failed_cycle=cycle,
                error_type=type(error).__name__,
            )
            try:
                checkpoint(report)
            except Exception as checkpoint_error:
                error.add_note(f"cannot save failure report: {checkpoint_error}")
            raise
        report["runs"].append(result)
        report["cycles_completed"] = cycle
        if cycle == cycles:
            report["status"] = "passed"
        checkpoint(report)
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Replace checkpoints atomically so failed writes retain previous evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(report, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture", choices=("opencv", "avfoundation"), default="avfoundation"
    )
    parser.add_argument("--backend", choices=("mediapipe", "vision"), default="vision")
    parser.add_argument(
        "--processing", choices=("opencv", "coreimage"), default="opencv"
    )
    parser.add_argument(
        "--quality", choices=("fast", "balanced", "accurate"), default="fast"
    )
    parser.add_argument(
        "--output-backend", choices=("preview", "virtual-cam"), default="preview"
    )
    parser.add_argument(
        "--input-device",
        type=int,
        help="Input camera index; AVFoundation excludes OBS output. Overrides VIDEO_IN.",
    )
    parser.add_argument(
        "--mask-smoothing", action="store_true", help="Stabilize segmentation edges."
    )
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument(
        "--cycles", type=int, default=1, help="Fresh capture/effect/output runs."
    )
    parser.add_argument(
        "--report", type=Path, default=Path("dist/benchmarks/live.json")
    )
    parser.add_argument(
        "--save-frame",
        type=Path,
        help="Save final image; multiple cycles add a -cycle-N suffix.",
    )
    args = parser.parse_args()
    if args.frames < 2 or args.warmup < 0 or args.cycles < 1:
        parser.error("frames >= 2, warmup >= 0 and cycles >= 1 are required")
    settings = load_settings(video_in=args.input_device)
    workload = {
        "capture": args.capture,
        "backend": args.backend,
        "processing": args.processing,
        "quality": args.quality,
        "output_backend": args.output_backend,
        "kernel_size": 31,
        "mask_smoothing": args.mask_smoothing,
        "input_device": settings.video_in,
        "requested_input": {
            "width": settings.in_width,
            "height": settings.in_height,
            "fps": settings.in_fps,
        },
    }

    def run(cycle: int) -> dict[str, Any]:
        if args.capture == "avfoundation":
            from webcam_mods.macos.capture import AVFoundationCamera

            source: FrameInput = AVFoundationCamera(
                device_index=settings.video_in,
                width=settings.in_width,
                height=settings.in_height,
                fps=settings.in_fps,
                device=settings.video_out,
            )
        else:
            from webcam_mods.input.video_dev import Webcam

            source = Webcam(settings=settings)
        save_frame = args.save_frame
        if save_frame is not None and args.cycles > 1:
            save_frame = save_frame.with_name(
                f"{save_frame.stem}-cycle-{cycle}{save_frame.suffix}"
            )
        with ExitStack() as resources:
            effects = PersonEffects(
                backend=args.backend,
                processing=args.processing,
                quality=args.quality,
                smoothing=args.mask_smoothing,
            )
            resources.callback(effects.close)
            result = run_benchmark(
                source,
                lambda frame: effects.blur_bg(frame, 31),
                lambda fps: default_frame_output(
                    fps, backend=args.output_backend, settings=settings
                ),
                settings,
                frames=args.frames,
                warmup=args.warmup,
                save_frame=save_frame,
            )
        result["workload"] = workload
        print(
            json.dumps(
                {
                    "cycle": cycle,
                    **{
                        key: result[key]
                        for key in (
                            "processing",
                            "capture_to_send",
                            "delivered_fps",
                            "process_peak_rss_bytes",
                        )
                    },
                },
                indent=2,
            )
        )
        return result

    def checkpoint(report: dict[str, Any]) -> None:
        write_report(args.report, {"workload": workload, **report})

    report = run_cycles(run, args.cycles, checkpoint)
    if args.cycles == 1:
        checkpoint(report["runs"][0])
    print(f"saved {args.report}")


if __name__ == "__main__":
    main()
