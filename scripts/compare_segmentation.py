#!/usr/bin/env python3
"""Compare raw/stabilized masks on deterministic fixtures or recorded BGR video.

Run each backend/quality in a fresh process for comparable peak RSS.
Fixture transforms probe stability/cost, not real hair/hand segmentation accuracy.
"""

import argparse
import json
from pathlib import Path
import resource
import sys
import time
from typing import Iterator

import cv2
import numpy as np

from webcam_mods.mods.mask_stabilizer import MaskStabilizer
from webcam_mods.mods.person_segmentation import PersonEffects, apply_alpha_mask
from webcam_mods.utils.video import Frame

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/astronaut.png"


def frames(
    source: Path, count: int, width: int, height: int
) -> Iterator[tuple[str, Frame]]:
    if min(count, width, height) < 1:
        raise ValueError("frames and dimensions must be positive")
    image = cv2.imread(str(source))
    if image is not None:
        image = cv2.resize(image, (width, height))
        for phase in ("static", "translation", "dim", "departure"):
            for index in range(count):
                if phase == "translation":
                    transform = np.float32([[1, 0, (index % 15) - 7], [0, 1, 0]])
                    frame = cv2.warpAffine(image, transform, (width, height))
                elif phase == "dim":
                    frame = (image.astype(np.float32) * 0.3).astype(np.uint8)
                elif phase == "departure":
                    frame = np.zeros_like(image)
                else:
                    frame = image.copy()
                yield phase, frame
        return
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError(f"cannot decode image/video: {source}")
        for _ in range(count):
            ok, frame = capture.read()
            if not ok:
                break
            yield "recorded", cv2.resize(frame, (width, height))
    finally:
        capture.release()


def compare(
    source: Path,
    output: Path,
    effects: PersonEffects,
    count: int = 30,
    width: int = 640,
    height: int = 480,
) -> dict[str, object]:
    stabilizer = MaskStabilizer()
    phases: dict[str, dict[str, list[float]]] = {}
    previous_raw = previous_smooth = None
    current_phase = None
    warmed = False
    rows = []
    last_masks = {}
    try:
        for phase, frame in frames(source, count, width, height):
            if not warmed:
                for _ in range(10):
                    effects.mask(frame)
                warmed = True
            if phase != current_phase:
                # retain history across phase transitions to expose lag/departure
                previous_raw = previous_smooth = None
                current_phase = phase
                phases[phase] = {
                    key: []
                    for key in (
                        "segmentation_ms",
                        "smoothing_ms",
                        "raw_delta",
                        "smooth_delta",
                        "deviation",
                    )
                }
            started = time.perf_counter_ns()
            image, alpha = effects.mask(frame)
            infer_ms = (time.perf_counter_ns() - started) / 1e6
            raw = alpha[:, :, 0]
            started = time.perf_counter_ns()
            smooth = stabilizer.apply(image, raw)
            smoothing_ms = (time.perf_counter_ns() - started) / 1e6
            samples = phases[phase]
            samples["segmentation_ms"].append(infer_ms)
            samples["smoothing_ms"].append(smoothing_ms)
            samples["deviation"].append(float(np.abs(raw - smooth).mean()))
            if previous_raw is not None:
                samples["raw_delta"].append(float(np.abs(raw - previous_raw).mean()))
                samples["smooth_delta"].append(
                    float(np.abs(smooth - previous_smooth).mean())
                )
            previous_raw, previous_smooth = raw.copy(), smooth.copy()
            last_masks[phase + "_raw"] = raw
            last_masks[phase + "_smooth"] = smooth
            # first and last frames expose transition response and settled detail
            if len(samples["segmentation_ms"]) in (1, count):
                background = np.asarray((0, 255, 0), dtype=np.float32)
                tiles = [
                    image,
                    apply_alpha_mask(image, background, raw),
                    apply_alpha_mask(image, background, smooth),
                    cv2.cvtColor((smooth * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR),
                ]
                row = np.concatenate(tiles, axis=1)
                cv2.putText(
                    row,
                    f"{phase} {len(samples['segmentation_ms'])}: source / raw / smooth / mask",
                    (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )
                rows.append(row)
    finally:
        effects.close()
    if not rows:
        raise ValueError("source contains no frames")
    output.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output / "comparison.jpg"), np.concatenate(rows, axis=0)):
        raise OSError("cannot write comparison sheet")
    np.savez_compressed(output / "masks.npz", **last_masks)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report: dict[str, object] = {
        "scope": "image fixture transforms or recorded video; no capture/output; no ground-truth accuracy score",
        "dimensions": [width, height],
        "warmup_frames": 10,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "memory_scope": "whole-process peak including imports, model initialization, sheets and masks",
        "phases": {
            phase: {
                key: {
                    "mean": float(np.mean(values)),
                    "p95": float(np.percentile(values, 95)),
                }
                for key, values in samples.items()
                if values
            }
            for phase, samples in phases.items()
        },
    }
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--frames",
        type=int,
        default=30,
        help="Frames per fixture phase, or video limit.",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--backend", choices=("mediapipe", "vision"), default="vision")
    parser.add_argument(
        "--quality", choices=("fast", "balanced", "accurate"), default="fast"
    )
    args = parser.parse_args()
    report = compare(
        args.source,
        args.output,
        PersonEffects(backend=args.backend, quality=args.quality),
        args.frames,
        args.width,
        args.height,
    )
    report["backend"], report["quality"] = args.backend, args.quality
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
