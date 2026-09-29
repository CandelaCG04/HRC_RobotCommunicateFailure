"""Interaction flow for one block: requests, fetching, feedback, decisions.

The controller is a small finite-state machine. It owns the robot and the
avatar for the block, decides what happens next and logs every robot,
human and system action. It never draws anything.

Flow of one request::

    CHOOSING -> ACKNOWLEDGING -> TO_TARGET -> WORKING -> RETURNING
      success -> DELIVERING -> CHOOSING
      failure -> FAIL_FEEDBACK -> DECIDING -> retry | accept alternative
                                              | do it myself | ask for
                                              something else | never mind
"""
from dataclasses import dataclass
from enum import Enum, auto

from game import settings
from game.core.avatar import Avatar
from game.robot import responses
from game.robot.robot import Robot


class State(Enum):
    CHOOSING = auto()
    ACKNOWLEDGING = auto()
    TO_TARGET = auto()
    WORKING = auto()
    RETURNING = auto()
    DELIVERING = auto()
    FAIL_FEEDBACK = auto()
    DECIDING = auto()
    SELF_OUT = auto()
    SELF_PICKUP = auto()
    SELF_BACK = auto()
    DONE = auto()


# How each item on the list ended up being resolved
PENDING = "pending"
DELIVERED = "delivered"
ALTERNATIVE = "alternative"
SELF = "self"
GAVE_UP = "gave_up"

TIMED_STATES = {State.ACKNOWLEDGING, State.WORKING, State.DELIVERING,
                State.FAIL_FEEDBACK, State.SELF_PICKUP}
ROBOT_TRIP_STATES = {State.ACKNOWLEDGING, State.TO_TARGET, State.WORKING,
                     State.RETURNING}
SELF_STATES = {State.SELF_OUT, State.SELF_PICKUP, State.SELF_BACK}


@dataclass
class Task:
    """One trip of the robot: where it goes and whether it will succeed."""
    item: object
    target_spot: str
    succeeds: bool
    carry_label: str
    is_alternative: bool = False


