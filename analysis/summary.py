"""Export analysis tables for one session as CSV and print a short summary.

    python -m analysis.summary [--session ID] [--db PATH] [--out DIR]

Writes to ``<out>/<session>/``: events.csv, emotion_intervals.csv,
failures.csv (with the emotion before/after each failure message),
emotion_share.csv, trial_summary.csv, and the evaluation metrics
failure_episodes.csv, persistence.csv, outcomes.csv and completion.csv
(see metrics.py).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from analysis import data, metrics

OUT_DIR = Path(__file__).resolve().parent / "output"
REACTION_WINDOW = 5.0   # seconds after a failure message counted as the reaction


def failure_reactions(intervals: pd.DataFrame, failures: pd.DataFrame,
                      window: float = REACTION_WINDOW) -> pd.DataFrame:
    """Per failure message: emotion just before it, and the non-neutral
    emotions that start within ``window`` seconds after it."""
    out = failures.copy()
    out["emotion_before"] = [data.emotion_at(intervals, t - 1e-6) for t in out["t_session"]]
    after = []
    for t in out["t_session"]:
        sel = intervals[(intervals["start"] >= t) & (intervals["start"] <= t + window)
                        & (intervals["emotion"] != "neutral")]
        after.append(" > ".join(sel.sort_values("start")["emotion"]) or None)
    out[f"emotions_within_{window:g}s"] = after
    return out


def export(db=None, session=None, out_dir: Path = OUT_DIR) -> dict[str, pd.DataFrame]:
    session = data.resolve_session(db, session)
    events = data.load_events(db, session)
    intervals = data.emotion_intervals(events)
    spans = data.block_spans(events)
    tables = {
        "events": events,
        "emotion_intervals": intervals,
        "failures": failure_reactions(intervals, data.failure_moments(events)),
        "emotion_share": data.emotion_share(intervals, spans),
        "trial_summary": data.trial_summary(db, session),
    }
    episodes = metrics.failure_episodes(events)
    tasks = metrics.persistence(events)
    tables.update({
        "failure_episodes": episodes,
        "persistence": tasks,
        "outcomes": metrics.outcome_table(episodes),
        "completion": metrics.completion_table(tasks),
    })
    out = Path(out_dir) / session
    out.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False)
    tables["_dir"] = out
    tables["_session"] = session
    return tables


def print_summary(tables) -> None:
    events, failures = tables["events"], tables["failures"]
    print(f"session {tables['_session']}  ->  {tables['_dir']}")
    print("\nevents per source:")
    print(events.groupby("source").size().to_string())
    share = tables["emotion_share"]
    if not share.empty:
        print("\nshare of observed time per emotion (%):")
        pivot = share.pivot_table(index=["block_id", "condition"], columns="emotion",
                                  values="fraction", sort=False)
        print((pivot.reindex(columns=list(data.EMOTIONS)) * 100).round(1).to_string())
    print(f"\nfailure messages: {len(failures)}")
    if not failures.empty:
        cols = ["t_session", "condition", "item", "attempt", "failure_type", "emotion_before",
                f"emotions_within_{REACTION_WINDOW:g}s"]
        print(failures[cols].round({"t_session": 1}).to_string(index=False))


def print_metrics(tables) -> None:
    for name, title in (("outcomes", "interaction outcome"),
                        ("completion", "task completion and persistence (failed tasks)")):
        table = tables[name]
        if not table.empty:
            print(f"\n{title}:")
            print(table.round(2).to_string(index=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session", help="session id (default: latest)")
    parser.add_argument("--db", help="database (default: $HRC_DB or data/hrc.db)")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)
    tables = export(args.db, args.session, Path(args.out))
    print_summary(tables)
    print_metrics(tables)


if __name__ == "__main__":
    main()
