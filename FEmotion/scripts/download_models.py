"""Download the three pretrained files FEmotion needs into models/ (no training involved).

  face_detection_yunet_2023mar.onnx  OpenCV YuNet face detector (MIT)
  mbf_va_mtl.onnx                    EmotiEffLib emotion + valence/arousal model (Apache-2.0)
  face_landmarker.task               MediaPipe Face Landmarker, blendshapes (Apache-2.0)

Usage:  python scripts/download_models.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

FILES = {  # name: (url, expected size in bytes or None)
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx",
        232_589,
    ),
    "mbf_va_mtl.onnx": (
        "https://raw.githubusercontent.com/sb-ai-lab/EmotiEffLib/main/"
        "models/affectnet_emotions/onnx/mbf_va_mtl.onnx",
        8_251_681,
    ),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
        "float16/latest/face_landmarker.task",
        None,  # "latest" may change size
    ),
}


def download(name: str, url: str, size: int | None) -> None:
    path = MODELS_DIR / name
    if path.exists():
        print(f"[ok] {name} already present")
        return
    print(f"[..] downloading {name}")
    tmp = path.with_name(name + ".part")
    urllib.request.urlretrieve(url, tmp)
    if size is not None and tmp.stat().st_size != size:
        tmp.unlink()
        sys.exit(f"{name}: unexpected size (expected {size} bytes); not installed")
    tmp.rename(path)


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    for name, (url, size) in FILES.items():
        download(name, url, size)


if __name__ == "__main__":
    main()
