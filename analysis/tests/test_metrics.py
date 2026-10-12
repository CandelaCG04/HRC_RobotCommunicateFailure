"""Persistence and interaction-outcome metrics on a synthetic session."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis import data, metrics  # noqa: E402
from hrc_log import db as hdb  # noqa: E402

COLS = ("session_id", "source", "writer_id", "seq", "event_type", "t_wall", "t_session",
        "clock_basis", "t_iso", "block_id", "condition", "actor", "action", "item", "attempt",
        "feedback_type", "detail", "task_id", "trial_id", "payload")


def make_rows():
    rows, seq = [], [0]

    def ev(t, actor, action, block, cond, item=None, attempt=None, fb=None, detail=None,
           payload=None):
        seq[0] += 1
        task, trial = hdb.trial_ids(block, item, attempt)
        rows.append(("s", "game", "g", seq[0], action, 1000 + t, t, "mono", "", block, cond,
                     actor, action, item, attempt, fb, detail, task, trial,
                     json.dumps(payload) if payload else None))

    # Block A, silent: milk fails, retry, fails again, give up.
    ev(1, "human", "request_item", "A", "silent", "milk", 1)
    ev(3, "robot", "feedback_start", "A", "silent", "milk", 1, "silent")
    ev(6, "robot", "feedback_end", "A", "silent", "milk", 1)
    ev(8, "human", "retry", "A", "silent", "milk", 2)
    ev(10, "robot", "feedback_start", "A", "silent", "milk", 2, "silent")
    ev(13, "robot", "feedback_end", "A", "silent", "milk", 2)
    ev(15, "human", "give_up", "A", "silent", "milk", 2)
    ev(15, "system", "item_resolved", "A", "silent", "milk", 2, detail="gave_up")
    # Block B, explanation + alternative: alternative accepted.
    ev(20, "human", "request_item", "B", "explanation_alternative", "tea", 1)
    ev(22, "robot", "feedback_start", "B", "explanation_alternative", "tea", 1,
       "explanation_alternative")
    ev(25, "robot", "feedback_end", "B", "explanation_alternative", "tea", 1)
    ev(26, "human", "accept_alternative", "B", "explanation_alternative", "tea", 1)
    ev(30, "system", "item_resolved", "B", "explanation_alternative", "tea", 1,
       detail="alternative")
    # Block C, adaptive: apology, then retry and delivery.
    ev(40, "human", "request_item", "C", "adaptive", "jam", 1)
    ev(42, "robot", "feedback_start", "C", "adaptive", "jam", 1, "explanation_apology",
       payload={"robot_action": "a5", "phase": "baseline", "policy": "mdp"})
    ev(45, "robot", "feedback_end", "C", "adaptive", "jam", 1)
    ev(47, "system", "belief_update", "C", "adaptive", "jam", 1, payload={
        "most_likely": "receptive", "reward": 0.7,
        "belief_posterior": {"receptive": 0.8, "frustrated": 0.15, "disengaging": 0.05}})
    ev(47, "human", "retry", "C", "adaptive", "jam", 2)
    ev(55, "system", "item_resolved", "C", "adaptive", "jam", 2, detail="delivered")
    return rows


@pytest.fixture
def events(tmp_path):
    path = tmp_path / "hrc.db"
    conn = hdb.connect(path)
    hdb.ensure_session(conn, "s", "cli", "P01", t0_wall=1000.0, t0_mono=50.0)
    conn.executemany(f"INSERT INTO events ({', '.join(chr(34) + c + chr(34) for c in COLS)})"
                     f" VALUES ({', '.join('?' * len(COLS))})", make_rows())
    conn.close()
    return data.load_events(path, "s")


def test_failure_episodes(events):
    ep = metrics.failure_episodes(events)
    assert ep[["robot_action", "phase", "decision", "decision_latency_s"]].values.tolist() == [
        ["a1", "fixed", "retry", 2.0], ["a1", "fixed", "give_up", 2.0],
        ["a3", "fixed", "accept_alt", 1.0], ["a5", "baseline", "retry", 2.0]]
    assert ep["alternative_offered"].tolist() == [False, False, True, False]
    last = ep.iloc[-1]
    assert (last["belief_most_likely"], last["reward"], last["p_receptive"]) == (
        "receptive", 0.7, 0.8)


def test_persistence(events):
    tasks = metrics.persistence(events).set_index("task_id")
    milk = tasks.loc["A:milk"]
    assert (milk["attempts"], milk["failures"], milk["outcome"]) == (2, 2, "gave_up")
    assert milk["time_to_abandonment_s"] == 14.0 and milk["mean_inter_attempt_s"] == 7.0
    assert tasks.loc["B:tea", "outcome"] == "alternative"
    assert pytest.approx(tasks.loc["C:jam", "mean_inter_attempt_s"]) == 7.0
    assert tasks.loc["B:tea", "time_to_abandonment_s"] != tasks.loc["B:tea",
                                                                     "time_to_abandonment_s"]


def test_outcome_and_completion_tables(events):
    ep = metrics.failure_episodes(events)
    out = metrics.outcome_table(ep).set_index("robot_action")     # adaptive rows -> by action
    assert list(out.index) == ["a1", "a3", "a5"]
    assert out.loc["a1", "continuation_rate"] == 0.5
    assert out.loc["a3", "alternative_acceptance"] == 1.0
    assert out.loc["a1", "alternative_acceptance"] != out.loc["a1", "alternative_acceptance"]
    by_condition = metrics.outcome_table(ep, by="condition")
    assert list(by_condition["condition"]) == ["silent", "explanation_alternative", "adaptive"]
    done = metrics.completion_table(metrics.persistence(events)).set_index("condition")
    assert done.loc["silent", "completion_rate"] == 0.0
    assert done.loc["explanation_alternative", "completion_rate"] == 1.0
    assert done.loc["silent", "mean_attempts"] == 2.0
