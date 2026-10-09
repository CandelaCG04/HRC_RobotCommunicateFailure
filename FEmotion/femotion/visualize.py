"""Optional OpenCV debug overlay. Draws on a copy; never touches the pipeline's frames."""
from __future__ import annotations

import cv2
import numpy as np

from femotion.pipeline import Snapshot

_GREEN, _GREY, _WHITE, _RED = (60, 200, 60), (160, 160, 160), (255, 255, 255), (40, 40, 230)


def draw_overlay(image: np.ndarray, snapshot: Snapshot, metrics_text: str) -> np.ndarray:
    out = image.copy()
    for face in snapshot.faces:
        b = face.box
        color = _GREEN if face.emotion else _GREY
        p0, p1 = (int(b.x), int(b.y)), (int(b.x + b.w), int(b.y + b.h))
        cv2.rectangle(out, p0, p1, color, 2)
        label = f"#{face.face_id} {face.emotion or '...'}"
        if face.confidence is not None:
            label += f" {face.confidence:.2f}"
        cv2.putText(out, label, (p0[0], max(15, p0[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if face.frustration is not None:  # frustration bar under the box
            bar_color = _RED if face.frustrated else _GREY
            x0, y0, width = p0[0], p1[1] + 6, p1[0] - p0[0]
            cv2.rectangle(out, (x0, y0), (x0 + width, y0 + 8), _GREY, 1)
            cv2.rectangle(out, (x0, y0), (x0 + int(width * face.frustration), y0 + 8), bar_color, -1)
            text = f"frustration {face.frustration:.2f}" + ("  FRUSTRATED" if face.frustrated else "")
            cv2.putText(out, text, (x0, y0 + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, bar_color, 1)
    cv2.putText(out, metrics_text, (8, out.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, _WHITE, 1)
    return out
