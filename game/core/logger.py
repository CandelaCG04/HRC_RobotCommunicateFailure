"""Timestamped CSV log with one row per robot, human or system action.

Timestamps:
    t_unix     wall-clock seconds since epoch (``time.time()``); use this to
               align with the facial-expression recogniser, which should log
               with the same clock.
    t_session  seconds since the game started (monotonic, for durations).
"""
import csv
import time
from datetime import datetime
from pathlib import Path

FIELDS = (
    "t_unix", "t_iso", "t_session",
    "participant", "order", "block_index", "block_id", "condition",
    "actor", "action", "item", "attempt", "feedback_type", "detail",
)
CONTEXT_FIELDS = ("participant", "order", "block_index", "block_id",
                  "condition")


class EventLogger:
    """Writes events to ``<log_dir>/<participant>_<date>_<time>.csv``."""

    def __init__(self, log_dir, participant, echo=False):
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = log_dir / f"{participant}_{stamp}.csv"
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDS)
        self._writer.writeheader()
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
            detail=""):
        """Write one event. ``actor`` is 'robot', 'human' or 'system'."""
        now = time.time()
        row = {
            "t_unix": f"{now:.3f}",
            "t_iso": datetime.fromtimestamp(now).isoformat(
                timespec="milliseconds"),
            "t_session": f"{time.perf_counter() - self._t0:.3f}",
            **self.context,
            "actor": actor,
            "action": action,
            "item": item,
            "attempt": attempt,
            "feedback_type": feedback_type,
            "detail": detail,
        }
        self._writer.writerow(row)
        self._file.flush()      # nothing is lost if the game crashes
        if self._echo:
            print(f"[{row['t_session']:>8}] {actor:<6} {action:<16} "
                  f"{item:<16} {feedback_type:<24} {detail}")

    def close(self):
        if not self._file.closed:
            self._file.close()
