"""Lightweight IoU tracker that assigns session-local face IDs (no identity recognition)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0
    # YuNet's 5 landmarks (x, y pairs): right eye, left eye, nose tip, right/left mouth corner.
    landmarks: tuple[float, ...] | None = None

    def iou(self, other: "Box") -> float:
        ix = max(0.0, min(self.x + self.w, other.x + other.w) - max(self.x, other.x))
        iy = max(0.0, min(self.y + self.h, other.y + other.h) - max(self.y, other.y))
        inter = ix * iy
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union > 0 else 0.0


@dataclass
class Track:
    face_id: int
    box: Box
    hits: int
    last_seen: float


class IoUTracker:
    """Greedy IoU matching between consecutive detection results.

    A track is *confirmed* after ``min_hits`` matched detections and dropped once it
    has not been matched for longer than ``timeout_s``.
    """

    def __init__(self, iou_threshold: float = 0.3, min_hits: int = 2, timeout_s: float = 1.0):
        self.iou_threshold = iou_threshold
        self.min_hits = min_hits
        self.timeout_s = timeout_s
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks.values())

    def confirmed(self) -> list[Track]:
        return [t for t in self._tracks.values() if t.hits >= self.min_hits]

    def update(self, boxes: list[Box], now: float) -> list[Track]:
        """Match ``boxes`` to existing tracks. Returns the tracks removed by timeout."""
        pairs = []
        for fid, track in self._tracks.items():
            for di, box in enumerate(boxes):
                iou = track.box.iou(box)
                if iou >= self.iou_threshold:
                    pairs.append((iou, fid, di))
        pairs.sort(reverse=True)

        matched_tracks: set[int] = set()
        matched_boxes: set[int] = set()
        for _, fid, di in pairs:
            if fid in matched_tracks or di in matched_boxes:
                continue
            track = self._tracks[fid]
            track.box = boxes[di]
            track.hits += 1
            track.last_seen = now
            matched_tracks.add(fid)
            matched_boxes.add(di)

        for di, box in enumerate(boxes):
            if di not in matched_boxes:
                self._tracks[self._next_id] = Track(self._next_id, box, hits=1, last_seen=now)
                self._next_id += 1

        removed = [t for t in self._tracks.values() if now - t.last_seen > self.timeout_s]
        for t in removed:
            del self._tracks[t.face_id]
        return removed
