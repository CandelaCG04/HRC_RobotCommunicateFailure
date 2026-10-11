"""Non-blocking event writer: one background thread per process.

Callers ``enqueue`` events; the time is captured at that moment (or passed in
by the caller when the event was observed earlier). The writer thread inserts
the queue in short ``BEGIN IMMEDIATE`` transactions, retries while the other
process holds the write lock, and appends rows it cannot store to a JSONL
spool file (``python -m hrc_log replay`` imports them later), so no event is
dropped silently.
"""
from __future__ import annotations

import atexit
import itertools
import json
import logging
import os
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from hrc_log import db

log = logging.getLogger("hrc_log")

# Columns a caller may set (everything else is filled in by the writer).
EVENT_FIELDS = (
    "participant", "order", "block_index", "block_id", "condition",
    "actor", "action", "item", "attempt", "feedback_type", "detail",
    "task_id", "trial_id", "robot_state", "t_game",
    "face_id", "emotion", "previous_emotion", "confidence", "duration_ms",
    "payload",
)
ROW_COLUMNS = (
    "session_id", "source", "writer_id", "seq", "event_type",
    "t_wall", "t_mono", "t_session", "clock_basis", "t_iso",
) + EVENT_FIELDS
_QUOTED = ", ".join('"%s"' % c for c in ROW_COLUMNS)
# ON CONFLICT only skips duplicates (replays); CHECK/NOT NULL violations still raise.
INSERT_SQL = (
    f"INSERT INTO events ({_QUOTED}) VALUES ({', '.join('?' for _ in ROW_COLUMNS)}) "
    "ON CONFLICT (writer_id, seq) DO NOTHING"
)
_STOP = object()


def event_row(record: dict, session) -> tuple:
    """Turn a queued/spooled record into an ``events`` row for ``session``."""
    t_session, basis = db.session_time(
        session, record["t_wall"], record.get("t_mono"), record.get("host"), record.get("boot_id"))
    values = {
        **record,
        "t_session": t_session,
        "clock_basis": basis,
        "t_iso": db.iso_utc(record["t_wall"]),
    }
    return tuple(values.get(c) for c in ROW_COLUMNS)


