"""Adaptive failure-response model (game/adaptive/). Pure Python, no pygame:

    analysis/.venv/bin/python -m pytest game/tests -q
"""
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from game.adaptive import load_config, observations  # noqa: E402
from game.adaptive.hmm import BeliefFilter  # noqa: E402
from game.adaptive.mind import RobotMind  # noqa: E402
from game.adaptive.policy import (BASELINE_ROWS, BaselineSchedule, HeuristicPolicy,  # noqa: E402
                                  UserModel, williams_design)
from game.adaptive.sensing import EmotionReader  # noqa: E402
from game.robot import responses  # noqa: E402
from game.robot.responses import ACTIONS  # noqa: E402

CFG = load_config()
BINS = CFG["pause_bins_s"]


def obs(decision="retry", latency=2.0, intervals=(), span=5.0):
    return observations.observe(list(intervals), 0.0, span, decision, latency, BINS)


# ----------------------------------------------------------- observations
def test_emotion_evidence_is_confidence_weighted_dwell():
    ev = observations.emotion_evidence([("angry", -2.0, 2.0, 0.5), ("neutral", 2.0, 4.0, 1.0)],
                                       0.0, 5.0)
    # anger 2 s * 0.5; neutral 2 s; uninformative: 1 s unsure anger + 1 s no face
    assert ev["anger"] == pytest.approx(0.2) and ev["neutral"] == pytest.approx(0.4)
    assert ev["uninformative"] == pytest.approx(0.4) and ev["face_seconds"] == pytest.approx(4.0)
    assert observations.dominant_emotion(ev) == "neutral"


def test_ambiguous_and_missing_face_are_uninformative():
    assert observations.emotion_evidence([("surprise", 0, 5, 0.9)], 0, 5)["uninformative"] == 1.0
    assert observations.emotion_evidence([], 0, 5)["uninformative"] == 1.0
    assert observations.dominant_emotion(observations.emotion_evidence([], 0, 5)) is None


def test_pause_bins():
    assert [observations.pause_bin(t, BINS) for t in (1, 5, 8, 20)] == [
        "fast", "normal", "slow", "slow"]


def test_sensing_reads_window_of_main_face(tmp_path):
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE events (session_id, source, event_type, face_id, t_wall, emotion,"
                " confidence, seq)")
    rows = [("s", "femotion", "emotion_transition", 1, 100.0, "neutral", 0.8, 1),
            ("s", "femotion", "emotion_transition", 1, 104.0, "angry", 0.6, 2),
            ("s", "femotion", "emotion_transition", 1, 106.0, None, None, 3),
            ("s", "femotion", "emotion_transition", 2, 103.0, "happy", 0.9, 1),   # bystander,
            ("s", "femotion", "emotion_transition", 2, 104.5, None, None, 2),     # seen briefly
            ("other", "femotion", "emotion_transition", 1, 103.0, "sad", 0.9, 1)]
    con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    reader = EmotionReader(db, "s")
    assert reader.window(102.0, 108.0) == [("neutral", 102.0, 104.0, 0.8),
                                           ("angry", 104.0, 106.0, 0.6)]
    assert EmotionReader(tmp_path / "missing.db", "s").window(0, 1) == []


# -------------------------------------------------------------------- HMM
def test_uninformative_observation_only_applies_dynamics():
    f = BeliefFilter(CFG)
    flat = {"decision": {s: dict.fromkeys(observations.DECISIONS, 0.2) for s in f.states},
            "pause": {s: dict.fromkeys(observations.PAUSES, 1 / 3) for s in f.states},
            "emotion": CFG["emission"]["emotion"]}
    f.emission = flat
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    before = list(f.belief)
    f.update(identity, obs(intervals=[("surprise", 0, 5, 1.0)]))
    assert f.belief == pytest.approx(before)
    assert sum(f.belief) == pytest.approx(1.0)


def test_single_anger_reading_nudges_repeated_anger_shifts():
    model = UserModel(CFG)
    once = BeliefFilter(CFG)
    once.update(model.transition("a2"), obs(intervals=[("angry", 4.5, 5.0, 0.6)]))
    assert once.most_likely() == "receptive"        # one short reading is not enough
    repeated = BeliefFilter(CFG)
    history = []
    for _ in range(4):
        repeated.update(model.transition("a2"), obs("retry", 2.0, [("angry", 0, 5, 0.8)]))
        history.append(repeated.belief[1])
    assert repeated.most_likely() == "frustrated"
    assert history == sorted(history)               # frustration builds up gradually


def test_abandonment_and_long_pauses_point_to_disengaging():
    model, f = UserModel(CFG), BeliefFilter(CFG)
    for _ in range(3):
        f.update(model.transition("a1"), obs("give_up", 12.0, [("sad", 0, 5, 0.7)]))
    assert f.most_likely() == "disengaging"


# ---------------------------------------------------------------- policies
def test_williams_design_counterbalances():
    rows = williams_design(ACTIONS)
    assert len(rows) == 10 and all(sorted(r) == sorted(ACTIONS) for r in rows)
    for pos in range(5):                            # each action equally often per position
        assert set(Counter(r[pos] for r in rows).values()) == {2}
    pairs = Counter((r[i], r[i + 1]) for r in rows for i in range(4))
    assert len(pairs) == 20 and set(pairs.values()) == {2}   # every ordered pair twice


