"""Face detection with OpenCV's YuNet (ONNX)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from femotion.config import DetectorConfig
from femotion.tracking import Box


class DetectorModelNotFoundError(FileNotFoundError):
    pass


class FaceDetector:
    def __init__(self, cfg: DetectorConfig):
        if not Path(cfg.model_path).is_file():
            raise DetectorModelNotFoundError(
                f"YuNet face detector not found at {cfg.model_path}. "
                "Run: python scripts/download_models.py"
            )
        self.min_face_size = cfg.min_face_size
        self._size: tuple[int, int] = (320, 320)
        self._det = cv2.FaceDetectorYN.create(
            cfg.model_path, "", self._size, cfg.score_threshold, cfg.nms_threshold, 50
        )

    def detect(self, frame: np.ndarray) -> list[Box]:
        h, w = frame.shape[:2]
        if (w, h) != self._size:
            self._size = (w, h)
            self._det.setInputSize(self._size)
        _, faces = self._det.detect(frame)
        if faces is None:
            return []
        boxes = []
        for f in faces:
            x, y, bw, bh = (float(v) for v in f[:4])
            x0, y0 = max(0.0, x), max(0.0, y)
            bw, bh = min(w, x + bw) - x0, min(h, y + bh) - y0
            if min(bw, bh) >= self.min_face_size:
                landmarks = tuple(float(v) for v in f[4:14])
                boxes.append(Box(x0, y0, bw, bh, float(f[-1]), landmarks))
        return boxes
