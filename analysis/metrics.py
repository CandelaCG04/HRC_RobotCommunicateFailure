"""Evaluation metrics: user persistence and interaction outcome.

    failure_episodes   one row per failure message: response (a1..a5), phase,
                       the participant's decision and latency, emotion in between,
                       and (adaptive mode) the robot's belief before/after
    persistence        per task (one item in one block): attempts, time to
                       abandonment, inter-attempt time, final outcome
    outcome_table      per group: continuation rate, alternative acceptance,
                       decision latency
    completion_table   per condition: share of tasks delivered / alternative /
                       self / gave up, and task completion rate

Groups are the condition in fixed mode and the robot's response (a1..a5) in
adaptive mode, so both designs read the same way.
"""
from __future__ import annotations

import json

import pandas as pd

from analysis import data

# Human decision rows that end a failure episode, and their decision names.
DECISION_OF_ACTION = {"retry": "retry", "accept_alternative": "accept_alt",
                      "do_it_myself": "self", "switch_request": "switch", "give_up": "give_up"}
ATTEMPT_ACTIONS = ("request_item", "retry")


def _payload(value):
    if isinstance(value, str) and value:
        return json.loads(value)
    return {}


def failure_episodes(events: pd.DataFrame) -> pd.DataFrame:
    game = events[events["source"] == "game"].sort_values(["t_session", "seq"])
    starts = game[(game["action"] == "feedback_start")
                  & game["feedback_type"].isin(data.FAILURE_FEEDBACK)]
    decisions = game[game["action"].isin(DECISION_OF_ACTION)]
    ends = game[(game["action"] == "feedback_end")]
    updates = game[game["action"] == "belief_update"]
    intervals = data.emotion_intervals(events)
    next_start = starts["t_session"].tolist()[1:] + [float("inf")]
    rows = []
    for (_, fb), t_next in zip(starts.iterrows(), next_start):
        t0 = fb["t_session"]
        dec = decisions[(decisions["t_session"] >= t0) & (decisions["item"] == fb["item"])
                        & (decisions["t_session"] < t_next)].head(1)
        end = ends[ends["t_session"] >= t0].head(1)
        upd = updates[(updates["t_session"] >= t0) & (updates["t_session"] < t_next)].head(1)
        p = _payload(fb.get("payload"))
        u = _payload(upd["payload"].iloc[0]) if len(upd) else {}
        t_dec = dec["t_session"].iloc[0] if len(dec) else None
        action = p.get("robot_action") or data.ACTION_OF_FEEDBACK[fb["feedback_type"]]
        rows.append({
            "t_session": t0, "block_id": fb["block_id"], "condition": fb["condition"],
            "item": fb["item"], "attempt": fb["attempt"], "task_id": fb["task_id"],
            "trial_id": fb["trial_id"], "robot_action": action,
            "phase": p.get("phase", "fixed"), "policy": p.get("policy"),
            "alternative_offered": action == "a3",
            "decision": DECISION_OF_ACTION[dec["action"].iloc[0]] if len(dec) else None,
            "decision_latency_s": (t_dec - end["t_session"].iloc[0])
            if t_dec is not None and len(end) else None,
            "emotion_dominant": _dominant(intervals, t0, t_dec if t_dec is not None else t0 + 5),
            "belief_most_likely": u.get("most_likely"),
            "reward": u.get("reward"),
            **{f"p_{k}": v for k, v in u.get("belief_posterior", {}).items()},
        })
    return pd.DataFrame(rows)


def _dominant(intervals, t_from, t_to):
    """Emotion with the longest dwell in [t_from, t_to] (None: no face)."""
    if intervals.empty or t_to <= t_from:
        return None
    dwell = (intervals["end"].clip(upper=t_to) - intervals["start"].clip(lower=t_from)).clip(lower=0)
    per = dwell.groupby(intervals["emotion"]).sum()
    per = per[per > 0]
    return per.idxmax() if len(per) else None


def persistence(events: pd.DataFrame) -> pd.DataFrame:
    game = events[(events["source"] == "game") & events["task_id"].notna()]
    rows = []
    for task_id, g in game.groupby("task_id", sort=False):
        g = g.sort_values(["t_session", "seq"])
        tries = g[g["action"].isin(ATTEMPT_ACTIONS)]["t_session"]
        if tries.empty:
            continue
        resolved = g[g["action"] == "item_resolved"]
        gave_up = g[g["action"] == "give_up"]
        gaps = tries.diff().dropna()
        rows.append({
            "task_id": task_id, "block_id": g["block_id"].iloc[0],
            "condition": g["condition"].iloc[0], "item": g["item"].iloc[0],
            "failures": int(((g["action"] == "feedback_start")
                             & g["feedback_type"].isin(data.FAILURE_FEEDBACK)).sum()),
            "attempts": len(tries),
            "outcome": resolved["detail"].iloc[-1] if len(resolved) else "unresolved",
            "time_to_abandonment_s": (gave_up["t_session"].iloc[0] - tries.iloc[0])
            if len(gave_up) else None,
            "mean_inter_attempt_s": gaps.mean() if len(gaps) else None,
        })
    return pd.DataFrame(rows)


_ORDER = {v: i for i, v in enumerate(data.CONDITIONS + tuple(data.ACTION_LABEL))}


def _ordered(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """Conditions in study order (silent, explanation, ...), actions a1..a5."""
    return table.sort_values(column, key=lambda c: c.map(lambda v: _ORDER.get(v, 99))) \
        .reset_index(drop=True)


def group_column(episodes: pd.DataFrame) -> str:
    """Robot response in adaptive sessions, condition otherwise."""
    return "robot_action" if (episodes.get("phase", pd.Series(dtype=str)) != "fixed").any() \
        else "condition"


def outcome_table(episodes: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame()
    by = by or group_column(episodes)
    decided = episodes[episodes["decision"].notna()]
    if decided.empty:
        return pd.DataFrame()

    def summary(g):
        offered = g[g["alternative_offered"]]
        return pd.Series({
            "failure_episodes": len(g),
            "continuation_rate": (g["decision"] != "give_up").mean(),
            "alternative_acceptance": (offered["decision"] == "accept_alt").mean()
            if len(offered) else float("nan"),
            "retry_rate": (g["decision"] == "retry").mean(),
            "mean_decision_latency_s": g["decision_latency_s"].mean(),
        })
    return _ordered(decided.groupby(by).apply(summary, include_groups=False).reset_index(), by)


def completion_table(tasks: pd.DataFrame) -> pd.DataFrame:
    """Per condition, over tasks that failed at least once."""
    if tasks.empty:
        return pd.DataFrame()
    failed = tasks[tasks["failures"] > 0]
    if failed.empty:
        return pd.DataFrame()
    share = pd.crosstab(failed["condition"], failed["outcome"], normalize="index")
    out = share.add_prefix("share_").reset_index()
    out["tasks"] = failed.groupby("condition").size().values
    done = failed["outcome"].isin(["delivered", "alternative", "self"])
    out["completion_rate"] = done.groupby(failed["condition"]).mean().values
    out["mean_attempts"] = failed.groupby("condition")["attempts"].mean().values
    out["mean_time_to_abandonment_s"] = failed.groupby("condition")["time_to_abandonment_s"] \
        .mean().values
    out["mean_inter_attempt_s"] = failed.groupby("condition")["mean_inter_attempt_s"].mean().values
    return _ordered(out, "condition")
