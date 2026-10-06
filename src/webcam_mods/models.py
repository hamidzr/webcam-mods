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
    "blaze_face_full_range": (
        "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/1/blaze_face_full_range.tflite",
        "3698b18f063835bc609069ef052228fbe86d9c9a6dc8dcb7c7c2d69aed2b181b",
    ),
}


def model_path(name: str) -> Path:
    """Return a verified local model, downloading it once when absent."""
    url, expected_hash = _MODELS[name]
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache_dir = cache_root / "webcam-mods" / "models"
    path = cache_dir / f"{name}{Path(url).suffix}"
    if path.is_file():
        with path.open("rb") as cached:
            if hashlib.file_digest(cached, "sha256").hexdigest() == expected_hash:
                return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with urlopen(url, timeout=30) as response:
            with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as temp:
                temp_path = Path(temp.name)
                digest = hashlib.sha256()
                while content := response.read(64 * 1024):
                    digest.update(content)
                    temp.write(content)
                if digest.hexdigest() != expected_hash:
                    raise ValueError(f"Invalid checksum for MediaPipe model {name}")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return path


if __name__ == "__main__":
    for model_name in _MODELS:
        print(model_path(model_name))
