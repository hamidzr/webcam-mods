"""Choose a MediaPipe delegate using isolated, bounded startup measurements."""

from io import BytesIO
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from typing import Any, Literal

from loguru import logger
import numpy as np

from webcam_mods.models import model_path
from webcam_mods.utils.video import Frame

Task = Literal["face", "segmentation"]
Delegate = Literal["cpu", "gpu"]
_CACHE: dict[tuple[Task, tuple[int, ...]], Delegate] = {}
_WARMUP = 10
_SAMPLES = 30
_ROUNDS = 3
_TIMEOUT = 15


def _validate_frame(frame: Frame) -> None:
    if (
        frame.dtype != np.uint8
        or frame.ndim != 3
        or frame.shape[2] != 3
        or frame.shape[0] == 0
        or frame.shape[1] == 0
    ):
        raise ValueError("expected a nonempty uint8 BGR frame")


def _probe(task: Task, delegate: Delegate, payload: bytes) -> float:
    result = subprocess.run(
        [sys.executable, "-m", "webcam_mods.mediapipe_delegate", task, delegate],
        input=payload,
        capture_output=True,
        timeout=_TIMEOUT,
        check=True,
    )
    value = json.loads(result.stdout)["median_ms"]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("invalid calibration result")
    median = float(value)
    if not math.isfinite(median) or median <= 0:
        raise ValueError("invalid calibration timing")
    return median


def select_delegate(task: Task, frame: Frame) -> Delegate:
    """Use GPU only when it consistently beats CPU on this input and shape."""
    if task not in ("face", "segmentation"):
        raise ValueError(f"unknown MediaPipe task: {task}")
    _validate_frame(frame)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return "cpu"
    key = (task, tuple(frame.shape))
    if key in _CACHE:
        return _CACHE[key]
    stream = BytesIO()
    np.save(stream, frame, allow_pickle=False)
    payload = stream.getvalue()
    cpu: list[float] = []
    gpu: list[float] = []
    selected: Delegate = "cpu"
    try:
        for round_index in range(_ROUNDS):
            order: tuple[Delegate, Delegate] = (
                ("cpu", "gpu") if round_index % 2 == 0 else ("gpu", "cpu")
            )
            measured = {delegate: _probe(task, delegate, payload) for delegate in order}
            cpu.append(measured["cpu"])
            gpu.append(measured["gpu"])
        if all(g < c * 0.95 for c, g in zip(cpu, gpu)):
            selected = "gpu"
        logger.info(
            "MediaPipe {} selected {}: CPU {:.2f} ms, GPU {:.2f} ms "
            "(three warmed median comparisons)",
            task,
            selected,
            statistics.median(cpu),
            statistics.median(gpu),
        )
    except Exception as error:
        # native crashes stay in workers; cache fallback to avoid repeated probes
        logger.warning(
            "MediaPipe {} calibration failed ({}); using CPU",
            task,
            type(error).__name__,
        )
    _CACHE[key] = selected
    return selected


def _measure(task: Task, delegate: Delegate, frame: Frame) -> float:
    import cv2
    import mediapipe as mp

    base = mp.tasks.BaseOptions(
        model_asset_path=str(
            model_path(
                "blaze_face_full_range" if task == "face" else "selfie_segmenter"
            )
        ),
        delegate=(
            mp.tasks.BaseOptions.Delegate.GPU
            if delegate == "gpu"
            else mp.tasks.BaseOptions.Delegate.CPU
        ),
    )
    handle: Any
    if task == "face":
        handle = mp.tasks.vision.FaceDetector.create_from_options(
            mp.tasks.vision.FaceDetectorOptions(
                base_options=base,
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                min_detection_confidence=0.6,
            )
        )
    else:
        handle = mp.tasks.vision.ImageSegmenter.create_from_options(
            mp.tasks.vision.ImageSegmenterOptions(
                base_options=base,
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                output_confidence_masks=True,
            )
        )
    elapsed: list[float] = []
    timestamp = 0
    try:
        for index in range(_WARMUP + _SAMPLES):
            start = time.perf_counter_ns()
            image = mp.Image(
                image_format=mp.ImageFormat.SRGBA,
                data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)),
            )
            timestamp = max(time.monotonic_ns() // 1_000_000, timestamp + 1)
            if task == "face":
                handle.detect_for_video(image, timestamp)
            else:
                result = handle.segment_for_video(image, timestamp)
                np.asarray(
                    result.confidence_masks[0].numpy_view(), dtype=np.float32
                ).squeeze(axis=-1).copy()
            duration = (time.perf_counter_ns() - start) / 1_000_000
            if index >= _WARMUP:
                elapsed.append(duration)
    finally:
        handle.close()
    return statistics.median(elapsed)


def _main() -> None:
    # aborting native libraries must not leave large core dumps
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except ImportError, OSError, ValueError:
        pass
    if len(sys.argv) != 3 or sys.argv[1] not in ("face", "segmentation"):
        raise ValueError("expected task and delegate")
    if sys.argv[2] not in ("cpu", "gpu"):
        raise ValueError("expected cpu or gpu delegate")
    task: Task = "face" if sys.argv[1] == "face" else "segmentation"
    delegate: Delegate = "cpu" if sys.argv[2] == "cpu" else "gpu"
    frame = np.load(BytesIO(sys.stdin.buffer.read()), allow_pickle=False)
    _validate_frame(frame)
    print(json.dumps({"median_ms": _measure(task, delegate, frame)}))


if __name__ == "__main__":
    _main()
