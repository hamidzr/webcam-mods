#!/usr/bin/env python3
"""Time cold delegate calibration without opening a camera or modifying caches.

uv run scripts/benchmark_startup.py --compare-legacy
Synthetic BGR input is materialized before timing. Cached models are required.
"""

import argparse
import hashlib
from io import BytesIO
import json
import os
import platform
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# calibration subprocesses must measure the same source as this harness
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(ROOT / "src"), *filter(None, [os.environ.get("PYTHONPATH")])]
)

from webcam_mods import mediapipe_delegate as delegates, models
from webcam_mods.settings import StartupSettings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--compare-legacy", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("CPU/Metal calibration requires Apple Silicon macOS")
    StartupSettings(in_width=args.width, in_height=args.height)
    for name, (url, expected_hash) in models._MODELS.items():
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        path = root / "webcam-mods" / "models" / f"{name}{Path(url).suffix}"
        if not path.is_file():
            parser.error("cached models required; run just models first")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected_hash:
                parser.error("cached model checksum invalid; run just models first")
    frame = np.zeros((args.height, args.width, 3), np.uint8)
    buffer = BytesIO()
    np.save(buffer, frame, allow_pickle=False)
    report: dict[str, Any] = {
        "input": "synthetic black BGR",
        "shape": list(frame.shape),
    }
    for task in ("face", "segmentation"):
        measurements: dict[str, Any] = {}
        if args.compare_legacy:
            legacy: dict[str, list[float]] = {"cpu": [], "gpu": []}
            started = time.perf_counter()
            for round_index in range(delegates._ROUNDS):
                for delegate in (
                    ("cpu", "gpu") if round_index % 2 == 0 else ("gpu", "cpu")
                ):
                    legacy[delegate].append(
                        delegates._probe(task, delegate, buffer.getvalue())
                    )
            measurements["legacy_seconds"] = time.perf_counter() - started
            measurements["legacy_selected"] = (
                "gpu"
                if all(g < c * 0.95 for c, g in zip(legacy["cpu"], legacy["gpu"]))
                else "cpu"
            )
        started = time.perf_counter()
        cpu, gpu = delegates._calibrate(task, frame)
        measurements["seconds"] = time.perf_counter() - started
        measurements["cpu_median_ms"] = cpu
        measurements["gpu_median_ms"] = gpu
        measurements["selected"] = (
            "gpu" if all(g < c * 0.95 for c, g in zip(cpu, gpu)) else "cpu"
        )
        report[task] = measurements
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
