import csv
import hashlib
import sqlite3

from hrc_log import db
from hrc_log.__main__ import load_queries
from hrc_log.migrate import migrate_csv, migrate_femotion

# Copy of FEmotion's pre-unification schema (femotion.db.LEGACY_SCHEMA); not imported
# so these tests do not depend on the FEmotion package.
LEGACY_SCHEMA = """
CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
    ended_at TEXT, camera_index INTEGER, model_name TEXT);
CREATE TABLE emotion_events (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL,
    face_id INTEGER NOT NULL, timestamp TEXT NOT NULL, previous_emotion TEXT, emotion TEXT,
    confidence REAL, duration_ms INTEGER, kind TEXT NOT NULL DEFAULT 'emotion');
"""
CSV_FIELDS = ("t_unix", "t_iso", "t_session", "participant", "order", "block_index", "block_id",
              "condition", "actor", "action", "item", "attempt", "feedback_type", "detail")


def make_legacy_db(path):
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.execute("INSERT INTO sessions VALUES (1, '2026-10-11T10:00:00+00:00',"
                " '2026-10-11T10:05:00+00:00', 0, 'mbf_va_mtl')")
    con.executemany(
        "INSERT INTO emotion_events (session_id, face_id, timestamp, previous_emotion, emotion,"
        " confidence, duration_ms) VALUES (1, 1, ?, ?, ?, ?, ?)",
        [("2026-10-11T10:00:02+00:00", None, "neutral", 0.8, None),
         ("2026-10-11T10:00:07.500000+00:00", "neutral", "sad", 0.6, 5500)])
    con.commit()
    con.close()


def make_csv(path):
    rows = [
        ("1791745305.890", "x", "0.000", "P01", "3", "", "", "", "system", "session_start", "",
         "", "", "order=a/b/c"),
        ("1791745339.054", "x", "33.164", "P01", "3", "1", "A", "silent", "robot", "acknowledge",
         "tea", "1", "", "Okay"),
    ]
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_FIELDS)
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_migrate_femotion_backs_up_and_is_idempotent(tmp_path, db_path, read):
    legacy = tmp_path / "femotion.db"
    make_legacy_db(legacy)
    before = digest(legacy)
    conn = db.connect(db_path)

    result = migrate_femotion(conn, legacy)
    assert result["events"] == 2 and result["sessions"] == 1
    backup = sqlite3.connect(result["backup"])
    assert backup.execute("SELECT COUNT(*) FROM emotion_events").fetchone() == (2,)
    assert digest(legacy) == before                     # source untouched

    assert migrate_femotion(conn, legacy, backup=False)["events"] == 0   # re-run: no duplicates
    assert read("SELECT status, created_by FROM sessions") == [("legacy", "migration")]
    assert read("SELECT t_session, clock_basis, previous_emotion, emotion, duration_ms"
                " FROM events ORDER BY seq") == [
        (2.0, "wall", None, "neutral", None), (7.5, "wall", "neutral", "sad", 5500)]
    # the compatibility view looks like the legacy table
    assert read("SELECT face_id, emotion, kind FROM emotion_events ORDER BY id") == [
        (1, "neutral", "emotion"), (1, "sad", "emotion")]


def test_migrate_csv_keeps_columns(tmp_path, db_path, read):
    path = tmp_path / "P01_20261011_210145.csv"
    make_csv(path)
    conn = db.connect(db_path)
    assert migrate_csv(conn, path)["events"] == 2
    assert migrate_csv(conn, path)["events"] == 0
    assert read("SELECT participant, t0_wall FROM sessions") == [("P01", 1791745305.890)]
    rows = read('SELECT participant, "order", block_index, block_id, condition, actor, action,'
                " item, attempt, detail, task_id, trial_id, t_game, t_session FROM events ORDER BY seq")
    assert rows[0][:7] == ("P01", 3, None, None, None, "system", "session_start")
    assert rows[1][:12] == ("P01", 3, 1, "A", "silent", "robot", "acknowledge", "tea", 1, "Okay",
                            "A:tea", "A:tea:1")
    assert rows[1][12] == 33.164 and abs(rows[1][13] - 33.164) < 1e-3


def test_validation_queries_run(tmp_path, db_path):
    """Every query in queries.sql executes against a session with both sources."""
    conn = db.connect(db_path)
    db.ensure_session(conn, "s", "cli", t0_wall=100.0, t0_mono=10.0)
    conn.executemany(
        "INSERT INTO events (session_id, source, writer_id, seq, event_type, t_wall, t_mono,"
        " t_session, clock_basis, t_iso, block_id, actor, action, item, attempt, trial_id,"
        " emotion, face_id, confidence) VALUES ('s', ?, ?, ?, ?, ?, ?, ?, 'mono', '', ?, ?, ?, ?,"
        " ?, ?, ?, ?, ?)",
        [("femotion", "f", 1, "emotion_transition", 101, 11, 1, None, None, None, None, None, None,
          "neutral", 1, 0.8),
         ("game", "g", 1, "request_item", 102, 12, 2, "A", "human", "request_item", "tea", 1,
          "A:tea:1", None, None, None),
         ("femotion", "f", 2, "emotion_transition", 103, 13, 3, None, None, None, None, None, None,
          "sad", 1, 0.6),
         ("game", "g", 2, "task_failed", 104, 14, 4, "A", "robot", "task_failed", "tea", 1,
          "A:tea:1", None, None, None)])
    queries = load_queries()
    assert {"timeline", "emotion_before_game_event", "trial_summary", "counts", "integrity"} <= set(queries)
    for sql in queries.values():
        conn.execute(sql, {"session": "s"}).fetchall()
    before = conn.execute(queries["emotion_before_game_event"], {"session": "s"}).fetchall()
    assert [(r["action"], r["emotion"]) for r in before] == [("request_item", "neutral"),
                                                             ("task_failed", "sad")]
    trial, = conn.execute(queries["trial_summary"], {"session": "s"}).fetchall()
    assert (trial["robot_actions"], trial["emotion_at_start"], trial["emotions_during"]) == (
        "task_failed", "neutral", "sad")
