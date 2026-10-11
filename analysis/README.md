# Analysis

Plots and tables for the shared game + facial-emotion database (`data/hrc.db`).
All times are `t_session`: seconds since the shared session start, the common timeline of game and emotion events. The database is opened read-only.

## Setup (own virtual environment)

```bash
python3 -m venv analisys/.venv
analysis/.venv/bin/pip install -r analisys/requirements.txt
```

## Use (from the repository root)

```bash
analysis/.venv/bin/python -m analisys.plot_session            # latest session
analysis/.venv/bin/python -m analisys.plot_session --session ID --formats png
analysis/.venv/bin/python -m analisys.summary                 # CSV export + printed summary
analysis/.venv/bin/python -m pytest analisys/tests -q
```

`--db PATH` (or `$HRC_DB`) selects another database. Session ids are listed by
`python3 -m hrc_log check`.

## Figures (`analisys/figures/<session>/`, PNG and PDF)

| File | Shows |
|---|---|
| `timeline` | Top: the stable facial emotion per detected face, one row per emotion (neutral in grey; blank = no face). Bottom: game events per actor (robot, human, system). Shaded backgrounds are the blocks, labelled with their condition. Dashed red lines mark failure messages, labelled with the failure type. |
| `failure_locked` | The emotion from 5 s before to 15 s after each failure message, one panel per failure, ordered by condition. |
| `emotion_share` | Share of observed (face-visible) time per emotion in each block. |

## Tables (`analisys/output/<session>/`)

| File | Content |
|---|---|
| `events.csv` | All events of the session (the `events` table). |
| `emotion_intervals.csv` | One row per stable emotion state: face, emotion, start, end, duration. |
| `failures.csv` | Each failure message with its condition, failure type, the emotion just before it, and the non-neutral emotions starting within 5 s after it. |
| `emotion_share.csv` | Seconds and fraction per emotion per block. |
| `trial_summary.csv` | Per trial: robot actions and emotions (`hrc_log/queries.sql`). |

## Code

```text
data.py           load a session and reshape it (intervals, blocks, failures, shares)
plot_session.py   the three figures
summary.py        CSV export and printed summary
tests/            synthetic-session tests
```

Both output folders contain participant data and are git-ignored.
