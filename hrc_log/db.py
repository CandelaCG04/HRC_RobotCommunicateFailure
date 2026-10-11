"""Connection, schema and session helpers for the shared SQLite database.

Standard library only, so both the game and the FEmotion virtual
environments can import it.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "hrc.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000

ENV_SESSION = "HRC_SESSION_ID"
ENV_DB = "HRC_DB"
SOURCES = ("game", "femotion")


def default_db_path() -> Path:
    """``$HRC_DB`` if set, else ``<repo>/data/hrc.db``."""
    return Path(os.environ.get(ENV_DB) or DEFAULT_DB)


def resolve_session_id(cli_value: str | None = None) -> str | None:
    """CLI value, else ``$HRC_SESSION_ID``, else None (caller creates one)."""
    return cli_value or os.environ.get(ENV_SESSION) or None


def new_session_id() -> str:
    return str(uuid.uuid4())


def iso_utc(t_wall: float) -> str:
    return datetime.fromtimestamp(t_wall, timezone.utc).isoformat(timespec="milliseconds")


def _read_boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip() or None
    except OSError:
        return None  # not Linux: monotonic times are never compared across processes


HOST = socket.gethostname()
BOOT_ID = _read_boot_id()


def connect(path: str | Path | None = None, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open the database, configure it for concurrent writers and create the schema.

    Autocommit mode (``isolation_level=None``): callers open explicit
    ``BEGIN IMMEDIATE`` transactions so lock waits happen up front.
    """
    path = Path(path) if path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=busy_timeout_ms / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    # WAL: readers never block the writer and two processes can interleave
    # short write transactions. NORMAL: no fsync per commit; the last commits
    # may be lost on power failure, never on an application crash.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _split_sql(ddl):
            conn.execute(statement)
        if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _split_sql(script: str) -> list[str]:
    """Split a DDL script into statements (no triggers, so ';' is a safe delimiter)."""
    lines = [line.split("--", 1)[0] for line in script.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def ensure_session(
    conn: sqlite3.Connection,
    session_id: str,
    created_by: str,
    participant: str | None = None,
    meta: dict | None = None,
    t0_wall: float | None = None,
    t0_mono: float | None = None,
    host: str | None = HOST,
    boot_id: str | None = BOOT_ID,
    status: str = "open",
) -> tuple[sqlite3.Row, bool]:
    """Create the session if it does not exist yet. Returns (row, created).

    ``t0_*``, ``host`` and ``boot_id`` default to now and this machine; they
    are passed explicitly when replaying spooled or legacy data.
    """
    if t0_wall is None:
        t0_wall, t0_mono = time.time(), time.monotonic()
    conn.execute("BEGIN IMMEDIATE")
    try:
        created = conn.execute(
            "INSERT INTO sessions (session_id, created_by, participant, t0_wall, t0_mono,"
            " host, boot_id, started_iso, status, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (session_id) DO NOTHING",
            (session_id, created_by, participant, t0_wall, t0_mono, host, boot_id,
             iso_utc(t0_wall), status, json.dumps(meta) if meta else None),
        ).rowcount == 1
        if participant and not created:
            conn.execute(
                "UPDATE sessions SET participant = COALESCE(participant, ?) WHERE session_id = ?",
                (participant, session_id),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return get_session(conn, session_id), created


def get_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()


def end_session(conn: sqlite3.Connection, session_id: str, status: str = "completed") -> bool:
    """Close an open session. Returns False if it was already closed."""
    return conn.execute(
        "UPDATE sessions SET ended_wall = ?, status = ? WHERE session_id = ? AND status = 'open'",
        (time.time(), status, session_id),
    ).rowcount == 1


def join_source(conn: sqlite3.Connection, writer_id: str, session_id: str, source: str,
                meta: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO session_sources (writer_id, session_id, source, pid, host, boot_id,"
        " joined_wall, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (writer_id) DO NOTHING",
        (writer_id, session_id, source, os.getpid(), HOST, BOOT_ID, time.time(),
         json.dumps(meta) if meta else None),
    )


def leave_source(conn: sqlite3.Connection, writer_id: str) -> None:
    conn.execute("UPDATE session_sources SET left_wall = ? WHERE writer_id = ?", (time.time(), writer_id))


def session_time(session, t_wall: float, t_mono: float | None, host: str | None,
                 boot_id: str | None) -> tuple[float, str]:
    """Seconds since the session start, and the clock used ('mono' or 'wall').

    Monotonic clocks are only comparable within one machine and boot, so the
    monotonic difference is used only when both match the session's creator;
    otherwise wall-clock time (subject to NTP adjustments) is the fallback.
    """
    if (t_mono is not None and session["t0_mono"] is not None and boot_id is not None
            and boot_id == session["boot_id"] and host == session["host"]):
        return t_mono - session["t0_mono"], "mono"
    return t_wall - session["t0_wall"], "wall"


def trial_ids(block_id, item, attempt) -> tuple[str | None, str | None]:
    """(task_id, trial_id): one list item in a block, and one attempt at it."""
    if block_id in (None, "") or item in (None, ""):
        return None, None
    task_id = f"{block_id}:{item}"
    if attempt in (None, ""):
        return task_id, None
    return task_id, f"{task_id}:{attempt}"
