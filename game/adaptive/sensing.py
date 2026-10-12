"""Sense: read the participant's stable facial emotions from the shared database.

FEmotion runs as a separate process and logs emotion transitions to the
``events`` table under the same session id. The game only reads them
(read-only connection; with WAL, readers never block the writers). If the
database or FEmotion is unavailable, every window is simply empty, which the
model treats as "no face" (no evidence).
"""
import sqlite3
from pathlib import Path

QUERY = (
    "SELECT face_id, t_wall, emotion, confidence FROM events"
    " WHERE session_id = ? AND source = 'femotion' AND event_type = 'emotion_transition'"
    " AND t_wall <= ? ORDER BY t_wall, seq"
)


class EmotionReader:
    def __init__(self, db_path, session_id, timeout_ms=100):
        self.db_path = Path(db_path)
        self.session_id = session_id
        self._timeout_ms = timeout_ms
        self._conn = None

    def _connect(self):
        if self._conn is None and self.db_path.exists():
            self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True,
                                         timeout=self._timeout_ms / 1000)
        return self._conn

    def window(self, t_from, t_to):
        """Stable-emotion intervals ``(emotion, start, end, confidence)`` of
        the main face, clipped to [t_from, t_to] (wall-clock seconds)."""
        try:
            conn = self._connect()
            rows = conn.execute(QUERY, (self.session_id, t_to)).fetchall() if conn else []
        except sqlite3.Error:
            return []
        return clip_intervals(transitions_to_intervals(rows, t_to), t_from, t_to)

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def transitions_to_intervals(rows, t_end):
    """Rows ``(face_id, t, emotion, confidence)`` sorted by time -> per-face
    intervals. A state lasts until the face's next transition (or ``t_end``);
    ``emotion=None`` (face lost) starts no interval."""
    by_face = {}
    for face_id, t, emotion, confidence in rows:
        by_face.setdefault(face_id, []).append((t, emotion, confidence))
    intervals = {}
    for face_id, transitions in by_face.items():
        out = intervals.setdefault(face_id, [])
        for i, (t, emotion, confidence) in enumerate(transitions):
            end = transitions[i + 1][0] if i + 1 < len(transitions) else t_end
            if emotion is not None and end > t:
                out.append((emotion, t, end, confidence))
    return intervals


def clip_intervals(intervals_by_face, t_from, t_to):
    """Clip to the window and keep the face seen longest in it (the participant)."""
    best, best_cover = [], 0.0
    for intervals in intervals_by_face.values():
        clipped = [(e, max(s, t_from), min(end, t_to), c) for e, s, end, c in intervals
                   if end > t_from and s < t_to]
        cover = sum(end - s for _, s, end, _ in clipped)
        if cover > best_cover:
            best, best_cover = clipped, cover
    return best
