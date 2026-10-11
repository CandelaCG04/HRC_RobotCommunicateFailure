"""Figures for one session: game events and emotions on the shared timeline.

    python -m analisys.plot_session [--session ID] [--db PATH] [--out DIR] [--formats png,pdf]

Writes to ``<out>/<session>/``:
    timeline.*         emotion states (per face) above the game events, by actor
    failure_locked.*   emotion from -5 s to +15 s around each failure message
    emotion_share.*    share of observed time per emotion in each block
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from analysis import data  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "figures"

# Light-mode tokens (dataviz reference palette).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
EMOTION_COLOR = "#2a78d6"     # emotion identity is the row; one hue for all states
NEUTRAL_COLOR = "#c3c2b7"     # neutral is the resting state: recessive grey
CRITICAL = "#d03b3b"          # failure message (status: always with marker + label)
GOOD = "#0ca30c"              # successful delivery (status: always with marker + label)
# Block background tints: categorical slots 1-3 for the conditions, grey for practice.
CONDITION_TINT = {"tutorial": "#898781", "silent": "#2a78d6", "explanation": "#eb6834",
                  "explanation_alternative": "#1baf7a"}
SEQUENTIAL = ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95",
              "#0d366b"]
CONDITION_LABEL = {"tutorial": "practice", "silent": "silent", "explanation": "explanation",
                   "explanation_alternative": "explanation + alternative"}
# Emotion rows top to bottom; neutral last, next to the game lanes.
EMOTION_ROWS = ("angry", "disgust", "fear", "sad", "surprise", "happy", "neutral")
DECISIONS = {"request_item", "retry", "accept_alternative", "do_it_myself", "switch_request",
             "give_up"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": INK_2, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
})


def _attempt(value) -> str:
    return "?" if value != value or value is None else str(int(value))


def _block_label(block) -> str:
    if block["condition"] == "tutorial":
        return "Practice"
    return f"{block['block_id']} · {CONDITION_LABEL.get(block['condition'], block['condition'])}"


def _shade_blocks(axes, spans, label_ax=None):
    for _, b in spans.iterrows():
        tint = CONDITION_TINT.get(b["condition"], MUTED)
        for ax in axes:
            ax.axvspan(b["start"], b["end"], color=tint, alpha=0.08, lw=0, zorder=0)
        if label_ax is not None:
            suffix = "" if b["finished"] else " (unfinished)"
            label_ax.text((b["start"] + b["end"]) / 2, 1.02, _block_label(b) + suffix,
                          transform=label_ax.get_xaxis_transform(), ha="center", va="bottom",
                          fontsize=9, color=INK_2)


def _emotion_axis(ax, intervals, xlim, title=None):
    for row, emotion in enumerate(EMOTION_ROWS):
        sel = intervals[intervals["emotion"] == emotion]
        color = NEUTRAL_COLOR if emotion == "neutral" else EMOTION_COLOR
        ax.broken_barh(list(zip(sel["start"], sel["duration"])), (row - 0.32, 0.64),
                       facecolors=color, edgecolor=SURFACE, linewidth=0.5, zorder=2)
    ax.set_yticks(range(len(EMOTION_ROWS)), EMOTION_ROWS)
    ax.set_ylim(len(EMOTION_ROWS) - 0.5, -0.5)
    ax.set_xlim(*xlim)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    if title:
        ax.set_ylabel(title, rotation=0, ha="right", va="center", color=INK_2, labelpad=12)


def _failure_lines(axes, failures, label_ax):
    for _, f in failures.iterrows():
        for ax in axes:
            ax.axvline(f["t_session"], color=CRITICAL, lw=1.2, ls=(0, (4, 3)), zorder=3)
        # Label inside the game panel, above the robot lane (row -1).
        label_ax.annotate(f"{f['failure_type'] or 'failure'}", (f["t_session"], -1.0),
                          xytext=(3, 0), textcoords="offset points", ha="left", va="center",
                          fontsize=7.5, color=INK_2, zorder=5)


def plot_timeline(events, intervals, spans, failures, session, out: Path, formats):
    t_end = data.session_end(events)
    xlim = (min(0.0, events["t_session"].min()), t_end * 1.01 + 1)
    faces = sorted(intervals["face_id"].unique()) or [None]
    width = min(30, max(12, t_end / 14))
    fig, axes = plt.subplots(
        len(faces) + 1, 1, sharex=True, figsize=(width, 2.3 * len(faces) + 2.6),
        gridspec_kw={"height_ratios": [len(EMOTION_ROWS)] * len(faces) + [5.5],
                     "hspace": 0.12})
    emo_axes, game_ax = axes[:-1], axes[-1]
    for ax, face in zip(emo_axes, faces):
        sel = intervals[intervals["face_id"] == face] if face is not None else intervals
        _emotion_axis(ax, sel, xlim, f"face {face}" if face is not None else "no face")
        ax.tick_params(axis="x", length=0)
        ax.spines["bottom"].set_visible(False)

    # Game lanes: one row per actor.
    game = events[events["source"] == "game"]
    lanes = {actor: i for i, actor in enumerate(data.ACTORS)}
    for actor, row in lanes.items():
        g = game[game["actor"] == actor]
        if actor == "robot":
            ok = g["action"].eq("feedback_start") & g["feedback_type"].isin(["success",
                                                                            "success_alternative"])
            fail = g["action"].eq("feedback_start") & g["feedback_type"].isin(data.FAILURE_FEEDBACK)
            rest = g[~ok & ~fail]
            game_ax.scatter(rest["t_session"], [row] * len(rest), marker="|", s=90, lw=1,
                            color=MUTED, zorder=3)
            game_ax.scatter(g[ok]["t_session"], [row] * ok.sum(), marker="o", s=42, color=GOOD,
                            edgecolor=SURFACE, lw=1.5, zorder=4)
            game_ax.scatter(g[fail]["t_session"], [row] * fail.sum(), marker="X", s=70,
                            color=CRITICAL, edgecolor=SURFACE, lw=1, zorder=4)
        elif actor == "human":
            dec = g["action"].isin(DECISIONS)
            game_ax.scatter(g[~dec]["t_session"], [row] * (~dec).sum(), marker="|", s=90, lw=1,
                            color=MUTED, zorder=3)
            game_ax.scatter(g[dec]["t_session"], [row] * dec.sum(), marker="D", s=34,
                            color=INK_2, edgecolor=SURFACE, lw=1, zorder=4)
        else:
            game_ax.scatter(g["t_session"], [row] * len(g), marker="|", s=90, lw=1, color=MUTED,
                            zorder=3)
    game_ax.set_yticks(list(lanes.values()), list(lanes))
    game_ax.set_ylim(len(lanes) - 0.4, -1.5)   # headroom for the failure-type labels
    game_ax.tick_params(axis="y", length=0)
    game_ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    game_ax.set_xlabel("time since session start (s)")
    game_ax.set_xlim(*xlim)

    _shade_blocks(axes, spans, label_ax=emo_axes[0])
    _failure_lines(axes, failures, label_ax=game_ax)

    legend = [
        Line2D([], [], color=EMOTION_COLOR, lw=6, label="emotion state"),
        Line2D([], [], color=NEUTRAL_COLOR, lw=6, label="neutral"),
        Line2D([], [], marker="X", ls="", color=CRITICAL, ms=8, label="failure message"),
        Line2D([], [], marker="o", ls="", color=GOOD, ms=7, label="item delivered"),
        Line2D([], [], marker="D", ls="", color=INK_2, ms=6, label="participant request / decision"),
        Line2D([], [], marker="|", ls="", color=MUTED, ms=10, mew=1.2, label="other event"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=len(legend), frameon=False,
               bbox_to_anchor=(0.5, -0.01), fontsize=8.5)
    participant = events["participant"].dropna()
    who = f"{participant.iloc[0]} · " if len(participant) else ""
    fig.suptitle(f"{who}session {session[:8]} · game events and facial emotion", x=0.01,
                 ha="left", fontsize=11, color=INK)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.86, bottom=0.16)
    return _save(fig, out, "timeline", formats)


def plot_failure_locked(intervals, failures, out: Path, formats, before=5.0, after=15.0):
    if failures.empty:
        return []
    failures = failures.assign(order=failures["condition"].map(
        {c: i for i, c in enumerate(data.CONDITIONS)})).sort_values(["order", "t_session"])
    n = len(failures)
    cols = min(4, n)
    rows = -(-n // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.4 * cols, 2.5 * rows + 0.8), sharey=True,
                             squeeze=False)
    for ax, (_, f) in zip(axes.flat, failures.iterrows()):
        rel = intervals.assign(start=intervals["start"] - f["t_session"],
                               end=intervals["end"] - f["t_session"])
        rel = rel[(rel["end"] > -before) & (rel["start"] < after)]
        rel = rel.assign(start=rel["start"].clip(lower=-before), end=rel["end"].clip(upper=after))
        rel = rel.assign(duration=rel["end"] - rel["start"])
        _emotion_axis(ax, rel, (-before, after))
        ax.axvline(0, color=CRITICAL, lw=1.2, ls=(0, (4, 3)), zorder=3)
        ax.set_title(f"{f['block_id']} · {CONDITION_LABEL.get(f['condition'], f['condition'])}\n"
                     f"{f['item']} #{_attempt(f['attempt'])} · {f['failure_type'] or '?'}",
                     fontsize=8.5, color=INK_2, loc="left")
        ax.set_xticks([-5, 0, 5, 10, 15])
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.supxlabel("seconds relative to the failure message (dashed line)", fontsize=9,
                  color=INK_2)
    fig.suptitle("Facial emotion around each failure message", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    return _save(fig, out, "failure_locked", formats)


def plot_emotion_share(share, out: Path, formats):
    if share.empty:
        return []
    table = share.pivot_table(index=["block_id", "condition"], columns="emotion",
                              values="fraction", sort=False).reindex(columns=list(data.EMOTIONS))
    labels = [_block_label({"block_id": b, "condition": c}) for b, c in table.index]
    cmap = LinearSegmentedColormap.from_list("blue", SEQUENTIAL)
    fig, ax = plt.subplots(figsize=(1.0 * len(data.EMOTIONS) + 2.2, 0.55 * len(table) + 1.6))
    values = table.to_numpy(dtype=float)
    ax.imshow(values, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for (i, j), v in np.ndenumerate(values):
        if v == v:  # not NaN
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=8.5,
                    color=SURFACE if v > 0.55 else INK)
    ax.set_xticks(range(len(data.EMOTIONS)), data.EMOTIONS)
    ax.set_yticks(range(len(labels)), labels)
    ax.tick_params(length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.set_title("Share of observed time per emotion, by block", loc="left", fontsize=11)
    fig.tight_layout()
    return _save(fig, out, "emotion_share", formats)


def _save(fig, out: Path, name: str, formats) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in formats:
        path = out / f"{name}.{fmt}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        paths.append(path)
    plt.close(fig)
    return paths


def plot_session(db=None, session=None, out_dir: Path = OUT_DIR, formats=("png", "pdf")):
    session = data.resolve_session(db, session)
    events = data.load_events(db, session)
    intervals = data.emotion_intervals(events)
    spans = data.block_spans(events)
    failures = data.failure_moments(events)
    out = Path(out_dir) / session
    paths = plot_timeline(events, intervals, spans, failures, session, out, formats)
    paths += plot_failure_locked(intervals, failures, out, formats)
    paths += plot_emotion_share(data.emotion_share(intervals, spans), out, formats)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session", help="session id (default: latest)")
    parser.add_argument("--db", help="database (default: $HRC_DB or data/hrc.db)")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--formats", default="png,pdf")
    args = parser.parse_args(argv)
    for path in plot_session(args.db, args.session, Path(args.out), args.formats.split(",")):
        print(path)


if __name__ == "__main__":
    main()
