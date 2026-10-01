# Home-care robot: communicating failure

Pygame simulation for our HRC research project (Group 5). The participant
plays an older adult with reduced mobility. A home-care robot fetches
items for them and sometimes fails. We manipulate **how the robot
communicates that failure**, extending Kwon et al. (2018) to failures that
are not about the end-effector position (perception, manipulation,
navigation).

## Run

```bash
pip install -r requirements.txt
python -m game.main --pid P01
```

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
| `--fast 4` | Run 4x faster. For testing only, never in the study. |

**Controls.** Participants use the mouse or number keys for the dialog and
the mouse for the activities. The researcher presses ENTER on the
block-end screens (the questionnaire is filled in there). Pressing ESC
twice quits and logs `session_aborted`.

## Session structure

Practice (3 items, all succeed), then three parts: Morning (A), Afternoon
(B) and Evening (C). Each part has 6 items: 3 succeed and 3 fail, with one
perception, one manipulation and one navigation failure. Each part uses
one condition:

| Condition | What the robot does after a failure |
|---|---|
| `silent` | Returns empty-handed with a sad face and says nothing. |
| `explanation` | Sad face and says why it failed. |
| `explanation_alternative` | Says why and offers an alternative (an extra button). |

The condition order is one of the 6 possible orders
(`config/counterbalance.json`). By default each session picks one **at
random**. With `--balanced`, the order comes from the participant number
(P01 gets order 0, P02 order 1, and P07 wraps back to order 0), so every
group of 6 participants covers each order exactly once. Either way, the
order is logged in the `session_start` row and in the `order` column.

After a failure the participant can choose **Try again** (up to 5
attempts), **accept the alternative** (only in `explanation_alternative`),
**I'll get it myself** (always takes 30 s, wherever the item is),
**Something else** (ask for another item), or **Never mind**. The failure feedback is shown
for the same 3 seconds in every condition before the choices appear. The
message stays in the speech bubble while the participant decides.

Every item also unlocks an activity that uses it ("Put on your reading
glasses", "Drink the tea"). The activity stays **locked until the
participant has the item**: brought by the robot, replaced by the
robot's alternative (the activity changes to match, e.g. "Put on the spare
glasses"), or fetched themselves. Giving up on an item skips its activity.
Once unlocked, one click starts it and it takes 6 seconds
(`ACTIVITY_TIME`), one at a time. **A part ends when every item is
resolved and every unlocked activity is done.**

This makes the human's part depend directly on the robot's deliveries.
It cannot be done ahead of the robot, it needs very little attention, and
it has no wrong answers (so it cannot cause frustration that could be
confused with frustration about the robot). Activities pause while the
avatar walks. The activity texts are in `items.json` (`use`).

### Screen layout

The house map (top left) is an ambient view of where the robot is. Your
list, the timer and the robot's screen are to its right. **Everything the
participant acts on sits side by side in the bottom band:** the robot's
status, what it just said and the answer buttons on the left, and the
activities on the right. The robot's message also appears in its speech
bubble on the map. Layout sizes are in `settings.py`.

### Attention cues

These cues help the participant keep track of the robot while working on
the activities. They are identical in every condition and never reveal
*whether* or *why* the robot failed.

| Moment | Sound | Visual |
|---|---|---|
| Robot arrives back (success or failure) | Rising two-note chime | The yellow "The robot is back!" strip in the bottom band flashes. |
| Robot needs an answer or a new request | Double ping | Blue strip, pulsing ring around the robot, and a pulsing dialog panel. |
| Still waiting after 8 s | One reminder ping per wait | (same as above) |
| Activity finished / all activities done | Soft two-note tone / short melody | The row turns to "done". |

Each cue is logged as `system,cue,<name>`. You can tune `REMINDER_AFTER`
and `SOUND_VOLUME` in `settings.py`.

## Log format

There is one CSV per session: `logs/<pid>_<date>_<time>.csv`. The folder is
git-ignored because it contains participant data.

| Column | Content |
|---|---|
| `t_unix` | Wall-clock time (`time.time()`). **Use this to align with the emotion recogniser**, which must log with the same clock. |
| `t_iso` | The same time, human-readable. |
| `t_session` | Seconds since the game started. |
| `participant`, `order`, `block_index`, `block_id`, `condition` | Context of the row. |
| `actor` | `robot`, `human` or `system`. |
| `action` | See below. |
| `item` | Item id being worked on (empty for mini-game rows). |
| `attempt` | Attempt number for that item (1, 2, ...). |
| `feedback_type` | Set on `feedback_start`: `silent`, `explanation`, `explanation_alternative`, `success`, `success_alternative`, `alternative_action`. |
| `detail` | The spoken text, destination, failure type, etc. |

**Actions:**

- **Human:** `request_item`, `retry`, `accept_alternative`,
  `do_it_myself`, `self_pickup`, `self_fetch_done`, `switch_request`,
  `give_up`, `activity_start`, `activity_done`, `activity_skipped`.
- **Robot:** `acknowledge`, `move_start`, `arrive`, `attempt_task`,
  `pick_up`, `task_failed`, `feedback_start`, `feedback_end`,
  `hand_over`.
- **System:** `session_start`, `block_start`, `item_resolved`,
  `activity_unlocked`, `cue`,
  `time_up`, `block_end`, `session_end`, `session_aborted`.

The key moment for the emotion analysis is `feedback_start` with a failure
`feedback_type`. That is when the participant learns the robot failed.

## Changing content

- `game/config/items.json`: items, where they are, the activity each one
  unlocks (`use`), and their failure explanation and alternative.
- `game/config/blocks.json`: which items appear in each part, whether
  they succeed.
- `game/config/counterbalance.json`: the condition orders.
- `game/settings.py`: speeds, timings, the attempt cap and the time
  limit.
- `game/robot/responses.py`: which parts of the message are said in which
  condition.

## Code layout

```
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
    logger.py          CSV event log
  robot/
    robot.py           robot agent (face, carrying)
    responses.py       condition-dependent robot speech
  ui/
    renderer.py        all drawing
    dialog_panel.py    multiple-choice buttons
    minigame.py        activities with the fetched items
    sounds.py          synthesised cue sounds
    speech.py          text wrapping, optional TTS
```