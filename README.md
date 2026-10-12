# Home-care robot: communicating failure

Pygame simulation for our HRC research project (Group 5). The participant plays an older adult with reduced mobility. A home-care robot fetches items for them and sometimes fails. We manipulate **how the robot communicates that failure**, extending Kwon et al. (2018) to failures that are not about the end-effector position (perception, manipulation, navigation).

## Run

The game and the facial-emotion recogniser (`FEmotion/`) each have their own virtual environment. Set them up once:

```bash
python3 -m venv game/.venv && game/.venv/bin/pip install -r requirements.txt
python3 -m venv FEmotion/.venv && FEmotion/.venv/bin/pip install -r FEmotion/requirements.txt
FEmotion/.venv/bin/python FEmotion/scripts/download_models.py
```

**One command for a study session** (from the repository root, any Python 3.10+):

```bash
python3 run_session.py --pid P01                     # game + emotion recognition
python3 run_session.py --pid P01 -- --fullscreen     # args after -- go to the game
python3 run_session.py --pid TEST --no-femotion -- --fast 4 --echo
```

The launcher creates one session, starts both processes with it, stops FEmotion when the game closes, and marks the session `completed` or `aborted`. If FEmotion is missing or crashes, the game keeps running.

**Or start them by hand** with the same session id (two terminals):

```bash
export HRC_SESSION_ID=$(python3 -m hrc_log new-session --participant P01)
game/.venv/bin/python -m game.main --pid P01            # terminal 1 (repo root)
cd FEmotion && .venv/bin/python -m femotion             # terminal 2 (same HRC_SESSION_ID)
python3 -m hrc_log end-session $HRC_SESSION_ID          # afterwards
```

`--session-id ID` and `--db PATH` work on both programs instead of the `HRC_SESSION_ID` and `HRC_DB` environment variables. Without a session id, each program starts its own session (e.g. `python -m game.main --pid P01` alone).

| Option | Meaning |
|---|---|
| `--pid P07` | Participant id. |
| `--balanced` | Pick the condition order from the participant number instead of at random. |
| `--order 3` | Force a condition order (0-5), e.g. to redo a run. |
| `--no-tutorial` | Skip the practice block. |
| `--tts` | Speak robot lines aloud (`pip install pyttsx3`). |
| `--mute` | Turn off the cue sounds. |
| `--fullscreen` | Fullscreen, scaled to the display. |
| `--echo` | Also print every log row to the console. |
| `--session-id ID` | Join this shared session (default `$HRC_SESSION_ID`, else a new one). |
| `--db PATH` | Shared SQLite database (default `$HRC_DB`, else `data/hrc.db`). |
| `--csv` | Also write the old per-session CSV to `logs/`. |
| `--fast 4` | Run 4x faster. For testing only, never in the study. |

**Controls.** Participants use the mouse or number keys for the dialog and the mouse for the activities. The researcher presses ENTER on the block-end screens (the questionnaire is filled in there). Pressing ESC twice quits and logs `session_aborted`.

## Session structure

Practice (3 items, all succeed), then three parts: Morning (A), Afternoon (B) and Evening (C). Each part has 6 items: 3 succeed and 3 fail, with one perception, one manipulation and one navigation failure. Each part uses one condition:

| Condition | What the robot does after a failure |
|---|---|
| `silent` | Returns empty-handed with a sad face and says nothing. |
| `explanation` | Sad face and says why it failed. |
| `explanation_alternative` | Says why and offers an alternative (an extra button). |

The condition order is one of the 6 possible orders (`config/counterbalance.json`). By default each session picks one **at random**. With `--balanced`, the order comes from the participant number (P01 gets order 0, P02 order 1, and P07 wraps back to order 0), so every group of 6 participants covers each order exactly once. Either way, the order is logged in the `session_start` row and in the `order` column.

