"""Non-destructive import of pre-unification data into the shared database.

* FEmotion's ``femotion.db`` (tables ``sessions`` and ``emotion_events``) is
  first copied to ``femotion.db.bak-<stamp>`` with SQLite's backup API, then
  read-only.
* Game CSV logs (``logs/*.csv``) are only read.

Source files are never modified. Imported sessions get ``status='legacy'`` and
``clock_basis='wall'`` (no monotonic times were recorded). Re-running is safe:
rows are keyed by (writer_id, seq) = (legacy file, legacy row number).
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from hrc_log import db
from hrc_log.writer import INSERT_SQL, event_row


def backup_sqlite(path: Path) -> Path:
    """Consistent copy (includes WAL contents) next to the original."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(f"{path.name}.bak-{stamp}")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def _insert(conn: sqlite3.Connection, rows: list) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = conn.total_changes
        conn.executemany(INSERT_SQL, rows)
        inserted = conn.total_changes - before
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return inserted


def _legacy_session(conn, session_id, participant, t0_wall, meta):
    session, _ = db.ensure_session(conn, session_id, "migration", participant, meta,
                                   t0_wall=t0_wall, t0_mono=None, host=None, boot_id=None,
                                   status="legacy")
    return session


def migrate_femotion(conn: sqlite3.Connection, path: str | Path, backup: bool = True) -> dict:
    path = Path(path).resolve()
    backup_path = backup_sqlite(path) if backup else None
    legacy = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    legacy.row_factory = sqlite3.Row
    writer_id = f"legacy:{path}"
    sessions = {}
    for row in legacy.execute("SELECT * FROM sessions ORDER BY id"):
        meta = {"legacy_file": str(path), "legacy_session_id": row["id"],
                "camera_index": row["camera_index"], "model_name": row["model_name"],
                "ended_at": row["ended_at"]}
        sessions[row["id"]] = _legacy_session(
            conn, f"legacy-femotion:{path.stem}:{row['id']}", None,
            datetime.fromisoformat(row["started_at"]).timestamp(), meta)
    rows = []
    for ev in legacy.execute("SELECT * FROM emotion_events ORDER BY id"):
        session = sessions[ev["session_id"]]
        kind = ev["kind"] or "emotion"
        record = {
            "session_id": session["session_id"], "source": "femotion",
            "writer_id": writer_id, "seq": ev["id"], "event_type": f"{kind}_transition",
            "t_wall": datetime.fromisoformat(ev["timestamp"]).timestamp(), "t_mono": None,
            "face_id": ev["face_id"], "emotion": ev["emotion"],
            "previous_emotion": ev["previous_emotion"], "confidence": ev["confidence"],
            "duration_ms": ev["duration_ms"],
        }
        rows.append(event_row(record, session))
    legacy.close()
    return {"file": str(path), "backup": str(backup_path) if backup_path else None,
            "sessions": len(sessions), "events": _insert(conn, rows)}


def _int(value):
    return int(value) if value not in (None, "") else None


def migrate_csv(conn: sqlite3.Connection, path: str | Path) -> dict:
    path = Path(path).resolve()
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return {"file": str(path), "sessions": 0, "events": 0}
    first = rows[0]
    t0_wall = float(first["t_unix"]) - float(first["t_session"] or 0)   # game start
    session = _legacy_session(conn, f"legacy-game:{path.stem}", first["participant"] or None,
                              t0_wall, {"legacy_file": str(path)})
    out = []
    for seq, row in enumerate(rows, start=1):
        task_id, trial_id = db.trial_ids(row["block_id"], row["item"], row["attempt"])
        record = {
            "session_id": session["session_id"], "source": "game",
            "writer_id": f"legacy:{path}", "seq": seq, "event_type": row["action"],
            "t_wall": float(row["t_unix"]), "t_mono": None,
            "participant": row["participant"] or None, "order": _int(row["order"]),
            "block_index": _int(row["block_index"]), "block_id": row["block_id"] or None,
            "condition": row["condition"] or None, "actor": row["actor"] or None,
            "action": row["action"] or None, "item": row["item"] or None,
            "attempt": _int(row["attempt"]), "feedback_type": row["feedback_type"] or None,
            "detail": row["detail"] or None, "task_id": task_id, "trial_id": trial_id,
            "t_game": float(row["t_session"]) if row["t_session"] else None,
        }
        out.append(event_row(record, session))
    return {"file": str(path), "sessions": 1, "events": _insert(conn, out)}
