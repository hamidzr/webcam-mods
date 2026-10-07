"""Choose a MediaPipe delegate using isolated, bounded startup measurements."""

from functools import lru_cache
import hashlib
from importlib import metadata
from io import BytesIO
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Literal

from loguru import logger
import numpy as np

from webcam_mods import models
from webcam_mods.models import model_path
from webcam_mods.utils.video import Frame, validate_frame as _validate_frame

Task = Literal["face", "segmentation"]
Delegate = Literal["cpu", "gpu"]
_CACHE: dict[tuple[Task, tuple[int, ...]], Delegate] = {}
_WARMUP = 10
_SAMPLES = 30
_ROUNDS = 3
_TIMEOUT = 15
_CALIBRATION_TIMEOUT = _TIMEOUT * _ROUNDS * 2
_CACHE_LIMIT = 128
_CACHE_MAX_AGE = 30 * 24 * 60 * 60
_CACHE_MAX_BYTES = 128 * 1024


def _cache_path(identity: str | None = None) -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    directory = root / "webcam-mods"
    if identity is None:
        return directory / "delegate-calibration.json"
    namespace = hashlib.sha256(identity.encode()).hexdigest()
    return directory / "delegate-calibration" / f"{namespace}.json"


@lru_cache(maxsize=1)
def _cache_identity() -> str:
    """Invalidate measurements when hardware, OS, models, or native wheels change."""
    identity = [platform.machine(), platform.version(), sys.version]
    try:
        hardware = (
            subprocess.run(
                ["/usr/sbin/sysctl", "-n", "hw.model", "machdep.cpu.brand_string"],
                capture_output=True,
                check=True,
                timeout=2,
            )
            .stdout.decode()
            .strip()
        )
        identity.append(hardware)
    except OSError, subprocess.SubprocessError, UnicodeError:
        identity.append(platform.processor())
    for package in ("mediapipe", "numpy", "opencv-contrib-python"):
        distribution = metadata.distribution(package)
        identity.extend([package, distribution.version])
        # RECORD fingerprints distinguish patched native wheels with equal versions
        identity.append(distribution.read_text("RECORD") or "")
    for source in (Path(__file__), Path(models.__file__)):
        with source.open("rb") as stream:
            identity.append(hashlib.file_digest(stream, "sha256").hexdigest())
    return hashlib.sha256("\n".join(identity).encode()).hexdigest()


def _disk_key(task: Task, shape: tuple[int, ...]) -> str:
    return f"{task}:{','.join(map(str, shape))}"


def _read_cache(identity: str) -> dict[str, dict[str, Any]]:
    # retain compatible legacy measurements while installations own separate files
    entries = _read_cache_file(_cache_path(identity), identity)
    return entries or _read_cache_file(_cache_path(), identity)


def _read_cache_file(path: Path, identity: str) -> dict[str, dict[str, Any]]:
    try:
        # bound parsing even if a cache file was damaged or replaced
        with path.open("rb") as stream:
            payload = stream.read(_CACHE_MAX_BYTES + 1)
        if len(payload) > _CACHE_MAX_BYTES:
            return {}
        document = json.loads(payload)
        if not isinstance(document, dict) or document.get("identity") != identity:
            return {}
        entries = document.get("entries")
        if not isinstance(entries, dict) or len(entries) > _CACHE_LIMIT:
            return {}
        now = time.time()
        valid: dict[str, dict[str, Any]] = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            timestamp = entry.get("timestamp")
            if (
                entry.get("delegate") in ("cpu", "gpu")
                and isinstance(timestamp, (int, float))
                and not isinstance(timestamp, bool)
                and math.isfinite(timestamp)
                and 0 <= now - timestamp <= _CACHE_MAX_AGE
            ):
                valid[key] = entry
        return valid
    except OSError, ValueError, TypeError:
        return {}