After a failure the participant can choose **Try again** (up to 5 attempts), **accept the alternative** (only in `explanation_alternative`), **I'll get it myself** (always takes 30 s, wherever the item is), **Something else** (ask for another item), or **Never mind**. The failure feedback is shown for the same 3 seconds in every condition before the choices appear. The message stays in the speech bubble while the participant decides.

Every item also unlocks an activity that uses it ("Put on your reading glasses", "Drink the tea"). The activity stays **locked until the participant has the item**: brought by the robot, replaced by the robot's alternative (the activity changes to match, e.g. "Put on the spare glasses"), or fetched themselves. Giving up on an item skips its activity. Once unlocked, clicking it opens a short hands-on interaction with the item, one at a time:

| Type | What you do | Used for |
|---|---|---|
| `hold` | Hold the mouse on the item (3 s, `HOLD_SECONDS`) | Drinking, pouring |
| `tap` | Click the item a few times, with a short pause between clicks (`TAP_COOLDOWN`) | Taking a bite, turning a page |
| `drag` | Drag the item onto yourself | Glasses on your face, blanket on, slippers on |
| `sequence` | Press buttons in the order shown | Dialling a number, the TV remote, a crossword |
| `slider` | Drag a dial into the green zone and leave it there | Tuning the radio |

Each takes a few seconds and none have wrong answers: a wrong move just does nothing. Each item's interaction is set under `do` in `items.json` (alternatives have their own). **A part ends when every item is resolved and every unlocked activity is done.**

This makes the human's part depend directly on the robot's deliveries. It cannot be done ahead of the robot, it needs very little attention, and it has no wrong answers (so it cannot cause frustration that could be confused with frustration about the robot). Activities pause while the avatar walks. The activity texts are in `items.json` (`use`).

### Screen layout

The house map (top left) is an ambient view of where the robot is. Your list, the timer and the robot's screen are to its right. **Everything the participant acts on sits side by side in the bottom band:** the robot's status, what it just said and the answer buttons on the left, and the activities on the right. The robot's message also appears in its speech bubble on the map. Layout sizes are in `settings.py`.

### Attention cues

These cues help the participant keep track of the robot while working on the activities. They are identical in every condition and never reveal *whether* or *why* the robot failed.

| Moment | Sound | Visual |
|---|---|---|
| Robot arrives back (success or failure) | Rising two-note chime | The yellow "The robot is back!" strip in the bottom band flashes. |
| Robot needs an answer or a new request | Double ping | Blue strip, pulsing ring around the robot, and a pulsing dialog panel. |
| Still waiting after 8 s | One reminder ping per wait | (same as above) |
| Activity finished / all activities done | Soft two-note tone / short melody | The row turns to "done". |

Each cue is logged as `system,cue,<name>`. You can tune `REMINDER_AFTER` and `SOUND_VOLUME` in `settings.py`.

## Adaptive mode (closed-loop robot)

```bash
python3 run_session.py --pid P05 -- --adaptive                   # MDP policy (default)
python3 run_session.py --pid P05 -- --adaptive --policy heuristic --balanced
```

Instead of a fixed condition per part, the robot chooses each failure response itself (Sense - Think - Act). The fixed-condition mode above stays the default; `--adaptive` is a separate, between-subjects mode.

| Action | Robot response | Logged `feedback_type` |
|---|---|---|
| `a1` | Fail silently | `silent` |
| `a2` | Explain inability | `explanation` |
| `a3` | Explain and propose an alternative (alternative button shown) | `explanation_alternative` |
| `a4` | Explain and offer to try again | `explanation_retry` |
| `a5` | Explain and apologise | `explanation_apology` |

**Sense.** After each failure the robot takes the window from its failure message to the participant's decision. It reads the participant's stable facial emotions in that window from the shared database, where FEmotion writes them, and it records the decision (`retry`, `accept_alt`, `self`, `switch` = something else, or `give_up` = abandon) and how long the participant took to decide.

**Think: state.** A hidden Markov model keeps a belief over *receptive*, *frustrated* and *disengaging*, updated once per failure, so a single facial reading only nudges it.

