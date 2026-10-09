"""MediaPipe Face Landmarker: per-face blendshape scores for the frustration estimator.

Used only for expression features (no identity, no micro-expression claims). Runs in
VIDEO mode on the full frame; results are associated with tracked faces by IoU.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from femotion.config import MeshConfig
from femotion.tracking import Box, Track


class MeshModelNotFoundError(FileNotFoundError):
    pass


class FaceMesh:
    def __init__(self, cfg: MeshConfig):
        if not Path(cfg.model_path).is_file():
            raise MeshModelNotFoundError(
                f"MediaPipe face_landmarker.task not found at {cfg.model_path}. "
                "Run: python scripts/download_models.py"
            )
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self.match_iou = cfg.match_iou
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=cfg.model_path),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=cfg.max_faces,
            output_face_blendshapes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_ts = -1

    def process(self, frame_bgr: np.ndarray, t: float, tracks: list[Track]) -> dict[int, dict[str, float]]:
        """Blendshape scores per tracked ``face_id`` for this frame."""
        ts = max(int(t * 1000), self._last_ts + 1)  # VIDEO mode needs increasing timestamps
        self._last_ts = ts
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self._landmarker.detect_for_video(
            self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ts
        )
        h, w = frame_bgr.shape[:2]
        faces = []
        for landmarks, shapes in zip(result.face_landmarks, result.face_blendshapes):
            xs = [p.x * w for p in landmarks]
            ys = [p.y * h for p in landmarks]
            box = Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            faces.append((box, {c.category_name: float(c.score) for c in shapes}))
        return associate(faces, tracks, self.match_iou)

    def close(self) -> None:
        self._landmarker.close()


def associate(
    faces: list[tuple[Box, dict[str, float]]], tracks: list[Track], min_iou: float
) -> dict[int, dict[str, float]]:
    """Greedy one-to-one IoU matching of mesh faces to tracks."""
    pairs = sorted(
        ((box.iou(tr.box), fi, tr.face_id) for fi, (box, _) in enumerate(faces) for tr in tracks),
        reverse=True,
    )
    out: dict[int, dict[str, float]] = {}
    used: set[int] = set()
    for iou, fi, fid in pairs:
        if iou < min_iou:
            break
        if fi in used or fid in out:
            continue
        used.add(fi)
        out[fid] = faces[fi][1]
    return out
