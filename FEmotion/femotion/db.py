"""Logging of emotion state transitions (not frames or raw predictions) to the shared
SQLite database (``hrc_log`` at the repository root, table ``events``)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import hrc_log
except ImportError:  # run from FEmotion/: the shared package lives in the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import hrc_log

# Pre-unification schema of femotion.db; kept for reference and for
# ``python -m hrc_log migrate``, which imports such files into the shared database.
LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    camera_index INTEGER,
    model_name   TEXT
);
CREATE TABLE IF NOT EXISTS emotion_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER NOT NULL REFERENCES sessions(id),
    face_id          INTEGER NOT NULL,
    timestamp        TEXT NOT NULL,
    previous_emotion TEXT,
    emotion          TEXT,
    confidence       REAL,
    duration_ms      INTEGER,
    kind             TEXT NOT NULL DEFAULT 'emotion'  -- 'emotion' | 'frustration'
);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventLogger:
    """Writes transitions as ``source='femotion'`` events. Inserts happen on a background
    thread (``hrc_log.EventWriter``), so logging never stalls the real-time worker.

    ``session_id`` joins an existing session (e.g. the game's); None uses
    ``$HRC_SESSION_ID`` or creates a new session.
    """

    def __init__(self, path: str | None = None, session_id: str | None = None):
        self._path = path
        self._requested_session = session_id
        self._writer: hrc_log.EventWriter | None = None
        self.session_id: str | None = None

    def start_session(self, camera_index: int | None, model_name: str | None) -> str:
        self._writer = hrc_log.EventWriter(
            self._path, self._requested_session, "femotion",
            source_meta={"camera_index": camera_index, "model_name": model_name},
        )
        self.session_id = self._writer.session_id
        return self.session_id

    def log_transition(
        self,
        face_id: int,
        timestamp: datetime,
        previous: str | None,
        emotion: str | None,
        confidence: float | None,
        duration_ms: int | None,
        kind: str = "emotion",
        t_mono: float | None = None,
    ) -> None:
        """``timestamp``: wall-clock onset; ``t_mono``: the same instant on
        ``time.monotonic()`` (preferred for the session timeline)."""
        if self._writer is None:
            raise RuntimeError("start_session() must be called before logging")
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        self._writer.enqueue(
            f"{kind}_transition", t_wall=timestamp.timestamp(), t_mono=t_mono,
            face_id=face_id, previous_emotion=previous, emotion=emotion,
            confidence=confidence, duration_ms=duration_ms,
        )

    def end_session(self) -> None:
        if self._writer is not None:
            self._writer.close("completed")
            self._writer = None

    def close(self) -> None:
        self.end_session()
