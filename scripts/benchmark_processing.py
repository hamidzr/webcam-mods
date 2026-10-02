#!/usr/bin/env python3
"""Benchmark background processing on moving disk frames, excluding capture/output."""

import argparse
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any, Callable, Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

Frame = NDArray[np.uint8]
FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/astronaut.png"


class Effects(Protocol):
    def blur_bg(self, frame: Frame, kernel_size: int) -> Frame:
        """Process one BGR frame."""
        ...

    def close(self) -> None:
        """Release native or model resources."""
        ...


@dataclass(frozen=True)
class BenchmarkOptions:
    frames: int = 100
    warmup: int = 10
    width: int = 640
    height: int = 480
    backend: str = "mediapipe"
    processing: str = "opencv"
    quality: str = "balanced"


def create_effects(options: BenchmarkOptions) -> Effects:
    from webcam_mods.mods.person_segmentation import PersonEffects

    return PersonEffects(
        backend=options.backend, processing=options.processing, quality=options.quality
    )


def run_benchmark(
    options: BenchmarkOptions,
    output: Path,
    *,
    fixture: Path = FIXTURE,
    factory: Callable[[BenchmarkOptions], Effects] = create_effects,
) -> dict[str, Any]:
    if min(options.frames, options.width, options.height) < 1 or options.warmup < 0:
        raise ValueError(
            "frames and dimensions must be positive; warmup must be nonnegative"
        )
    source = cv2.imread(str(fixture))
    if source is None:
        raise FileNotFoundError(f"cannot decode fixture: {fixture}")
    source = cv2.resize(source, (options.width, options.height))
    effects = factory(options)
    timings = []
    result = None
    try:
        for index in range(options.warmup + options.frames):
            # generate identical motion for every backend, outside processing timing
            frame = np.roll(source, (index % 9) - 4, axis=1)
            started = time.perf_counter_ns()
            result = effects.blur_bg(frame, 31)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            if (
                result is None
                or result.shape != source.shape
                or result.dtype != np.uint8
            ):
                raise ValueError("effect returned invalid BGR output")
            if index >= options.warmup:
                timings.append(elapsed_ms)
    finally:
        effects.close()

    packages = {}
    for name in (
        "numpy",
        "opencv-python",
        "opencv-contrib-python",
        "mediapipe",
        "pyobjc-core",
    ):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            pass
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report: dict[str, Any] = {
        "scope": "disk fixture background blur; capture, output, initialization and frame generation excluded",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "packages": packages,
        },
        "workload": {
            **vars(options),
            "fixture": fixture.name,
            "motion": "horizontal roll from -4 through 4 pixels",
            "kernel_size": 31,
            "blur_kernel": "box" if options.processing == "opencv" else "Gaussian",
        },
        "median_ms": float(np.median(timings)),
        "p95_ms": float(np.percentile(timings, 95)),
        "processing_frames_per_second": 1000 * len(timings) / sum(timings),
        "output_shape": list(result.shape),
        "output_dtype": str(result.dtype),
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "memory_scope": "whole-process lifetime high-water RSS; includes imports, initialization and warmup",
        "samples_ms": timings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    image_path = output.with_suffix(".png")
    if not cv2.imwrite(str(image_path), result):
        raise OSError(f"cannot write output image: {image_path}")
    report["output_image"] = image_path.name
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument(
        "--backend", choices=("mediapipe", "vision"), default="mediapipe"
    )
    parser.add_argument(
        "--processing", choices=("opencv", "coreimage"), default="opencv"
    )
    parser.add_argument(
        "--quality", choices=("fast", "balanced", "accurate"), default="balanced"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("dist/benchmarks/processing.json")
    )
    args = parser.parse_args()
    output = args.output
    options = BenchmarkOptions(
        **{key: value for key, value in vars(args).items() if key != "output"}
    )
    report = run_benchmark(options, output)
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("median_ms", "p95_ms", "processing_frames_per_second")
            },
            indent=2,
        )
    )
    print(f"saved {output} and {output.with_suffix('.png')}")


if __name__ == "__main__":
    main()
