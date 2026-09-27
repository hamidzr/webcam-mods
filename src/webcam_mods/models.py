"""Download the MediaPipe task models on first use."""

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen

_MODELS = {
    "selfie_segmenter": (
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite",
        "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b",
    ),
    "yunet_face": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
}


def model_path(name: str) -> Path:
    """Return a verified local model, downloading it once when absent."""
    url, expected_hash = _MODELS[name]
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache_dir = cache_root / "webcam-mods" / "models"
    path = cache_dir / f"{name}{Path(url).suffix}"
    if (
        path.is_file()
        and hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
    ):
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with urlopen(url, timeout=30) as response:
            with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as temp:
                temp_path = Path(temp.name)
                content = response.read()
                if hashlib.sha256(content).hexdigest() != expected_hash:
                    raise ValueError(f"Invalid checksum for MediaPipe model {name}")
                temp.write(content)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return path


if __name__ == "__main__":
    for model_name in _MODELS:
        print(model_path(model_name))
