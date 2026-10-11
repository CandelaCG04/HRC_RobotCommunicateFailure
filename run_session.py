"""Start the game and the facial-emotion recogniser in one shared session.

Usage (from the repository root, with any Python 3.10+)::

    python3 run_session.py --pid P01                      # game + FEmotion
    python3 run_session.py --pid P01 --show -- --fullscreen --tts
    python3 run_session.py --pid TEST --no-femotion -- --fast 4 --echo

Arguments after ``--`` go to the game. The launcher creates the session,
passes it to both processes through $HRC_SESSION_ID and $HRC_DB, and each
process runs in its own virtual environment. If FEmotion is missing or
crashes, the game keeps running. When the game exits, FEmotion is stopped
(SIGINT, its normal shutdown path) and the session is marked completed or
aborted.
"""
import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from hrc_log import db

ROOT = Path(__file__).resolve().parent
GAME_PY = ROOT / "game" / ".venv" / "bin" / "python"
FEMOTION_DIR = ROOT / "FEmotion"
FEMOTION_PY = FEMOTION_DIR / ".venv" / "bin" / "python"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pid", required=True, help="participant id, e.g. P07")
    parser.add_argument("--db", default=str(db.default_db_path()))
    parser.add_argument("--session-id", default=None,
                        help="reuse/join this session id (default: new)")
    parser.add_argument("--no-femotion", action="store_true",
                        help="run the game without emotion recognition")
    parser.add_argument("--show", action="store_true",
                        help="show FEmotion's camera debug window")
    parser.add_argument("--game-python", default=str(GAME_PY))
    parser.add_argument("--femotion-python", default=str(FEMOTION_PY))
    parser.add_argument("game_args", nargs=argparse.REMAINDER,
                        help="-- followed by extra game arguments")
    args = parser.parse_args(argv)
    if args.game_args[:1] == ["--"]:
        args.game_args = args.game_args[1:]
    return args


def _default_sigint():
    # Children of a backgrounded/nohup launcher inherit an ignored SIGINT;
    # restore it so stop() can shut FEmotion down cleanly.
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def stop(proc, name, timeout=10.0):
    """Ask ``proc`` to shut down cleanly, then force it."""
    if proc is None or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        print(f"[launcher] {name} did not stop; terminating", file=sys.stderr)
        proc.terminate()
        proc.wait(5)


def game_outcome(conn, session_id):
    """'completed' if the game logged session_end, else 'aborted'."""
    row = conn.execute(
        "SELECT action FROM events WHERE session_id = ? AND source = 'game'"
        " AND action IN ('session_end', 'session_aborted')"
        " ORDER BY t_session DESC LIMIT 1", (session_id,)).fetchone()
    return "completed" if row and row[0] == "session_end" else "aborted"


def main(argv=None):
    args = parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    popen_kw = {"preexec_fn": _default_sigint} if os.name == "posix" else {}
    conn = db.connect(args.db)
    session_id = args.session_id or db.new_session_id()
    db.ensure_session(conn, session_id, "launcher", args.pid,
                      {"game_args": args.game_args, "femotion": not args.no_femotion})
    print(f"[launcher] session {session_id} -> {args.db}")
    env = {**os.environ, db.ENV_SESSION: session_id, db.ENV_DB: str(Path(args.db).resolve())}

    femotion = None
    if not args.no_femotion:
        if Path(args.femotion_python).exists():
            cmd = [args.femotion_python, "-m", "femotion"] + (["--show"] if args.show else [])
            femotion = subprocess.Popen(cmd, cwd=FEMOTION_DIR, env=env, **popen_kw)
        else:
            print(f"[launcher] {args.femotion_python} not found; running without FEmotion",
                  file=sys.stderr)

    game = subprocess.Popen(
        [args.game_python, "-m", "game.main", "--pid", args.pid] + args.game_args,
        cwd=ROOT, env=env, **popen_kw)
    try:
        game.wait()
    except KeyboardInterrupt:
        # Ctrl+C also reached both children (same process group); let them finish.
        game.wait()
    finally:
        if femotion is not None and femotion.poll() is not None:
            print(f"[launcher] FEmotion exited early with code {femotion.returncode}",
                  file=sys.stderr)
        stop(femotion, "FEmotion")

    status = game_outcome(conn, session_id)
    db.end_session(conn, session_id, status)
    counts = dict(conn.execute(
        "SELECT source, COUNT(*) FROM events WHERE session_id = ? GROUP BY source",
        (session_id,)).fetchall())
    conn.close()
    print(f"[launcher] session {session_id} {status}: "
          f"{counts.get('game', 0)} game events, {counts.get('femotion', 0)} emotion events")
    print("[launcher] check with: python3 -m hrc_log check --session " + session_id)
    return game.returncode


if __name__ == "__main__":
    sys.exit(main())
