#!/usr/bin/env python3
"""Measure portable pixel operations without capture, inference or output I/O."""

import argparse
import json
import statistics
import time
from collections.abc import Callable

import numpy as np

from webcam_mods.mods.person_segmentation import apply_alpha_mask
from webcam_mods.mods.video_mods import brighten
from webcam_mods.utils.video import Frame


def measure(operation: Callable[[], Frame], iterations: int, samples: int) -> float:
    for _ in range(5):
        operation()
    durations = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        for _ in range(iterations):
            operation()
        durations.append((time.perf_counter_ns() - started) / iterations / 1_000_000)
    return statistics.median(durations)


def benchmark(iterations: int = 50, samples: int = 5) -> dict[str, float]:
    if iterations < 1 or samples < 1:
        raise ValueError("iterations and samples must be positive")
    rng = np.random.default_rng(42)
    results = {}
    for width, height in ((640, 480), (1920, 1080)):
        frame = rng.integers(0, 256, (height, width, 3), np.uint8)
        background = rng.integers(0, 256, frame.shape, np.uint8)
        mask = rng.random((height, width, 1), dtype=np.float32)
        results[f"{width}x{height} brighten_ms"] = measure(
            lambda: brighten(frame, 30), iterations, samples
        )
        results[f"{width}x{height} blend_ms"] = measure(
            lambda: apply_alpha_mask(frame, background, mask), iterations, samples
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if args.iterations < 1 or args.samples < 1:
        parser.error("iterations and samples must be positive")
    print(json.dumps(benchmark(args.iterations, args.samples), indent=2))


if __name__ == "__main__":
    main()
