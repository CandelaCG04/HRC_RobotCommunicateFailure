-- Unified event store shared by the game and FEmotion (one row per event).
-- Applied idempotently by hrc_log.db.connect(); bump SCHEMA_VERSION in db.py on change.

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

-- One experimental session. Created by whoever starts first (launcher, game or
-- FEmotion); the others join it. t0_* is the shared zero of the session timeline.
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_by   TEXT NOT NULL,             -- launcher | game | femotion | cli | migration
    participant  TEXT,
    t0_wall      REAL NOT NULL,             -- time.time() at creation
    t0_mono      REAL,                      -- time.monotonic() at creation (NULL for legacy)
    host         TEXT,                      -- machine and boot on which t0_mono is valid
    boot_id      TEXT,
    started_iso  TEXT NOT NULL,
    ended_wall   REAL,
    status       TEXT NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'completed', 'aborted', 'legacy')),
    meta         TEXT CHECK (meta IS NULL OR json_valid(meta))
);

-- One row per writer (process run) that joined a session. left_wall stays NULL
-- if the process crashed or is still running.
CREATE TABLE IF NOT EXISTS session_sources (
    writer_id    TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    source       TEXT NOT NULL CHECK (source IN ('game', 'femotion')),
    pid          INTEGER,
    host         TEXT,
    boot_id      TEXT,
    joined_wall  REAL NOT NULL,
    left_wall    REAL,
    meta         TEXT CHECK (meta IS NULL OR json_valid(meta))
);
CREATE INDEX IF NOT EXISTS idx_sources_session ON session_sources(session_id, source);

CREATE TABLE IF NOT EXISTS events (
    event_id         INTEGER PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions(session_id),
    source           TEXT NOT NULL CHECK (source IN ('game', 'femotion')),
    writer_id        TEXT NOT NULL,         -- process run that observed the event
    seq              INTEGER NOT NULL,      -- order within writer_id (tie-break, dedup)
    event_type       TEXT NOT NULL,         -- game: action; femotion: emotion_transition
    -- time, all captured when the event was observed (not when inserted)
    t_wall           REAL NOT NULL,         -- seconds since epoch
    t_mono           REAL,                  -- time.monotonic() on the writer's machine
    t_session        REAL NOT NULL,         -- seconds since sessions.t0_*
    clock_basis      TEXT NOT NULL CHECK (clock_basis IN ('mono', 'wall')),
    t_iso            TEXT NOT NULL,         -- UTC ISO-8601 of t_wall
    -- game CSV columns, same order as the CSV
    participant      TEXT,
    "order"          INTEGER,
    block_index      INTEGER,
    block_id         TEXT,
    condition        TEXT,
    actor            TEXT,                  -- robot | human | system | camera
    action           TEXT,
    item             TEXT,
    attempt          INTEGER,
    feedback_type    TEXT,
    detail           TEXT,
    -- added for joins
    task_id          TEXT,                  -- '<block_id>:<item>'
    trial_id         TEXT,                  -- '<block_id>:<item>:<attempt>'
    robot_state      TEXT,                  -- game.core.state_machine.State at log time
    t_game           REAL,                  -- the CSV's t_session (seconds since game start)
    -- emotion
    face_id          INTEGER,
    emotion          TEXT,                  -- NULL = face lost / state ended
    previous_emotion TEXT,
    confidence       REAL,
    duration_ms      INTEGER,               -- how long previous_emotion lasted
    payload          TEXT CHECK (payload IS NULL OR json_valid(payload)),
    UNIQUE (writer_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_timeline ON events(session_id, t_session, seq);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(session_id, source, t_session);
CREATE INDEX IF NOT EXISTS idx_events_trial ON events(session_id, trial_id);

-- Same columns as FEmotion's legacy emotion_events table, for old analysis code.
CREATE VIEW IF NOT EXISTS emotion_events AS
SELECT event_id AS id, session_id, face_id, t_iso AS timestamp, previous_emotion,
       emotion, confidence, duration_ms,
       CASE event_type WHEN 'frustration_transition' THEN 'frustration' ELSE 'emotion' END AS kind
FROM events
WHERE source = 'femotion';
