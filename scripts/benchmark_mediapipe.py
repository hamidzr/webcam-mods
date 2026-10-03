#!/usr/bin/env python3
"""Compare CPU/Metal with identical RGBA inputs and one installed MediaPipe wheel.

Workers isolate native aborts. Moving fixture frames are materialized before timing.
Segmentation total uses the app's exact OpenCV background blur path. Capture,
virtual-camera output, initialization and frame generation are excluded.
"""

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
Frame = NDArray[np.uint8]
Mask = NDArray[np.float32]


def stats(samples: list[float]) -> dict[str, Any]:
    return {
        "median_ms": float(np.median(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
        "mean_ms": float(np.mean(samples)),
        "samples_ms": samples,
    }


class TimedTask:
    def __init__(self, task: str, delegate: str, image_format: str) -> None:
        import mediapipe as mp
        from webcam_mods.models import model_path

        self.mp = mp
        self.task = task
        self.image_format = image_format
        self.timestamp = 0
        self.inference_ms = 0.0
        self.boundary_ms = 0.0
        self.mask: Mask | None = None
        self.boxes: list[list[int]] = []
        base = mp.tasks.BaseOptions(
            model_asset_path=str(
                model_path(
                    "selfie_segmenter"
                    if task == "segmentation"
                    else "blaze_face_full_range"
                )
            ),
            delegate=getattr(mp.tasks.BaseOptions.Delegate, delegate.upper()),
        )
        vision = mp.tasks.vision
        if task == "segmentation":
            self.native = vision.ImageSegmenter.create_from_options(
                vision.ImageSegmenterOptions(
                    base_options=base,
                    running_mode=vision.RunningMode.VIDEO,
                    output_confidence_masks=True,
                )
            )
        else:
            self.native = vision.FaceDetector.create_from_options(
                vision.FaceDetectorOptions(
                    base_options=base,
                    running_mode=vision.RunningMode.VIDEO,
                    min_detection_confidence=0.6,
                )
            )

    def predict(self, frame: Frame) -> Mask:
        started = time.perf_counter_ns()
        image = self.mp.Image(
            image_format=getattr(self.mp.ImageFormat, self.image_format),
            data=np.ascontiguousarray(
                cv2.cvtColor(
                    frame,
                    (
                        cv2.COLOR_BGR2RGBA
                        if self.image_format == "SRGBA"
                        else cv2.COLOR_BGR2RGB
                    ),
                )
            ),
        )
        self.timestamp += 34
        infer_started = time.perf_counter_ns()
        if self.task == "segmentation":
            result = self.native.segment_for_video(image, self.timestamp)
        else:
            result = self.native.detect_for_video(image, self.timestamp)
        infer_finished = time.perf_counter_ns()
        self.inference_ms = (infer_finished - infer_started) / 1e6
        if self.task == "segmentation":
            self.mask = (
                np.asarray(result.confidence_masks[0].numpy_view(), dtype=np.float32)
                .reshape(frame.shape[:2])
                .copy()
            )
        else:
            self.boxes = [
                [box.origin_x, box.origin_y, box.width, box.height]
                for detection in result.detections
                for box in [detection.bounding_box]
            ]
        self.boundary_ms = (time.perf_counter_ns() - started) / 1e6
        return (
            self.mask if self.mask is not None else np.empty((0, 0), dtype=np.float32)
        )

    def close(self) -> None:
        self.native.close()


def worker(args: argparse.Namespace) -> None:
    from webcam_mods.mods.person_segmentation import MediaPipeSegmenter, PersonEffects

    # match CPU threading across processes and avoid OpenCV oversubscription
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    cv2.setNumThreads(1)
    load_start = os.getloadavg()
    frames: NDArray[np.uint8] = np.load(args.input)
    task = TimedTask(args.task, args.delegate, args.image_format)
    effects = PersonEffects()
    effects.segmenter = cast(MediaPipeSegmenter, task)
    samples: dict[str, list[float]] = {
        "api_inference": [],
        "inference_with_boundaries": [],
        "processing_total": [],
    }
    masks: list[Mask] = []
    boxes: list[list[list[int]]] = []
    valid = 0
    output: Frame = frames[0]
    try:
        for index in range(args.warmup + args.frames):
            frame = frames[index % len(frames)]
            started = time.perf_counter_ns()
            if args.task == "segmentation":
                output = effects.blur_bg(frame, 31)
            else:
                task.predict(frame)
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if args.task == "face":
                output = frame
            if task.mask is not None and (
                not np.isfinite(task.mask).all()
                or not (0 <= task.mask.min() <= task.mask.max() <= 1)
            ):
                raise ValueError("invalid confidence mask")
            if index < args.warmup:
                continue
            samples["api_inference"].append(task.inference_ms)
            samples["inference_with_boundaries"].append(task.boundary_ms)
            samples["processing_total"].append(elapsed)
            valid += int(
                task.mask is not None
                if args.task == "segmentation"
                else bool(task.boxes)
            )
            if index in (args.warmup, args.warmup + args.frames - 1):
                if task.mask is not None:
                    masks.append(task.mask.copy())
                boxes.append(task.boxes)
    finally:
        effects.close()
    if args.task == "face":
        output = output.copy()
        for left, top, width, height in task.boxes:
            cv2.rectangle(
                output, (left, top), (left + width, top + height), (0, 255, 0), 2
            )
    if not cv2.imwrite(str(args.output.with_suffix(".png")), output):
        raise OSError("cannot write output PNG")
    if masks:
        np.savez_compressed(args.output.with_suffix(".npz"), masks=np.asarray(masks))
    report = {
        "task": args.task,
        "delegate": args.delegate,
        "image_format": args.image_format,
        "environment": {
            "mediapipe": version("mediapipe"),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "opencv_threads": cv2.getNumThreads(),
            "load_average_start": load_start,
            "load_average_end": os.getloadavg(),
            "native_libraries_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in Path(task.mp.__file__).parent.rglob("libmediapipe*")
                if path.is_file()
            },
        },
        "timings": {name: stats(values) for name, values in samples.items()},
        "valid_frames": valid,
        "frames": args.frames,
        "boxes_first_last": boxes,
        "mask_foreground_fraction_first_last": [
            float(np.mean(mask > 0.5)) for mask in masks
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")


def orchestrate(args: argparse.Namespace) -> None:
    from webcam_mods.models import model_path

    if args.frames < 1 or args.warmup < 0 or args.rounds < 1:
        raise ValueError("frames/rounds must be positive and warmup nonnegative")
    source = cv2.imread(str(args.source))
    if source is None:
        raise ValueError(f"cannot decode {args.source}")
    args.output.mkdir(parents=True, exist_ok=True)
    models = {
        name: hashlib.sha256(model_path(name).read_bytes()).hexdigest()
        for name in ("selfie_segmenter", "blaze_face_full_range")
    }
    runs: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    for resolution in args.resolutions:
        width, height = (int(value) for value in resolution.split("x"))
        if min(width, height) < 1:
            raise ValueError("dimensions must be positive")
        image = cv2.resize(source, (width, height))
        input_path = args.output / f"frames-{resolution}.npy"
        np.save(
            input_path,
            np.asarray([np.roll(image, shift, axis=1) for shift in range(-4, 5)]),
        )
        for round_index in range(args.rounds):
            delegates: tuple[str, ...] = (
                ("cpu", "gpu") if round_index % 2 == 0 else ("gpu", "cpu")
            )
            if args.cpu_baseline:
                delegates += ("cpu-srgb",)
            for task in ("face", "segmentation"):
                pair: dict[str, Path] = {}
                for delegate in delegates:
                    output = (
                        args.output
                        / f"{resolution}-{task}-{delegate}-{round_index}.json"
                    )
                    command = [
                        args.python,
                        str(Path(__file__).resolve()),
                        "--worker",
                        "--task",
                        task,
                        "--delegate",
                        delegate.split("-")[0],
                        "--image-format",
                        "SRGB" if delegate == "cpu-srgb" else "SRGBA",
                        "--input",
                        str(input_path.resolve()),
                        "--output",
                        str(output.resolve()),
                        "--frames",
                        str(args.frames),
                        "--warmup",
                        str(args.warmup),
                    ]
                    print(
                        f"{resolution} round {round_index + 1}: {task} {delegate}",
                        flush=True,
                    )
                    with output.with_suffix(".log").open("w") as log:
                        try:
                            code: int | str
                            completed = subprocess.run(
                                command, stdout=log, stderr=log, timeout=args.timeout
                            )
                            code = completed.returncode
                        except subprocess.TimeoutExpired:
                            code = "timeout"
                    run: dict[str, Any] = {
                        "resolution": resolution,
                        "round": round_index,
                        "task": task,
                        "delegate": delegate,
                        "exit_code": code,
                    }
                    if code == 0:
                        run["result"] = json.loads(output.read_text())
                        if delegate in ("cpu", "gpu"):
                            pair[delegate] = output
                    runs.append(run)
                if len(pair) == 2:
                    comparison: dict[str, Any] = {
                        "resolution": resolution,
                        "round": round_index,
                        "task": task,
                    }
                    if task == "segmentation":
                        with (
                            np.load(pair["cpu"].with_suffix(".npz")) as cpu,
                            np.load(pair["gpu"].with_suffix(".npz")) as gpu,
                        ):
                            delta = np.abs(cpu["masks"] - gpu["masks"])
                            comparison.update(
                                mask_mean_absolute_error=float(delta.mean()),
                                mask_max_absolute_error=float(delta.max()),
                            )
                    else:
                        comparison["boxes_cpu"] = json.loads(pair["cpu"].read_text())[
                            "boxes_first_last"
                        ]
                        comparison["boxes_gpu"] = json.loads(pair["gpu"].read_text())[
                            "boxes_first_last"
                        ]
                        comparison["face_counts_match"] = all(
                            len(cpu_boxes) == len(gpu_boxes)
                            for cpu_boxes, gpu_boxes in zip(
                                comparison["boxes_cpu"], comparison["boxes_gpu"]
                            )
                        )
                        if comparison["face_counts_match"]:
                            coordinate_errors = [
                                abs(cpu_coordinate - gpu_coordinate)
                                for cpu_boxes, gpu_boxes in zip(
                                    comparison["boxes_cpu"], comparison["boxes_gpu"]
                                )
                                for cpu_box, gpu_box in zip(cpu_boxes, gpu_boxes)
                                for cpu_coordinate, gpu_coordinate in zip(
                                    cpu_box, gpu_box
                                )
                            ]
                            comparison["box_coordinate_max_absolute_error_pixels"] = (
                                max(coordinate_errors, default=0)
                            )
                    parity.append(comparison)
        input_path.unlink()
    aggregates = []
    for resolution in args.resolutions:
        for task in ("face", "segmentation"):
            for delegate in (
                ("cpu", "gpu", "cpu-srgb") if args.cpu_baseline else ("cpu", "gpu")
            ):
                matching = [
                    run["result"]
                    for run in runs
                    if run["resolution"] == resolution
                    and run["task"] == task
                    and run["delegate"] == delegate
                    and "result" in run
                ]
                if matching:
                    aggregates.append(
                        {
                            "resolution": resolution,
                            "task": task,
                            "delegate": delegate,
                            "successful_rounds": len(matching),
                            "timings": {
                                name: stats(
                                    [
                                        sample
                                        for result in matching
                                        for sample in result["timings"][name][
                                            "samples_ms"
                                        ]
                                    ]
                                )
                                for name in matching[0]["timings"]
                            },
                        }
                    )
    report = {
        "scope": "same installed wheel; identical moving fixture BGR frames converted to RGBA; VIDEO API; no capture/output/init; segmentation total is app OpenCV blur (31), no smoothing; face total is detection boundaries, no tracking/crop",
        "api_timing_note": "native API return; GPU readback may occur during output materialization, included in inference_with_boundaries and processing_total",
        "workload": {
            "source": args.source.name,
            "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
            "models_sha256": models,
            "motion": "nine horizontal translations -4 through +4 pixels, repeated",
            "warmup": args.warmup,
            "frames": args.frames,
            "rounds": args.rounds,
            "order": "CPU/GPU alternating by round, fresh worker each run",
        },
        "aggregates": aggregates,
        "runs": runs,
        "parity_first_last_frames": parity,
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved {args.output / 'summary.json'}")
    if any(run["exit_code"] != 0 for run in runs):
        raise SystemExit("One or more benchmark workers failed; inspect summary/logs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Interpreter containing the wheel to benchmark",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist/mediapipe-fair-benchmark"
    )
    parser.add_argument(
        "--source", type=Path, default=ROOT / "tests/fixtures/astronaut.png"
    )
    parser.add_argument("--resolutions", nargs="+", default=["640x480", "1920x1080"])
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--cpu-baseline",
        action="store_true",
        help="Also measure current app CPU SRGB input, outside the fair RGBA comparison",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--task", choices=("face", "segmentation"), help=argparse.SUPPRESS
    )
    parser.add_argument("--delegate", choices=("cpu", "gpu"), help=argparse.SUPPRESS)
    parser.add_argument(
        "--image-format",
        choices=("SRGB", "SRGBA"),
        default="SRGBA",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.worker:
        worker(args)
    else:
        orchestrate(args)


if __name__ == "__main__":
    main()