class BlockController:
    """Runs one block (one condition) of the experiment."""

    def __init__(self, block, world, logger, voice):
        self.block = block
        self.world = world
        self.logger = logger
        self.voice = voice
        self.items = {item.item_id: item for item in block.items}
        self.status = {item_id: PENDING for item_id in self.items}
        self.attempts = {item_id: 0 for item_id in self.items}
        self.robot = Robot(world, world.spot("robot_home"))
        self.avatar = Avatar(world, world.spot("avatar_seat"))
        self.state = State.CHOOSING
        self.timer = 0.0
        self.task = None
        self.current = None             # item currently being worked on
        self.robot_speech = ""
        self.pending_status = None      # status applied after DELIVERING
        self.elapsed = 0.0
        self._time_up_logged = False
        # Attention cues for the UI (sound + visuals), drained every frame
        self._cues = []
        self.cue_times = {}             # cue name -> self.elapsed when fired
        self._wait_time = 0.0
        self._reminded = False

    # ------------------------------------------------------------ queries
    @property
    def done(self):
        return self.state == State.DONE

    @property
    def accepts_input(self):
        return self.state in (State.CHOOSING, State.DECIDING)

    @property
    def hands_free(self):
        """False while the avatar walks (knitting pauses)."""
        return self.state not in SELF_STATES

    @property
    def waiting_for_user(self):
        """True when the robot is idle and needs a choice from the user."""
        return self.accepts_input and bool(self.pending_items())

    @property
    def phase(self):
        """Coarse, condition-neutral status for the attention cues."""
        if self.state in (State.DELIVERING, State.FAIL_FEEDBACK):
            return "back"
        if self.state == State.DECIDING:
            return "waiting_answer"
        if self.state == State.CHOOSING and self.pending_items():
            return "waiting_request"
        if self.state in SELF_STATES:
            return "self"
        if self.state in ROBOT_TRIP_STATES:
            return "busy"
        return "done"

    def pop_cues(self):
        cues, self._cues = self._cues, []
        return cues

    def seconds_since(self, cue):
        return self.elapsed - self.cue_times.get(cue, -1e9)

    @property
    def time_left(self):
        return max(0.0, settings.BLOCK_TIME_LIMIT - self.elapsed)

    def pending_items(self):
        return [item for item in self.block.items
                if self.status[item.item_id] == PENDING]

    def dialog_content(self):
        """Return (prompt, [(button label, action key), ...])."""
        if self.state == State.CHOOSING:
            options = [(item.name[0].upper() + item.name[1:],
                        f"request:{item.item_id}")
                       for item in self.pending_items()]
            return "What should the robot bring you?", options
        if self.state == State.DECIDING:
            return "What would you like to do?", self._decision_options()
        return self._status_text(), []

    def _decision_options(self):
        item = self.current
        options = []
        if self.attempts[item.item_id] < settings.MAX_ATTEMPTS:
            options.append(("Try again", "retry"))
        if responses.offers_alternative(self.block.condition):
            options.append((item.failure.alternative.button, "accept_alt"))
        options.append(("I'll get it myself", "self"))
        if len(self.pending_items()) > 1:
            options.append(("Something else", "switch"))
        options.append(("Never mind", "give_up"))
        return options

    def _status_text(self):
        if self.state in ROBOT_TRIP_STATES and self.task:
            if self.task.is_alternative:
                return f"The robot is getting the {self.task.carry_label}..."
            return f"The robot is getting your {self.current.name}..."
        if self.state in SELF_STATES:
            return f"You are getting your {self.current.name} yourself..."
        if self.state in (State.FAIL_FEEDBACK, State.DELIVERING):
            return "Please wait..."
        if self.state == State.DONE:
            return "Everything on your list is sorted!"
        return ""

    # ------------------------------------------------------------ input
    def handle_action(self, key):
        """Apply a dialog choice made by the participant."""
        if self.state == State.CHOOSING and key.startswith("request:"):
            item_id = key.split(":", 1)[1]
            if self.status.get(item_id) != PENDING:
                return
            self.current = self.items[item_id]
            self._start_attempt("request_item")
        elif self.state == State.DECIDING:
            handler = {
                "retry": self._on_retry,
                "accept_alt": self._on_accept_alternative,
                "self": self._on_self_fetch,
                "switch": self._on_switch,
                "give_up": self._on_give_up,
            }.get(key)
            if handler:
                handler()

    def _on_retry(self):
        if self.attempts[self.current.item_id] >= settings.MAX_ATTEMPTS:
            return
        self._start_attempt("retry")

    def _on_accept_alternative(self):
        alt = self.current.failure.alternative
        self._log("human", "accept_alternative", detail=alt.button)
        if alt.fetch_spot:
            task = Task(self.current, alt.fetch_spot, True, alt.item_name,
                        is_alternative=True)
            self._start_task(task,
                             responses.acknowledge_alternative(alt.item_name))
        else:
            # Alternative that needs no trip (e.g. switching on subtitles)
            self.robot.face = "happy"
            self._say(alt.reply)
            self._log("robot", "feedback_start",
                      feedback_type=responses.ALTERNATIVE_ACTION,
                      detail=alt.reply)
            self.pending_status = ALTERNATIVE
            self._enter(State.DELIVERING, settings.DELIVER_TIME)

    def _on_self_fetch(self):
        self._reset_robot_display()
        goal = self.world.spot(self.current.spot)
        path = self.avatar.plan(goal, extra_blocked={self.robot.tile})
        # Scale walking speed so the whole trip (there, pick up, back)
        # always takes SELF_FETCH_TIME seconds.
        walk_time = settings.SELF_FETCH_TIME - settings.SELF_PICKUP_TIME
        speed = 2 * (len(path) - 1) / walk_time
        self.avatar.set_speed(speed)
        self._log("human", "do_it_myself",
                  detail=f"tiles={len(path) - 1};speed={speed:.2f}")
        self.avatar.go_to(goal, extra_blocked={self.robot.tile})
        self._enter(State.SELF_OUT)

    def _on_switch(self):
        self._log("human", "switch_request")
        self._reset_robot_display()
        self.current = None
        self._enter(State.CHOOSING)

    def _on_give_up(self):
        self._log("human", "give_up")
        self._reset_robot_display()
        self._resolve(GAVE_UP)

    # ------------------------------------------------------------ update
    def update(self, dt):
        self.elapsed += dt
        if not self._time_up_logged and self.time_left <= 0:
            self._time_up_logged = True
            self.logger.log("system", "time_up")

        if self.waiting_for_user and settings.REMINDER_AFTER is not None:
            self._wait_time += dt
            due = self._wait_time >= settings.REMINDER_AFTER
            if due and not self._reminded:
                self._reminded = True
                self._cue("reminder")

        robot_arrived = self.robot.update(dt)
        avatar_arrived = self.avatar.update(dt)
        if self.state in TIMED_STATES:
            self.timer -= dt
        timer_done = self.timer <= 0
        state = self.state

        if state == State.ACKNOWLEDGING and timer_done:
            self._say("")
            self._move_robot(self.task.target_spot)
            self._enter(State.TO_TARGET)

        elif state == State.TO_TARGET and robot_arrived:
            self._log("robot", "arrive", detail=self.task.target_spot)
            self.robot.face = "thinking"
            self.robot.working = True
            self._log("robot", "attempt_task")
            self._enter(State.WORKING, settings.WORK_TIME)

        elif state == State.WORKING and timer_done:
            self.robot.working = False
            self.robot.face = "neutral"
            if self.task.succeeds:
                self.robot.carrying = self.task.carry_label
                self._log("robot", "pick_up", detail=self.task.carry_label)
            else:
                self._log("robot", "task_failed",
                          detail=self.current.failure.type)
            self._move_robot("robot_home")
            self._enter(State.RETURNING)

        elif state == State.RETURNING and robot_arrived:
            self._log("robot", "arrive", detail="robot_home")
            self._cue("robot_back")
            self._give_feedback()

        elif state == State.DELIVERING and timer_done:
            if self.robot.carrying:
                self._log("robot", "hand_over", detail=self.robot.carrying)
            self._log("robot", "feedback_end")
            self._reset_robot_display()
            self._resolve(self.pending_status)
            self._cue_if_waiting()

        elif state == State.FAIL_FEEDBACK and timer_done:
            self._log("robot", "feedback_end")
            self._enter(State.DECIDING)
            self._cue("input_needed")

        elif state == State.SELF_OUT and avatar_arrived:
            self.avatar.carrying = self.current.name
            self._log("human", "self_pickup")
            self._enter(State.SELF_PICKUP, settings.SELF_PICKUP_TIME)

        elif state == State.SELF_PICKUP and timer_done:
            self.avatar.go_to(self.avatar.seat,
                              extra_blocked={self.robot.tile})
            self._enter(State.SELF_BACK)

        elif state == State.SELF_BACK and avatar_arrived:
            self.avatar.carrying = None
            self._log("human", "self_fetch_done")
            self._resolve(SELF)
            self._cue_if_waiting()

    # ------------------------------------------------------------ helpers
    def _start_attempt(self, human_action):
        """Log the human's request/retry and send the robot off."""
        item = self.current
        self.attempts[item.item_id] += 1
        self._log("human", human_action)
        target = item.spot if item.succeeds else item.failure.stop_spot
        task = Task(item, target, item.succeeds, item.name)
        ack = responses.acknowledge(item.name, self.attempts[item.item_id])
        self._start_task(task, ack)

    def _start_task(self, task, ack_text):
        self.task = task
        self.robot.face = "neutral"
        self._say(ack_text)
        self._log("robot", "acknowledge", detail=ack_text)
        self._enter(State.ACKNOWLEDGING, settings.ACK_TIME)

    def _give_feedback(self):
        """Robot is back next to the user: show success or failure."""
        if self.task.succeeds:
            if self.task.is_alternative:
                feedback_type = responses.SUCCESS_ALTERNATIVE
                self.pending_status = ALTERNATIVE
            else:
                feedback_type = responses.SUCCESS
                self.pending_status = DELIVERED
            text = responses.deliver(self.task.carry_label,
                                     self.task.is_alternative)
            self.robot.face = "happy"
            self._say(text)
            self._log("robot", "feedback_start",
                      feedback_type=feedback_type, detail=text)
            self._enter(State.DELIVERING, settings.DELIVER_TIME)
        else:
            feedback_type, text = responses.failure_feedback(
                self.block.condition, self.current.failure)
            self.robot.face = "sad"
            self._say(text)
            self._log("robot", "feedback_start",
                      feedback_type=feedback_type,
                      detail=text or "(no message)")
            self._enter(State.FAIL_FEEDBACK, settings.FEEDBACK_TIME)

    def _move_robot(self, spot_name):
        self.robot.go_to(self.world.spot(spot_name),
                         extra_blocked={self.avatar.tile})
        self._log("robot", "move_start", detail=f"to={spot_name}")

    def _resolve(self, status):
        self.status[self.current.item_id] = status
        self._log("system", "item_resolved", detail=status)
        self.current = None
        self.task = None
        self._enter(State.DONE if not self.pending_items()
                    else State.CHOOSING)

    def _reset_robot_display(self):
        self.robot.face = "neutral"
        self.robot.carrying = None
        self._say("")

    def _enter(self, state, duration=0.0):
        self.state = state
        self.timer = duration
        self._wait_time = 0.0
        self._reminded = False

    def _cue(self, name):
        """Queue an attention cue; it is logged when the UI plays it."""
        self._cues.append(name)
        self.cue_times[name] = self.elapsed

    def _cue_if_waiting(self):
        """After the robot/avatar finishes on its own, call the user back."""
        if self.waiting_for_user:
            self._cue("input_needed")

    def _say(self, text):
        self.robot_speech = text
        if text:
            self.voice.say(text)

    def _log(self, actor, action, feedback_type="", detail=""):
        item_id = self.current.item_id if self.current else ""
        attempt = self.attempts[item_id] if item_id else ""
        self.logger.log(actor, action, item=item_id, attempt=attempt,
                        feedback_type=feedback_type, detail=detail)
