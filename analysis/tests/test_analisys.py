"""Synthetic session -> reshaping functions and both CLIs."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis import data, plot_session, summary  # noqa: E402
from hrc_log import db as hdb  # noqa: E402

COLS = ("session_id", "source", "writer_id", "seq", "event_type", "t_wall", "t_mono", "t_session",
        "clock_basis", "t_iso", "participant", "block_index", "block_id", "condition", "actor",
        "action", "item", "attempt", "feedback_type", "detail", "trial_id", "face_id",
        "previous_emotion", "emotion", "confidence")


def game(seq, t, action, actor="system", block=None, cond=None, idx=None, item=None,
         attempt=None, fb=None, detail=None):
    trial = f"{block}:{item}:{attempt}" if item and attempt else None
    return ("s", "game", "g", seq, action, 1000 + t, 50 + t, t, "mono", "", "P01", idx, block,
            cond, actor, action, item, attempt, fb, detail, trial, None, None, None, None)


def emo(seq, t, prev, emotion, face=1, conf=0.7):
    return ("s", "femotion", f"f{face}", seq, "emotion_transition", 1000 + t, 50 + t, t, "mono",
            "", None, None, None, None, None, None, None, None, None, None, None, face, prev,
            emotion, conf)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "hrc.db"
    conn = hdb.connect(path)
    hdb.ensure_session(conn, "s", "cli", "P01", t0_wall=1000.0, t0_mono=50.0)
    rows = [
        game(1, 0.0, "session_start"),
        game(2, 1.0, "block_start", block="tutorial", cond="tutorial", idx=0),
        game(3, 2.0, "feedback_start", "robot", "tutorial", "tutorial", 0, "tea", 1, "success"),
        game(4, 10.0, "block_end", block="tutorial", cond="tutorial", idx=0),
        game(5, 12.0, "block_start", block="A", cond="silent", idx=1),
        game(6, 14.0, "request_item", "human", "A", "silent", 1, "milk", 1),
        game(7, 15.0, "task_failed", "robot", "A", "silent", 1, "milk", 1, detail="manipulation"),
        game(8, 16.0, "feedback_start", "robot", "A", "silent", 1, "milk", 1, "silent"),
        game(9, 30.0, "session_aborted", block="A", cond="silent", idx=1),   # block A unfinished
        emo(1, 0.5, None, "neutral"),
        emo(2, 17.0, "neutral", "angry"),
        emo(3, 19.0, "angry", "neutral"),
        emo(4, 25.0, "neutral", None),          # face lost: gap until the end
        emo(1, 20.0, None, "happy", face=2),    # second face, open until the end
    ]
    conn.executemany(f"INSERT INTO events ({', '.join(chr(34) + c + chr(34) for c in COLS)})"
                     f" VALUES ({', '.join('?' * len(COLS))})", rows)
    conn.close()
    return path


def test_emotion_intervals(db_path):
    iv = data.emotion_intervals(data.load_events(db_path, "s"))
    got = [tuple(r) for r in iv[["face_id", "emotion", "start", "end"]].itertuples(index=False)]
    assert got == [(1, "neutral", 0.5, 17.0), (1, "angry", 17.0, 19.0), (1, "neutral", 19.0, 25.0),
                   (2, "happy", 20.0, 30.0)]
    assert data.emotion_at(iv, 18.0) == "angry"
    assert data.emotion_at(iv, 26.0) == "happy"     # face 1 lost, face 2 still seen


def test_blocks_failures_and_share(db_path):
    events = data.load_events(db_path)              # latest session by default
    spans = data.block_spans(events)
    assert [tuple(r) for r in spans[["block_id", "start", "end", "finished"]].itertuples(
        index=False)] == [("tutorial", 1.0, 10.0, True), ("A", 12.0, 30.0, False)]
    failures = data.failure_moments(events)
    assert failures[["item", "failure_type", "t_session"]].values.tolist() == [
        ["milk", "manipulation", 16.0]]
    share = data.emotion_share(data.emotion_intervals(events), spans)
    for _, block in share.groupby("block_id"):
        assert block["fraction"].sum() == pytest.approx(1.0)
    a = share[share["block_id"] == "A"].set_index("emotion")["seconds"]
    assert a["angry"] == pytest.approx(2.0) and a["happy"] == pytest.approx(10.0)
    reactions = summary.failure_reactions(data.emotion_intervals(events), failures)
    assert reactions[["emotion_before", "emotions_within_5s"]].values.tolist() == [
        ["neutral", "angry > happy"]]   # face 2 starts happy at 20 s


def test_clis_write_files_and_do_not_modify_db(db_path, tmp_path, capsys):
    mtime = db_path.stat().st_mtime_ns
    paths = plot_session.plot_session(db_path, "s", tmp_path / "fig", ("png",))
    assert sorted(p.name for p in paths) == ["emotion_share.png", "failure_locked.png",
                                             "timeline.png"]
    assert all(p.stat().st_size > 0 for p in paths)
    summary.main(["--db", str(db_path), "--session", "s", "--out", str(tmp_path / "out")])
    assert {p.name for p in (tmp_path / "out" / "s").iterdir()} == {
        "events.csv", "emotion_intervals.csv", "failures.csv", "emotion_share.csv",
        "trial_summary.csv"}
    assert "failure messages: 1" in capsys.readouterr().out
    assert db_path.stat().st_mtime_ns == mtime