- Emotion is soft evidence: confidence-weighted time in each emotion.
- Fear and surprise, low confidence and "no face" carry no evidence.
- Retries count as engagement. Long pauses and giving up point to disengaging.

**Think: decision.**

- **Baseline:** the first 5 failures use every response once, in a counterbalanced order (Williams design, 10 orders). `--balanced` picks the order by participant number and `--order N` forces one; otherwise it is random.
- **Then** the policy decides:
  - `heuristic`: ordered rules, e.g. offer the alternative when frustration rises and apologise when the user seems to disengage.
  - `mdp`: a small MDP over (state, response). It is solved on a Thompson sample of what the robot has learned about this user and applied to the belief (QMDP).

**Adapt.** After every failure the robot updates how this user's state responds to each response (Dirichlet counts) and how rewarding each response was.
- The reward is task progress, plus engagement (P(receptive) − P(disengaging)), plus facial valence, minus a small cost for longer   messages.
- Learning is per session, starting from hand-set priors.

| BDI | In the code (`game/adaptive/mind.py`) |
|---|---|
| Beliefs | user-state belief, task status, alternative availability, outcome history, learned per-user model and its uncertainty |
| Desires | reward weights: task progress, engagement, low frustration |
| Intentions | the chosen response for this failure, with phase, policy and rationale |

**Configuration.** All probabilities, rules and weights are in `game/config/adaptive.json`. They are documented hypotheses, not fitted values. `--seed` makes a run reproducible; the seed is logged either way.

**Log events.** In adaptive mode the log has three extra kinds of event:
- `policy_decision`: the response with its belief, scores and rationale.
- `feedback_start`: carries `{robot_action, phase, policy}`.
- `belief_update`: after each decision, with the observation, the belief before and after, the reward and the learned model.

The session's `session_start` row records `mode`, `policy`, `baseline` and `seed`.

Without FEmotion the robot adapts on behaviour alone.

## Log format

The game and FEmotion write to one SQLite database, `data/hrc.db` (git-ignored because it contains participant data), via the shared standard-library package `hrc_log/`. Each event is one row of `events`; `sessions` holds one row per session and `session_sources` one row per process that joined it. The schema is in `hrc_log/schema.sql`.

**Time.** Every row stores the time at which the event was *observed*: `t_wall` (`time.time()`), `t_mono` (`time.monotonic()`) and `t_session`, seconds since the shared session start. `t_session` uses the monotonic clock when the row was written on the same machine and boot as the session start (`clock_basis = 'mono'`) and the wall clock otherwise (`'wall'`). Sort by `t_session, seq` to get one timeline of game and emotion events.

| Column | Content |
|---|---|
| `session_id`, `source` (`game`/`femotion`), `event_type`, `seq` | Which session, which program, what happened, order within that program run. |
| `t_wall`, `t_mono`, `t_session`, `clock_basis`, `t_iso` | See above. `t_iso` is UTC. |
| `t_game` | Seconds since the game started (the old CSV `t_session`). |
| `participant`, `order`, `block_index`, `block_id`, `condition` | Context of the row. |
| `actor` | `robot`, `human` or `system`. |
| `action` | See below. |
| `item` | Item id being worked on (empty for mini-game rows). |
| `attempt` | Attempt number for that item (1, 2, ...). |
| `feedback_type` | Set on `feedback_start`: `silent`, `explanation`, `explanation_alternative`, `success`, `success_alternative`, `alternative_action`. |
| `detail` | The spoken text, destination, failure type, etc. |
| `task_id`, `trial_id` | `<block_id>:<item>` and `<block_id>:<item>:<attempt>`, for joins. |
| `robot_state` | Robot controller state (`game/core/state_machine.py` `State`) when the row was logged. |
| `face_id`, `previous_emotion`, `emotion`, `confidence`, `duration_ms` | FEmotion transitions (`event_type = emotion_transition`); `emotion` NULL = face lost. |
| `payload` | JSON for anything else. |

