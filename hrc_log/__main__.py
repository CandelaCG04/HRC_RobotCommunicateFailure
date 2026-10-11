"""Command line tools for the shared database.

    python -m hrc_log new-session [--participant P01]   # prints a session id
    python -m hrc_log end-session ID [--status aborted]
    python -m hrc_log migrate [--femotion-db PATH ...] [--csv PATH ...]
    python -m hrc_log replay                            # import spooled events
    python -m hrc_log check [--session ID]
    python -m hrc_log query <name|all> [--session ID] [--limit N]

``--db`` (or $HRC_DB) selects the database; default ``<repo>/data/hrc.db``.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from hrc_log import db
from hrc_log.migrate import migrate_csv, migrate_femotion
from hrc_log.writer import replay_spool

QUERIES_PATH = Path(__file__).resolve().parent / "queries.sql"


def load_queries(path: Path = QUERIES_PATH) -> dict[str, str]:
    """{name: sql} from the '-- name:' sections of queries.sql."""
    parts = re.split(r"^-- name:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), flags=re.M)
    return {name: sql.strip() for name, sql in zip(parts[1::2], parts[2::2])}


def print_rows(cursor, limit: int | None = None) -> None:
    headers = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    shown = rows if limit is None else rows[:limit]
    cells = [["" if v is None else str(v) for v in row] for row in shown]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    if len(shown) < len(rows):
        print(f"... {len(rows) - len(shown)} more rows")


def latest_session(conn) -> str | None:
    row = conn.execute("SELECT session_id FROM sessions WHERE status != 'legacy'"
                       " ORDER BY t0_wall DESC LIMIT 1").fetchone()
    return row[0] if row else None


def cmd_new_session(conn, args):
    session_id = args.session_id or db.new_session_id()
    db.ensure_session(conn, session_id, "cli", args.participant)
    print(session_id)


def cmd_end_session(conn, args):
    if not db.end_session(conn, args.session_id, args.status):
        print(f"session {args.session_id} not found or already closed", file=sys.stderr)
        return 1


def cmd_migrate(conn, args):
    femotion = args.femotion_db
    csvs = args.csv
    if not femotion and not csvs:   # defaults: the pre-unification locations
        legacy_db = db.REPO_ROOT / "FEmotion" / "femotion.db"
        femotion = [legacy_db] if legacy_db.exists() else []
        csvs = sorted((db.REPO_ROOT / "logs").glob("*.csv"))
    for path in femotion or []:
        print(migrate_femotion(conn, path, backup=not args.no_backup))
    for path in csvs or []:
        print(migrate_csv(conn, path))


def cmd_replay(conn, args):
    spool = Path(args.spool_dir) if args.spool_dir else Path(args.db).parent / "spool"
    files = sorted(spool.glob("*.jsonl"))
    if not files:
        print(f"no spool files in {spool}")
    for path in files:
        print(f"{path.name}: {replay_spool(conn, path)} rows imported")


def cmd_check(conn, args):
    print("integrity_check:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    print("foreign_key_check:", len(conn.execute("PRAGMA foreign_key_check").fetchall()), "violations")
    spool = Path(args.db).parent / "spool"
    pending = sorted(spool.glob("*.jsonl"))
    print(f"pending spool files: {len(pending)}" + (" (run: python -m hrc_log replay)" if pending else ""))
    print()
    print_rows(conn.execute(
        "SELECT s.session_id, s.participant, s.status, s.started_iso,"
        " (SELECT COUNT(*) FROM events e WHERE e.session_id = s.session_id AND e.source = 'game') AS game,"
        " (SELECT COUNT(*) FROM events e WHERE e.session_id = s.session_id AND e.source = 'femotion')"
        " AS femotion,"
        " (SELECT COUNT(*) FROM session_sources x WHERE x.session_id = s.session_id"
        "  AND x.left_wall IS NULL) AS unclosed"
        " FROM sessions s ORDER BY s.t0_wall"))
    session = args.session or latest_session(conn)
    if session:
        print(f"\nsession {session}")
        queries = load_queries()
        for name in ("counts", "sources", "integrity"):
            print(f"\n[{name}]")
            print_rows(conn.execute(queries[name], {"session": session}))


def cmd_query(conn, args):
    queries = load_queries()
    session = args.session or latest_session(conn)
    names = list(queries) if args.name == "all" else [args.name]
    for name in names:
        if name not in queries:
            print(f"unknown query '{name}'; one of: {', '.join(queries)}", file=sys.stderr)
            return 1
        print(f"\n[{name}]  session {session}")
        print_rows(conn.execute(queries[name], {"session": session}), args.limit)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hrc_log", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(db.default_db_path()))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new-session")
    p.add_argument("--participant")
    p.add_argument("--session-id", help="use this id instead of a new UUID")
    p.set_defaults(func=cmd_new_session)

    p = sub.add_parser("end-session")
    p.add_argument("session_id")
    p.add_argument("--status", default="completed", choices=("completed", "aborted"))
    p.set_defaults(func=cmd_end_session)

    p = sub.add_parser("migrate")
    p.add_argument("--femotion-db", action="append", help="legacy femotion.db (repeatable)")
    p.add_argument("--csv", action="append", help="legacy game CSV (repeatable)")
    p.add_argument("--no-backup", action="store_true")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("replay")
    p.add_argument("--spool-dir")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("check")
    p.add_argument("--session")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("query")
    p.add_argument("name")
    p.add_argument("--session")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_query)

    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    try:
        return args.func(conn, args) or 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
