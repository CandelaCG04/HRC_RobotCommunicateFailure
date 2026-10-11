"""Shared SQLite event log for the game and FEmotion (standard library only).

    from hrc_log import EventWriter
    writer = EventWriter(source="game")      # session from --session-id / $HRC_SESSION_ID
    writer.enqueue("request_item", actor="human", item="newspaper")
    writer.close("completed")
"""
from hrc_log.db import (DEFAULT_DB, ENV_DB, ENV_SESSION, connect, default_db_path,
                        resolve_session_id, trial_ids)
from hrc_log.writer import EventWriter

__all__ = ["DEFAULT_DB", "ENV_DB", "ENV_SESSION", "EventWriter", "connect",
           "default_db_path", "resolve_session_id", "trial_ids"]
