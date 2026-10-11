import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time

import pytest

from hrc_log import EventWriter, db
from hrc_log.writer import replay_spool

from conftest import ROOT


def make_writer(db_path, tmp_path, **kw):
    kw.setdefault("spool_dir", tmp_path / "spool")
    return EventWriter(db_path, kw.pop("session_id", None), kw.pop("source", "game"), **kw)


def test_observation_time_survives_batching(db_path, tmp_path, read):
    w = make_writer(db_path, tmp_path, flush_interval=0.5)
    t0_wall, t0_mono = w._t0
    # observed 5 s after session start, enqueued later, inserted later still
    w.enqueue("observed", t_wall=t0_wall + 5.0, t_mono=t0_mono + 5.0)
    w.enqueue("now")
    time.sleep(0.1)
    w.close()
    rows = read("SELECT event_type, t_wall, t_mono, t_session, clock_basis, seq FROM events ORDER BY seq")
    assert rows[0][:5] == ("observed", t0_wall + 5.0, t0_mono + 5.0, pytest.approx(5.0), "mono")
    assert rows[1][4] == "mono" and 0 <= rows[1][3] < 1.0
    assert [r[5] for r in rows] == [1, 2]
    # t_session agrees with the wall clock (same machine)
    for _, t_wall, _, t_session, _, _ in rows:
        assert abs((t_wall - t0_wall) - t_session) < 0.05


def test_wall_time_derived_from_monotonic(db_path, tmp_path, read):
    w = make_writer(db_path, tmp_path)
    onset = time.monotonic() - 2.0          # e.g. a camera frame captured 2 s ago
    w.enqueue("emotion_transition", t_mono=onset)
    w.close()
    (t_wall, t_mono), = read("SELECT t_wall, t_mono FROM events")
    assert t_mono == onset and abs(t_wall - (time.time() - 2.0)) < 0.1


def test_second_writer_joins_and_only_creator_ends_session(db_path, tmp_path, read):
    a = make_writer(db_path, tmp_path, source="game", participant="P01")
    a.ready.wait(5)
    b = make_writer(db_path, tmp_path, source="femotion", session_id=a.session_id)
    b.ready.wait(5)
    assert a.created and not b.created
    b.enqueue("emotion_transition", emotion="happy", face_id=1)
    b.close("aborted")                      # FEmotion stops early
    assert read("SELECT status FROM sessions") == [("open",)]
    a.enqueue("request_item", actor="human", item="tea")
    a.close("completed")
    assert read("SELECT status, participant FROM sessions") == [("completed", "P01")]
    assert read("SELECT source, left_wall IS NOT NULL FROM session_sources ORDER BY source") == [
        ("femotion", 1), ("game", 1)]
    assert read("SELECT source, COUNT(*) FROM events GROUP BY source ORDER BY source") == [
        ("femotion", 1), ("game", 1)]


def test_session_from_environment(db_path, tmp_path, monkeypatch, read):
    monkeypatch.setenv("HRC_SESSION_ID", "env-session")
    w = make_writer(db_path, tmp_path)
    w.close()
    assert w.session_id == "env-session"
    assert read("SELECT session_id FROM sessions") == [("env-session",)]


CHILD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    from hrc_log import EventWriter
    db_path, session, source, n = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
    w = EventWriter(db_path, session, source, flush_interval=0.01, batch_size=20)
    for i in range(n):
        w.enqueue("tick", detail=str(i))
        if i % 50 == 0:
            time.sleep(0.005)
    w.close()
    print(w.spooled)
""")


def test_two_processes_write_concurrently(db_path, tmp_path, read):
    conn = db.connect(db_path)
    db.ensure_session(conn, "shared", "launcher")
    n = 1500
    procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), str(db_path), "shared", src,
                               str(n)], stdout=subprocess.PIPE, text=True, cwd=tmp_path)
             for src in ("game", "femotion")]
    seen = 0
    while any(p.poll() is None for p in procs):     # concurrent reader
        seen = max(seen, conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        time.sleep(0.01)
    outs = [p.communicate()[0].strip() for p in procs]
    assert [p.returncode for p in procs] == [0, 0]
    assert outs == ["0", "0"]                       # nothing spooled: no lock failures
    assert read("SELECT source, COUNT(*), MIN(seq), MAX(seq) FROM events GROUP BY source"
                " ORDER BY source") == [("femotion", n, 1, n), ("game", n, 1, n)]
    assert not list(tmp_path.glob("**/*.jsonl"))


def test_locked_database_spools_then_replays(db_path, tmp_path, read):
    w = make_writer(db_path, tmp_path, busy_timeout_ms=50, max_retries=2)
    assert w.ready.wait(5)
    blocker = sqlite3.connect(db_path, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")              # the other process hogs the write lock
    start = time.perf_counter()
    for i in range(3):
        w.enqueue("request_item", actor="human", item=f"x{i}", attempt=1)
    assert time.perf_counter() - start < 0.05       # the caller never waits for the lock
    w.close()
    blocker.execute("ROLLBACK")
    blocker.close()

    assert w.spooled == 3 and w.spool_path.exists()
    assert read("SELECT COUNT(*) FROM events") == [(0,)]
    backup = tmp_path / "copy.jsonl"
    shutil.copy(w.spool_path, backup)
    conn = db.connect(db_path)
    assert replay_spool(conn, w.spool_path) == 3
    assert not w.spool_path.exists()                # renamed to *.replayed
    assert replay_spool(conn, backup) == 0          # idempotent
    assert read("SELECT item, seq, clock_basis FROM events ORDER BY seq") == [
        ("x0", 1, "mono"), ("x1", 2, "mono"), ("x2", 3, "mono")]


def test_unreachable_database_spools_and_replay_recreates_session(tmp_path, read, db_path):
    bad = tmp_path / "is_a_dir"
    bad.mkdir()
    w = EventWriter(bad, "lost-session", "femotion", spool_dir=tmp_path / "spool")
    w.enqueue("emotion_transition", emotion="sad", face_id=2)
    w.close()
    assert w.spooled == 1
    conn = db.connect(db_path)
    assert replay_spool(conn, w.spool_path) == 1
    assert read("SELECT session_id, created_by FROM sessions") == [("lost-session", "femotion")]
    assert read("SELECT emotion, clock_basis FROM events") == [("sad", "mono")]


def test_events_after_close_are_spooled_not_lost(db_path, tmp_path):
    w = make_writer(db_path, tmp_path)
    w.close()
    w.enqueue("late")
    assert w.spooled == 1


def test_unknown_field_is_rejected(db_path, tmp_path):
    w = make_writer(db_path, tmp_path)
    with pytest.raises(KeyError):
        w.enqueue("x", not_a_column=1)
    w.close()
