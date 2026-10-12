# Analysis

Plots and tables for the shared game + facial-emotion database (`data/hrc.db`).
All times are `t_session`: seconds since the shared session start, the common timeline of game and emotion events. The database is opened read-only.

## Setup (own virtual environment)

```bash
python3 -m venv analysis/.venv
analysis/.venv/bin/pip install -r analysis/requirements.txt
```

## Use (from the repository root)

```bash
analysis/.venv/bin/python -m analysis.plot_session            # latest session
analysis/.venv/bin/python -m analysis.plot_session --session ID --formats png
analysis/.venv/bin/python -m analysis.summary                 # CSV export + printed summary
analysis/.venv/bin/python -m pytest analysis/tests -q
```

`--db PATH` (or `$HRC_DB`) selects another database. Session ids are listed by
`python3 -m hrc_log check`.

## Figures (`analysis/figures/<session>/`, PNG and PDF)

| File | Shows |
|---|---|
| `timeline` | Top: the stable facial emotion per detected face, one row per emotion (neutral in grey; blank = no face). Bottom: game events per actor (robot, human, system). Shaded backgrounds are the blocks, labelled with their condition. Dashed red lines mark failure messages, labelled with the failure type. |
| `failure_locked` | The emotion from 5 s before to 15 s after each failure message, one panel per failure, ordered by condition. |
| `emotion_share` | Share of observed (face-visible) time per emotion in each block. |
| `metrics` | Interaction outcome per condition, or per robot response (a1-a5) in adaptive sessions: continuation rate, alternative acceptance, retry rate, decision latency. Persistence per condition: task completion, attempts, time to abandonment, inter-attempt time. Each bar shows its n. |
| `adaptation` | Adaptive sessions only: the robot's belief (receptive / frustrated / disengaging) after each failure, the response it chose, the participant's decision and the reward, with the baseline schedule shaded. |

## Tables (`analysis/output/<session>/`)

| File | Content |
|---|---|
| `events.csv` | All events of the session (the `events` table). |
| `emotion_intervals.csv` | One row per stable emotion state: face, emotion, start, end, duration. |
| `failures.csv` | Each failure message with its condition, failure type, the emotion just before it, and the non-neutral emotions starting within 5 s after it. |
| `emotion_share.csv` | Seconds and fraction per emotion per block. |
| `trial_summary.csv` | Per trial: robot actions and emotions (`hrc_log/queries.sql`). |
| `failure_episodes.csv` | One row per failure message: response a1-a5, phase (fixed/baseline/adaptive), decision, decision latency, dominant emotion, and the belief and reward (adaptive). |
| `persistence.csv` | Per task (item in a block): failures, attempts, outcome, time to abandonment, mean inter-attempt time. |
| `outcomes.csv` | Continuation rate, alternative acceptance, retry rate, decision latency per condition/response. |
| `completion.csv` | Per condition, over failed tasks: outcome shares, completion rate, attempts, time to abandonment, inter-attempt time. |

**Metric definitions.**
- *Continuation rate*: failures not followed by giving up.
- *Alternative acceptance*: accepted ÷ failures where an alternative was
  offered.
- *Task completion*: the item was delivered, replaced by the alternative or
  fetched by the participant.
- *Time to abandonment*: from the first request of the item to giving up.
- *Inter-attempt time*: between successive requests or retries of the same
  item.
- *Decision latency*: from the end of the failure message to the decision.

## Code

```text
data.py           load a session and reshape it (intervals, blocks, failures, shares)
plot_session.py   the three figures
summary.py        CSV export and printed summary
metrics.py        persistence and interaction-outcome metrics
tests/            synthetic-session tests
```

Both output folders contain participant data and are git-ignored.