With `--csv` the game also writes the old file `logs/<pid>_<date>_<time>.csv`
with the columns `t_unix`, `t_iso`, `t_session`, `participant` ... `detail`.

**Actions:**

- **Human:** `request_item`, `retry`, `accept_alternative`,
  `do_it_myself`, `self_pickup`, `self_fetch_done`, `switch_request`,
  `give_up`, `activity_start`, `activity_step` (each bite, digit, etc.),
  `activity_done`, `activity_skipped`.
- **Robot:** `acknowledge`, `move_start`, `arrive`, `attempt_task`,
  `pick_up`, `task_failed`, `feedback_start`, `feedback_end`,
  `hand_over`.
- **System:** `session_start`, `block_start`, `item_resolved`,
  `activity_unlocked`, `cue`,
  `time_up`, `block_end`, `session_end`, `session_aborted`.

The key moment for the emotion analysis is `feedback_start` with a failure `feedback_type`. That is when the participant learns the robot failed.

**Checks and analysis queries** (`hrc_log/queries.sql`; default: latest session):

```bash
python3 -m hrc_log check [--session ID]      # integrity, counts, unclosed processes
python3 -m hrc_log query timeline            # game + emotion events on one timeline
python3 -m hrc_log query emotion_before_game_event
python3 -m hrc_log query trial_summary       # robot actions and emotions per trial
python3 -m hrc_log query all --session ID
```

**If something goes wrong.** Writes run on a background thread with a 5 s lock timeout and retries; rows that still cannot be stored are appended to `data/spool/*.jsonl` and imported later with `python3 -m hrc_log replay`. A process that crashed shows as `NOT CLOSED` in `check`; everything it logged before the crash is already in the database.

## Changing content

- `game/config/items.json`: items, where they are, the activity each one unlocks (`use`) and its interaction (`do`), and their failure explanation and alternative.
- `game/config/blocks.json`: which items appear in each part, whether they succeed.
- `game/config/counterbalance.json`: the condition orders.
- `game/settings.py`: speeds, timings, the attempt cap and the time limit.
- `game/robot/responses.py`: which parts of the message are said in which condition, and the adaptive responses a1-a5.
- `game/config/adaptive.json`: the adaptive model (priors, emission tables, rules, reward weights).

## Code layout

```text
run_session.py         starts game + FEmotion in one session
hrc_log/               shared SQLite event log (standard library only)
  schema.sql           tables, indexes, the emotion_events view
  writer.py            background writer, retries, spool
  queries.sql          validation / analysis queries
  migrate.py           import of old femotion.db / CSV files
game/
  main.py              screens, main loop, block sequencing
  settings.py          all tunable numbers
  config/              experiment content (JSON)
  core/
    state_machine.py   per-block interaction flow (the core logic)
    session.py         builds the plan from the configs
    world.py           house layout, furniture, named spots
    pathfinding.py     A*
    movement.py        smooth grid movement
    avatar.py          the participant's character
    logger.py          event log (shared database, optional CSV)
  adaptive/            adaptive mode: sensing, observations, HMM belief,
                       policies (baseline / heuristic / MDP), RobotMind (BDI)
  tests/               adaptive-model tests (no pygame needed)
  robot/
    robot.py           robot agent (face, carrying)
    responses.py       condition-dependent robot speech
  ui/
    renderer.py        all drawing
    dialog_panel.py    multiple-choice buttons
    minigame.py        activities with the fetched items
    interactions.py    the hands-on interactions (hold, tap, drag, ...)
    sounds.py          synthesised cue sounds
    speech.py          text wrapping, optional TTS
```

## Analysis

Timeline plots of game events and facial emotion, failure-locked emotion plots and CSV exports are in `analysis/` (own virtual environment; see `analysis/README.md`):

```bash
analysis/.venv/bin/python -m analysis.plot_session   # figures for the latest session
analysis/.venv/bin/python -m analysis.summary        # CSV tables + summary
```
