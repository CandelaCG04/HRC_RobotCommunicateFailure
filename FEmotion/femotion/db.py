"""SQLite logging of sessions and emotion state transitions (not frames or raw predictions)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_events_session ON emotion_events(session_id, face_id);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventLogger:
    """Owns one SQLite connection; must be used from the thread that created it."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        # WAL + synchronous=NORMAL: commits no longer fsync, so logging cannot stall the
        # real-time worker (default mode measured 0.4-2.4 s per commit on a laptop disk).
        # Trade-off: the last transitions may be lost on power failure (not on app crash).
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self.session_id: int | None = None

    def start_session(self, camera_index: int | None, model_name: str | None) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, camera_index, model_name) VALUES (?, ?, ?)",
            (utc_now().isoformat(), camera_index, model_name),
        )
        self._conn.commit()
        self.session_id = cur.lastrowid
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
    ) -> None:
        if self.session_id is None:
            raise RuntimeError("start_session() must be called before logging")
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        self._conn.execute(
            "INSERT INTO emotion_events (session_id, face_id, timestamp, previous_emotion,"
            " emotion, confidence, duration_ms, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.session_id,
                face_id,
                timestamp.astimezone(timezone.utc).isoformat(),
                previous,
                emotion,
                confidence,
                duration_ms,
                kind,
            ),
        )
        self._conn.commit()

    def end_session(self) -> None:
        if self.session_id is None:
            return
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (utc_now().isoformat(), self.session_id),
        )
        self._conn.commit()
        self.session_id = None

    def close(self) -> None:
        self._conn.close()
