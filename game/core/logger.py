"""Event log with one row per robot, human or system action.

Rows go to the shared SQLite database (``hrc_log``, table ``events``) that
the facial-emotion recogniser also writes to, under the same session id.
With ``csv=True`` the old CSV file is written as well.

Timestamps (captured when ``log`` is called):
    t_unix     wall-clock seconds since epoch (``time.time()``).
    t_session  in the CSV: seconds since the game started; stored in the
               database as ``t_game``. The database's own ``t_session`` is
               seconds since the shared session start (see hrc_log.db).
"""
import csv
import time
from datetime import datetime
from pathlib import Path

from hrc_log import EventWriter, trial_ids

FIELDS = (
    "t_unix", "t_iso", "t_session",
    "participant", "order", "block_index", "block_id", "condition",
    "actor", "action", "item", "attempt", "feedback_type", "detail",
)
CONTEXT_FIELDS = ("participant", "order", "block_index", "block_id",
                  "condition")


class EventLogger:
    """Writes events to the shared database and, optionally, to
    ``<log_dir>/<participant>_<date>_<time>.csv``."""

    def __init__(self, log_dir, participant, echo=False, db_path=None,
                 session_id=None, csv_log=False):
        self._writer = EventWriter(db_path, session_id, "game",
                                   participant=participant)
        self.session_id = self._writer.session_id
        self.db_path = self._writer.db_path
        self.path = None
        self._file = None
        if csv_log:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = log_dir / f"{participant}_{stamp}.csv"
            self._file = open(self.path, "w", newline="", encoding="utf-8")
            self._csv = csv.DictWriter(self._file, fieldnames=FIELDS)
            self._csv.writeheader()
        self._t0 = time.perf_counter()
        self._echo = echo
        self.context = {field: "" for field in CONTEXT_FIELDS}
        self.context["participant"] = participant

    def set_context(self, **fields):
        """Set values repeated on every following row (block, condition)."""
        unknown = set(fields) - set(CONTEXT_FIELDS)
        if unknown:
            raise KeyError(f"Unknown context fields: {unknown}")
        self.context.update(fields)

    def log(self, actor, action, item="", attempt="", feedback_type="",
            detail="", robot_state=""):
        """Write one event. ``actor`` is 'robot', 'human' or 'system'.
        ``robot_state`` is the block controller's state at that moment."""
        now, mono = time.time(), time.monotonic()
        t_game = time.perf_counter() - self._t0
        row = {
            "t_unix": f"{now:.3f}",
            "t_iso": datetime.fromtimestamp(now).isoformat(
                timespec="milliseconds"),
            "t_session": f"{t_game:.3f}",
            **self.context,
            "actor": actor,
            "action": action,
            "item": item,
            "attempt": attempt,
            "feedback_type": feedback_type,
            "detail": detail,
        }
        task_id, trial_id = trial_ids(self.context["block_id"], item, attempt)
        self._writer.enqueue(
            action, t_wall=now, t_mono=mono, **self.context, actor=actor,
            action=action, item=item, attempt=attempt,
            feedback_type=feedback_type, detail=detail, task_id=task_id,
            trial_id=trial_id, robot_state=robot_state, t_game=t_game)
        if self._file is not None:
            self._csv.writerow(row)
            self._file.flush()      # nothing is lost if the game crashes
        if self._echo:
            print(f"[{row['t_session']:>8}] {actor:<6} {action:<16} "
                  f"{item:<16} {feedback_type:<24} {detail}")

    def close(self, status=None):
        """Flush everything. ``status`` ('completed'/'aborted') ends the
        session only if the game created it (standalone run)."""
        self._writer.close(status)
        if self._file is not None and not self._file.closed:
            self._file.close()
