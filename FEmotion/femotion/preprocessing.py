"""Face alignment / cropping and conversion to the emotion model's input format."""
from __future__ import annotations

import cv2
import numpy as np

from femotion.tracking import Box


def _eyes(box: Box) -> tuple[np.ndarray, np.ndarray] | None:
    if not box.landmarks:
        return None
    a, b = np.array(box.landmarks[0:2]), np.array(box.landmarks[2:4])
    return (a, b) if a[0] <= b[0] else (b, a)  # (image-left eye, image-right eye)


def align_face(frame: np.ndarray, box: Box, margin: float, out_size: int) -> np.ndarray | None:
    """Square face crop (box enlarged by ``margin`` per side), rotated so the eyes are
    level and scaled to ``out_size``, in a single affine warp."""
    side = max(box.w, box.h) * (1 + 2 * margin)
    if side < 2:
        return None
    eyes = _eyes(box)
    angle = 0.0
    if eyes is not None:
        (lx, ly), (rx, ry) = eyes
        angle = float(np.degrees(np.arctan2(ry - ly, rx - lx)))
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    # Warp to at most 2x the output size, then INTER_AREA-downscale (warpAffine has no area filter).
    warp_size = out_size if side <= 2 * out_size else 2 * out_size
    m = cv2.getRotationMatrix2D((cx, cy), angle, warp_size / side)
    m[0, 2] += warp_size / 2 - cx
    m[1, 2] += warp_size / 2 - cy
    face = cv2.warpAffine(frame, m, (warp_size, warp_size), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
    if warp_size != out_size:
        face = cv2.resize(face, (out_size, out_size), interpolation=cv2.INTER_AREA)
    return face


def yaw_proxy(box: Box) -> float | None:
    """|nose offset from the eye midpoint, along the eye axis| / eye distance.
    About 0 for a frontal face, growing towards ~0.5 in profile."""
    eyes = _eyes(box)
    if eyes is None:
        return None
    a, b = eyes
    axis = b - a
    dist = float(np.hypot(*axis))
    if dist < 1e-6:
        return None
    nose = np.array(box.landmarks[4:6])
    return abs(float(np.dot(nose - (a + b) / 2, axis / dist))) / dist


def prepare_faces(faces_bgr: list[np.ndarray], size: int) -> np.ndarray:
    """BGR face crops -> float32 RGB [N, 3, size, size] scaled to [-1, 1]."""
    batch = np.stack([
        cv2.cvtColor(cv2.resize(f, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        for f in faces_bgr
    ]).astype(np.float32)
    return np.ascontiguousarray((batch / 127.5 - 1.0).transpose(0, 3, 1, 2))