def _write_cache(identity: str, key: str, delegate: Delegate) -> None:
    path = _cache_path(identity)
    temporary: Path | None = None
    try:
        entries = _read_cache(identity)
        entries[key] = {"delegate": delegate, "timestamp": time.time()}
        entries = dict(
            sorted(entries.items(), key=lambda item: item[1]["timestamp"])[
                -_CACHE_LIMIT:
            ]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False, encoding="utf-8"
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"identity": identity, "entries": entries}, stream)
        os.replace(temporary, path)
    except OSError, ValueError, TypeError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _probe(task: Task, delegate: Delegate, payload: bytes) -> float:
    result = subprocess.run(
        [sys.executable, "-m", "webcam_mods.mediapipe_delegate", task, delegate],
        input=payload,
        capture_output=True,
        timeout=_TIMEOUT,
        check=True,
    )
    return _valid_timing(json.loads(result.stdout)["median_ms"])


def _valid_timing(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("invalid calibration result")
    median = float(value)
    if not math.isfinite(median) or median <= 0:
        raise ValueError("invalid calibration timing")
    return median


def _calibrate(task: Task, frame: Frame) -> tuple[list[float], list[float]]:
    """Keep all warmed comparisons in one isolated, time-bounded process."""
    stream = BytesIO()
    np.save(stream, frame, allow_pickle=False)
    result = subprocess.run(
        [sys.executable, "-m", "webcam_mods.mediapipe_delegate", task, "calibrate"],
        input=stream.getvalue(),
        capture_output=True,
        # preserve the former six workers' total budget for large input shapes
        timeout=_CALIBRATION_TIMEOUT,
        check=True,
    )
    document = json.loads(result.stdout)
    if not isinstance(document, dict):
        raise ValueError("invalid calibration result")
    measurements = []
    for delegate in ("cpu", "gpu"):
        values = document.get(delegate)
        if not isinstance(values, list) or len(values) != _ROUNDS:
            raise ValueError("invalid calibration rounds")
        measurements.append([_valid_timing(value) for value in values])
    return measurements[0], measurements[1]


def _measure_rounds(task: Task, frame: Frame) -> dict[str, list[float]]:
    measurements: dict[str, list[float]] = {"cpu": [], "gpu": []}
    for round_index in range(_ROUNDS):
        order: tuple[Delegate, Delegate] = (
            ("cpu", "gpu") if round_index % 2 == 0 else ("gpu", "cpu")
        )
        for delegate in order:
            measurements[delegate].append(_measure(task, delegate, frame))
    return measurements


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
    identity: str | None = None
    disk_key = _disk_key(task, key[1])
    try:
        identity = _cache_identity()
        cached = _read_cache(identity).get(disk_key)
        if cached is not None:
            selected_cached: Delegate = "gpu" if cached["delegate"] == "gpu" else "cpu"
            _remember(key, selected_cached)
            return selected_cached
    except OSError, ValueError, metadata.PackageNotFoundError:
        # cache availability must never prevent inference or fresh calibration
        pass
    selected: Delegate = "cpu"
    succeeded = False
    try:
        cpu, gpu = _calibrate(task, frame)
        if all(g < c * 0.95 for c, g in zip(cpu, gpu)):
            selected = "gpu"
        succeeded = True
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
    _remember(key, selected)
    # transient probe failure should not poison future launches
    if succeeded and identity is not None:
        _write_cache(identity, disk_key, selected)
    return selected


def _remember(key: tuple[Task, tuple[int, ...]], delegate: Delegate) -> None:
    _CACHE[key] = delegate
    if len(_CACHE) > _CACHE_LIMIT:
        del _CACHE[next(iter(_CACHE))]


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
    if sys.argv[2] not in ("cpu", "gpu", "calibrate"):
        raise ValueError("expected cpu, gpu, or calibrate delegate")
    task: Task = "face" if sys.argv[1] == "face" else "segmentation"
    delegate: Delegate = "cpu" if sys.argv[2] == "cpu" else "gpu"
    frame = np.load(BytesIO(sys.stdin.buffer.read()), allow_pickle=False)
    _validate_frame(frame)
    print(
        json.dumps(
            _measure_rounds(task, frame)
            if sys.argv[2] == "calibrate"
            else {"median_ms": _measure(task, delegate, frame)}
        )
    )


if __name__ == "__main__":
    _main()
