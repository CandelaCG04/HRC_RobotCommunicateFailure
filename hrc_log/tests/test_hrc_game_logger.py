"""Game logger -> events mapping. game.core.logger has no pygame dependency."""
import csv

from game.core.logger import FIELDS, EventLogger


def test_game_events_map_to_columns(tmp_path, db_path, read):
    logger = EventLogger(tmp_path / "logs", "P07", db_path=db_path, csv_log=True)
    logger.set_context(order=2)
    logger.log("system", "session_start", detail="order=a/b/c")
    logger.set_context(block_index=1, block_id="A", condition="silent")
    logger.log("robot", "task_failed", item="tea", attempt=2,
               feedback_type="perception", detail="no cup", robot_state="WORKING")
    logger.log("human", "activity_step", item="tea", detail="stir")
    logger.close("completed")

    assert read("SELECT session_id, participant, status FROM sessions") == [
        (logger.session_id, "P07", "completed")]
    rows = read('SELECT seq, event_type, participant, "order", block_index, block_id, condition,'
                " actor, action, item, attempt, feedback_type, detail, task_id, trial_id,"
                " robot_state, source, clock_basis FROM events ORDER BY seq")
    assert rows == [
        (1, "session_start", "P07", 2, None, None, None, "system", "session_start", None, None,
         None, "order=a/b/c", None, None, None, "game", "mono"),
        (2, "task_failed", "P07", 2, 1, "A", "silent", "robot", "task_failed", "tea", 2,
         "perception", "no cup", "A:tea", "A:tea:2", "WORKING", "game", "mono"),
        (3, "activity_step", "P07", 2, 1, "A", "silent", "human", "activity_step", "tea", None,
         None, "stir", "A:tea", None, None, "game", "mono"),
    ]
    # the same instant in both clocks; t_game is the old CSV t_session
    for t_wall, t_session, t_game, t0 in read(
            "SELECT e.t_wall, e.t_session, e.t_game, s.t0_wall FROM events e JOIN sessions s"
            " USING (session_id)"):
        assert abs((t_wall - t0) - t_session) < 0.05 and abs(t_game - t_session) < 0.05

    # opt-in CSV keeps the old format
    with open(logger.path, newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert tuple(csv_rows[0]) == FIELDS
    assert [r["action"] for r in csv_rows] == ["session_start", "task_failed", "activity_step"]


def test_no_csv_by_default_and_joined_session_stays_open(tmp_path, db_path, read, monkeypatch):
    monkeypatch.setenv("HRC_SESSION_ID", "launched")
    from hrc_log import db
    db.ensure_session(db.connect(db_path), "launched", "launcher")
    logger = EventLogger(tmp_path / "logs", "P01", db_path=db_path)
    logger.log("system", "session_start")
    logger.close("aborted")
    assert logger.path is None and not (tmp_path / "logs").exists()
    # the launcher, not the game, ends a session it created
    assert read("SELECT status FROM sessions") == [("open",)]
    assert read("SELECT session_id FROM events") == [("launched",)]