class EventWriter:
    """Writes events of one ``source`` ('game' or 'femotion') to the shared database.

    Thread-safe: ``enqueue`` may be called from any thread. Never blocks on
    the database; the connection lives in the writer thread only.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        session_id: str | None = None,
        source: str = "game",
        *,
        created_by: str | None = None,
        participant: str | None = None,
        session_meta: dict | None = None,
        source_meta: dict | None = None,
        spool_dir: str | Path | None = None,
        batch_size: int = 200,
        flush_interval: float = 0.25,
        max_retries: int = 5,
        busy_timeout_ms: int = db.BUSY_TIMEOUT_MS,
    ):
        if source not in db.SOURCES:
            raise ValueError(f"source must be one of {db.SOURCES}")
        self.db_path = Path(db_path) if db_path else db.default_db_path()
        self.session_id = db.resolve_session_id(session_id) or db.new_session_id()
        self.source = source
        self.writer_id = str(uuid.uuid4())
        spool_dir = Path(spool_dir) if spool_dir else self.db_path.parent / "spool"
        self.spool_path = spool_dir / f"{self.session_id}_{source}_{self.writer_id[:8]}.jsonl"
        # Session zero if this writer ends up creating the session.
        self._t0 = (time.time(), time.monotonic())
        self._created_by = created_by or source
        self._participant = participant
        self._session_meta = session_meta
        self._source_meta = source_meta
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._busy_timeout_ms = busy_timeout_ms

        self.created: bool | None = None    # True if this writer created the session
        self.spooled = 0                    # rows written to the spool file
        self._conn: sqlite3.Connection | None = None
        self._session = None
        self._queue: queue.Queue = queue.Queue()
        self._seq = itertools.count(1)
        self._seq_lock = threading.Lock()
        self._spool_lock = threading.Lock()
        self._closed = False
        self._close_status: str | None = None
        self.ready = threading.Event()      # set once the database was tried
        self._thread = threading.Thread(target=self._run, name=f"hrc-log-{source}", daemon=True)
        self._thread.start()
        atexit.register(self._atexit)

    # ---------------------------------------------------------------- API
    def enqueue(self, event_type: str, *, t_wall: float | None = None,
                t_mono: float | None = None, **fields) -> None:
        """Queue one event. Pass ``t_mono`` (``time.monotonic()``) and/or
        ``t_wall`` when the event was observed before this call."""
        if t_wall is None and t_mono is None:
            t_wall, t_mono = time.time(), time.monotonic()
        elif t_wall is None:
            t_wall = time.time() - (time.monotonic() - t_mono)
        unknown = set(fields) - set(EVENT_FIELDS)
        if unknown:
            raise KeyError(f"Unknown event fields: {sorted(unknown)}")
        if isinstance(fields.get("payload"), dict):
            fields["payload"] = json.dumps(fields["payload"])
        with self._seq_lock:
            seq = next(self._seq)
        record = {
            "session_id": self.session_id, "source": self.source,
            "writer_id": self.writer_id, "seq": seq, "event_type": event_type,
            "t_wall": t_wall, "t_mono": t_mono,
            "host": db.HOST, "boot_id": db.BOOT_ID,
            "session_t0_wall": self._t0[0], "session_t0_mono": self._t0[1],
            **{k: (None if v == "" else v) for k, v in fields.items()},
        }
        if self._closed:
            log.warning("event after close, spooling: %s", event_type)
            self._spool([record])
        else:
            self._queue.put(record)

    def close(self, status: str | None = None, timeout: float = 10.0) -> None:
        """Flush, record that this source left, and end the session if this
        writer created it (``status`` defaults to 'completed')."""
        if self._closed:
            return
        self._close_status = status or "completed"
        self._closed = True
        self._queue.put(_STOP)
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.error("hrc_log writer did not finish within %.0f s; %d events still queued",
                      timeout, self._queue.qsize())
        atexit.unregister(self._atexit)

    def _atexit(self):
        # Reached only if the application never called close(): treat as aborted.
        self.close(status="aborted")

    # ------------------------------------------------------------- thread
    def _run(self) -> None:
        self._try_open()
        self.ready.set()
        stop = False
        while not stop:
            batch, stop = self._next_batch()
            if batch:
                self._write(batch)
        self._finish()

    def _try_open(self) -> bool:
        try:
            conn = db.connect(self.db_path, self._busy_timeout_ms)
            session, self.created = db.ensure_session(
                conn, self.session_id, self._created_by, self._participant,
                self._session_meta, *self._t0)
            db.join_source(conn, self.writer_id, self.session_id, self.source, self._source_meta)
        except (sqlite3.Error, OSError) as exc:
            log.error("cannot open %s (%s); events go to %s", self.db_path, exc, self.spool_path)
            return False
        self._conn, self._session = conn, session
        return True

    def _next_batch(self) -> tuple[list, bool]:
        try:
            first = self._queue.get(timeout=self._flush_interval)
        except queue.Empty:
            return [], False
        if first is _STOP:
            return [], True
        batch = [first]
        while len(batch) < self._batch_size:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _STOP:
                return batch, True
            batch.append(item)
        return batch, False

    def _write(self, batch: list) -> None:
        if self._conn is None and not self._try_open():
            self._spool(batch)
            return
        rows = [event_row(r, self._session) for r in batch]
        error = None
        for attempt in range(self._max_retries):
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.executemany(INSERT_SQL, rows)
                self._conn.execute("COMMIT")
                return
            except sqlite3.Error as exc:
                error = exc
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                busy = isinstance(exc, sqlite3.OperationalError) and (
                    "locked" in str(exc) or "busy" in str(exc))
                if not busy:
                    break
                time.sleep(min(0.05 * 2 ** attempt, 1.0))
        log.error("could not write %d events (%s); spooled to %s", len(batch), error, self.spool_path)
        self._spool(batch)

    def _spool(self, records: list) -> None:
        with self._spool_lock:
            try:
                self.spool_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.spool_path, "a", encoding="utf-8") as fh:
                    for record in records:
                        fh.write(json.dumps(record) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                self.spooled += len(records)
            except OSError:
                log.exception("LOST %d events: spool file %s not writable", len(records), self.spool_path)

    def _finish(self) -> None:
        if self._conn is None:
            return
        try:
            db.leave_source(self._conn, self.writer_id)
            if self.created:
                db.end_session(self._conn, self.session_id, self._close_status or "completed")
        except sqlite3.Error as exc:
            log.error("could not close session %s cleanly: %s", self.session_id, exc)
        finally:
            self._conn.close()
            self._conn = None


def replay_spool(conn: sqlite3.Connection, path: str | Path) -> int:
    """Insert the rows of one spool file (idempotent). Renames the file to
    ``*.replayed`` on success. Returns the number of new rows."""
    path = Path(path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    inserted = 0
    sessions = {}
    for record in records:
        sid = record["session_id"]
        if sid not in sessions:
            # Recreate the session row if the database was unreachable when it started.
            sessions[sid], _ = db.ensure_session(
                conn, sid, record["source"], t0_wall=record["session_t0_wall"],
                t0_mono=record["session_t0_mono"], host=record.get("host"),
                boot_id=record.get("boot_id"))
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = conn.total_changes
        conn.executemany(INSERT_SQL, [event_row(r, sessions[r["session_id"]]) for r in records])
        inserted = conn.total_changes - before
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    path.rename(path.with_suffix(path.suffix + ".replayed"))
    return inserted
