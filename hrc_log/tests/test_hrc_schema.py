import sqlite3

import pytest

from hrc_log import db


def test_connect_configures_and_creates_schema(db_path):
    conn = db.connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"sessions", "session_sources", "events", "emotion_events", "schema_version",
            "idx_events_timeline", "idx_events_trial"} <= names
    conn.close()
    # idempotent: a second connect neither fails nor duplicates the version row
    conn = db.connect(db_path)
    assert [tuple(r) for r in conn.execute("SELECT version FROM schema_version")] == [(db.SCHEMA_VERSION,)]


def test_constraints(db_path):
    conn = db.connect(db_path)
    base = ("INSERT INTO events (session_id, source, writer_id, seq, event_type, t_wall,"
            " t_session, clock_basis, t_iso) VALUES (?, ?, 'w', ?, 'x', 0, 0, 'mono', '')")
    with pytest.raises(sqlite3.IntegrityError):     # foreign key: unknown session
        conn.execute(base, ("nope", "game", 1))
    db.ensure_session(conn, "s", "cli")
    with pytest.raises(sqlite3.IntegrityError):     # source CHECK
        conn.execute(base, ("s", "other", 1))
    conn.execute(base, ("s", "game", 1))
    with pytest.raises(sqlite3.IntegrityError):     # UNIQUE (writer_id, seq)
        conn.execute(base, ("s", "game", 1))
    with pytest.raises(sqlite3.IntegrityError):     # payload must be JSON
        conn.execute(base.replace("t_iso)", "t_iso, payload)").replace("'')", "'', 'x{')"),
                     ("s", "game", 2))


def test_ensure_session_first_creator_wins(db_path):
    conn = db.connect(db_path)
    row, created = db.ensure_session(conn, "s1", "launcher", None, {"a": 1})
    assert created and row["status"] == "open" and row["t0_mono"] is not None
    row2, created2 = db.ensure_session(conn, "s1", "game", "P01")
    assert not created2 and row2["created_by"] == "launcher" and row2["t0_wall"] == row["t0_wall"]
    assert row2["participant"] == "P01"     # filled in by the joiner
    assert db.end_session(conn, "s1", "aborted")
    assert not db.end_session(conn, "s1", "completed")   # already closed
    assert db.get_session(conn, "s1")["status"] == "aborted"


def test_resolve_session_id_precedence(monkeypatch):
    monkeypatch.setenv("HRC_SESSION_ID", "from-env")
    assert db.resolve_session_id("from-cli") == "from-cli"
    assert db.resolve_session_id(None) == "from-env"
    monkeypatch.delenv("HRC_SESSION_ID")
    assert db.resolve_session_id(None) is None


def test_session_time_basis():
    session = {"t0_wall": 1000.0, "t0_mono": 50.0, "host": "h", "boot_id": "b"}
    assert db.session_time(session, 1010.5, 60.0, "h", "b") == (10.0, "mono")
    # other machine, other boot, or no monotonic time: fall back to wall clock
    assert db.session_time(session, 1010.5, 60.0, "other", "b") == (10.5, "wall")
    assert db.session_time(session, 1010.5, 60.0, "h", "rebooted") == (10.5, "wall")
    assert db.session_time(session, 1010.5, None, "h", "b") == (10.5, "wall")
    assert db.session_time(session, 1010.5, 60.0, "h", None) == (10.5, "wall")


def test_trial_ids():
    assert db.trial_ids("A", "tea", 2) == ("A:tea", "A:tea:2")
    assert db.trial_ids("A", "tea", "") == ("A:tea", None)
    assert db.trial_ids("", "tea", 1) == (None, None)
    assert db.trial_ids("A", "", 1) == (None, None)