def test_baseline_schedule_each_action_once_and_skips_unavailable():
    s = BaselineSchedule(0)
    first = BASELINE_ROWS[0][0]
    got = [s.next([a for a in ACTIONS if a != first])]        # first one not allowed now
    got += [s.next(ACTIONS) for _ in range(4)]
    assert sorted(got) == sorted(ACTIONS) and got[0] != first and s.done
    assert BaselineSchedule(11).order == BASELINE_ROWS[1]


def test_heuristic_rules():
    h = HeuristicPolicy(CFG)
    assert h.choose([0.5, 0.4, 0.1], [0.7, 0.2, 0.1], None, ACTIONS)[0] == "a3"   # F rising
    assert h.choose([0.2, 0.2, 0.6], [0.2, 0.2, 0.6], None, ACTIONS)[0] == "a5"   # disengaging
    assert h.choose([0.8, 0.1, 0.1], [0.8, 0.1, 0.1], "give_up", ACTIONS)[0] == "a3"
    assert h.choose([0.8, 0.1, 0.1], [0.8, 0.1, 0.1], "retry", ACTIONS)[0] == "a4"
    assert h.choose([0.8, 0.1, 0.1], None, None, ["a1", "a2"])[0] == "a1"         # fallback


def test_user_model_soft_counts_and_reward_mean():
    m = UserModel(CFG)
    before = [row[:] for row in m.alpha["a3"]]
    m.update("a3", [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 2.0)
    assert m.alpha["a3"][0][1] == pytest.approx(before[0][1] + 1)
    assert m.reward_mean[0][2] == pytest.approx((0.4 * 1 + 2.0) / 2)   # prior 0.4, count 1


# -------------------------------------------------------------- the mind
def run_mind(policy, seed, user, episodes=20):
    """Simulated user: ``user(action, rng) -> (decision, intervals)``."""
    rng = random.Random(seed)
    mind = RobotMind(CFG, policy, baseline_row=seed, seed=seed)
    actions = []
    for _ in range(episodes):
        intent = mind.choose("item")
        decision, intervals = user(intent.action, rng)
        mind.observe(decision, rng.uniform(1, 6), 0.0, 5.0, intervals)
        actions.append((intent.phase, intent.action))
    return actions


def prefers_alternative(action, rng):
    """Accepts and is pleased by an offered alternative; otherwise often
    annoyed and abandons."""
    if action == "a3":
        return "accept_alt", [("happy", 0, 5, 0.8)]
    if rng.random() < 0.6:
        return "give_up", [("angry", 0, 5, 0.8)]
    return "retry", [("neutral", 0, 5, 0.8)]


def test_baseline_then_adaptive_and_reproducible():
    a = run_mind("mdp", 3, prefers_alternative)
    assert [p for p, _ in a[:5]] == ["baseline"] * 5
    assert sorted(x for _, x in a[:5]) == sorted(ACTIONS)
    assert all(p == "adaptive" for p, _ in a[5:])
    assert a == run_mind("mdp", 3, prefers_alternative)        # same seed, same choices


def test_mdp_learns_the_users_preferred_response():
    shares = []
    for seed in range(8):
        adaptive = [x for p, x in run_mind("mdp", seed, prefers_alternative, 20) if p == "adaptive"]
        shares.append(adaptive.count("a3") / len(adaptive))
    assert sum(shares) / len(shares) > 0.6                     # chance would be 0.2


def test_mind_records_and_alternative_availability():
    mind = RobotMind(CFG, "heuristic", 0, seed=1)
    intent = mind.choose("milk", alternative_available=False, retry_available=False)
    assert intent.action not in ("a3", "a4")
    rec = mind.observe("give_up", 9.0, 0.0, 5.0, [])
    assert rec["pause"] == "slow" and rec["emotion"]["uninformative"] == 1.0
    assert set(rec["belief_posterior"]) == {"receptive", "frustrated", "disengaging"}
    with pytest.raises(RuntimeError):
        mind.observe("retry", 1.0, 0.0, 1.0, [])


# -------------------------------------------------------------- responses
def test_action_texts():
    class Alt:
        offer = "Shall I bring the jug?"

    class Failure:
        explanation = "The glass is too slippery."
        alternative = Alt()

    f = Failure()
    assert responses.action_feedback("a1", f) == ("silent", "")
    assert responses.action_feedback("a2", f) == ("explanation", f.explanation)
    assert responses.action_feedback("a3", f)[1] == f"{f.explanation} {Alt.offer}"
    assert responses.action_feedback("a4", f) == (
        "explanation_retry", f"{f.explanation} {responses.RETRY_OFFER}")
    assert responses.action_feedback("a5", f) == (
        "explanation_apology", f"{responses.APOLOGY} {f.explanation}")
    assert [a for a in ACTIONS if responses.action_offers_alternative(a)] == ["a3"]
