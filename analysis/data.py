"""Load one session from the shared database and reshape it for analysis.

All times are ``t_session``: seconds since the shared session start, the
common timeline of game and emotion events (see hrc_log/schema.sql).
The database is opened read-only; analysis never writes to it.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hrc_log.__main__ import load_queries  # noqa: E402  (stdlib-only package)
from hrc_log.db import default_db_path  # noqa: E402

# Same order as FEmotion/femotion/emotions.py EMOTIONS (not importable here).
EMOTIONS = ("angry", "disgust", "fear", "happy", "sad", "surprise", "neutral")
FAILURE_FEEDBACK = ("silent", "explanation", "explanation_alternative")
CONDITIONS = ("tutorial",) + FAILURE_FEEDBACK
ACTORS = ("robot", "human", "system")


def connect_ro(db: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db) if db else default_db_path()
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def list_sessions(db=None) -> pd.DataFrame:
    with closing(connect_ro(db)) as conn:
        return pd.read_sql_query(
            "SELECT s.session_id, s.participant, s.status, s.started_iso,"
            " (SELECT COUNT(*) FROM events e WHERE e.session_id = s.session_id"
            "  AND e.source = 'game') AS game_events,"
            " (SELECT COUNT(*) FROM events e WHERE e.session_id = s.session_id"
            "  AND e.source = 'femotion') AS emotion_events"
            " FROM sessions s ORDER BY s.t0_wall", conn)


def resolve_session(db=None, session: str | None = None) -> str:
    """``session`` if given, else the most recent non-legacy session."""
    if session:
        return session
    with closing(connect_ro(db)) as conn:
        row = conn.execute("SELECT session_id FROM sessions WHERE status != 'legacy'"
                           " ORDER BY t0_wall DESC LIMIT 1").fetchone()
    if row is None:
        raise LookupError("no sessions in the database")
    return row[0]


def load_events(db=None, session: str | None = None) -> pd.DataFrame:
    session = resolve_session(db, session)
    with closing(connect_ro(db)) as conn:
        events = pd.read_sql_query(
            "SELECT * FROM events WHERE session_id = ? ORDER BY t_session, seq",
            conn, params=(session,))
    if events.empty:
        raise LookupError(f"session {session} has no events")
    return events


def session_end(events: pd.DataFrame) -> float:
    return float(events["t_session"].max())


def emotion_intervals(events: pd.DataFrame) -> pd.DataFrame:
    """One row per stable emotion state: face_id, emotion, start, end, confidence.

    A state lasts until the next transition of the same face. ``emotion=None``
    transitions (face lost) end a state without starting one. A state that is
    still open at the end lasts until the last event of the session.
    """
    cols = ["face_id", "emotion", "start", "end", "duration", "confidence"]
    em = events[(events["source"] == "femotion")
                & events["event_type"].eq("emotion_transition")]
    end_of_session = session_end(events)
    rows = []
    for face_id, face in em.groupby("face_id", sort=True):
        face = face.sort_values(["t_session", "seq"])
        starts = face["t_session"].tolist()
        for i, (_, tr) in enumerate(face.iterrows()):
            if pd.isna(tr["emotion"]):
                continue
            end = starts[i + 1] if i + 1 < len(starts) else end_of_session
            rows.append((int(face_id), tr["emotion"], tr["t_session"], end,
                         end - tr["t_session"], tr["confidence"]))
    return pd.DataFrame(rows, columns=cols)


def block_spans(events: pd.DataFrame) -> pd.DataFrame:
    """block_id, condition, start, end per played block. An unfinished block
    (aborted session) ends at the last event."""
    game = events[events["source"] == "game"]
    starts = game[game["action"] == "block_start"]
    ends = game[game["action"] == "block_end"]
    rows = []
    for i, (_, b) in enumerate(starts.iterrows()):
        next_start = starts["t_session"].iloc[i + 1] if i + 1 < len(starts) else None
        done = ends[(ends["block_index"] == b["block_index"]) & (ends["t_session"] >= b["t_session"])]
        if not done.empty:
            end, finished = done["t_session"].iloc[0], True
        else:
            end, finished = (next_start if next_start is not None else session_end(events)), False
        rows.append((b["block_index"], b["block_id"], b["condition"], b["t_session"], end, finished))
    return pd.DataFrame(rows, columns=["block_index", "block_id", "condition", "start", "end",
                                       "finished"])


def failure_moments(events: pd.DataFrame) -> pd.DataFrame:
    """Each failure message: the ``feedback_start`` of a failed attempt, when the
    participant learns that the robot failed. Adds the failure type from the
    trial's ``task_failed`` row."""
    game = events[events["source"] == "game"]
    fb = game[(game["action"] == "feedback_start")
              & game["feedback_type"].isin(FAILURE_FEEDBACK)]
    failed = game[game["action"] == "task_failed"].set_index("trial_id")["detail"]
    failed = failed[~failed.index.duplicated()]
    out = fb[["t_session", "block_id", "condition", "item", "attempt", "trial_id",
              "feedback_type", "detail"]].rename(columns={"detail": "message"}).copy()
    out["failure_type"] = out["trial_id"].map(failed)
    out["attempt"] = out["attempt"].astype("Int64")
    return out.reset_index(drop=True)


def emotion_at(intervals: pd.DataFrame, t: float) -> str | None:
    """Stable emotion (any face, latest onset) at time ``t``; None if no face."""
    hit = intervals[(intervals["start"] <= t) & (intervals["end"] > t)]
    return None if hit.empty else hit.sort_values("start")["emotion"].iloc[-1]


def emotion_share(intervals: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    """Seconds and fraction of observed time per emotion within each block."""
    rows = []
    for _, b in spans.iterrows():
        overlap = (intervals["end"].clip(upper=b["end"])
                   - intervals["start"].clip(lower=b["start"])).clip(lower=0)
        seconds = overlap.groupby(intervals["emotion"]).sum() if len(intervals) else pd.Series(dtype=float)
        observed = seconds.sum()
        for emotion in EMOTIONS:
            s = float(seconds.get(emotion, 0.0))
            rows.append((b["block_id"], b["condition"], emotion, s,
                         s / observed if observed > 0 else float("nan"),
                         b["end"] - b["start"]))
    return pd.DataFrame(rows, columns=["block_id", "condition", "emotion", "seconds", "fraction",
                                       "block_seconds"])


def trial_summary(db=None, session: str | None = None) -> pd.DataFrame:
    """Per trial robot actions and emotions (hrc_log/queries.sql 'trial_summary')."""
    session = resolve_session(db, session)
    with closing(connect_ro(db)) as conn:
        return pd.read_sql_query(load_queries()["trial_summary"], conn,
                                 params={"session": session})
