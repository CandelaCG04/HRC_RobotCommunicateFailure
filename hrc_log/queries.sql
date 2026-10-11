-- Validation / analysis queries. Run with:
--   python -m hrc_log query <name|all> [--session ID]
-- Each query starts with a "-- name:" line and takes the :session parameter.

-- name: timeline
-- Game and emotion events on one shared session timeline.
SELECT printf('%.3f', t_session) AS t, source, clock_basis AS clock, event_type,
       actor, item, attempt, robot_state, previous_emotion, emotion,
       round(confidence, 2) AS conf, face_id
FROM events
WHERE session_id = :session
ORDER BY t_session, source, seq;

-- name: emotion_before_game_event
-- The latest emotion observation (any face) at or before each game event.
SELECT printf('%.3f', g.t_session) AS t, g.actor, g.action, g.item, g.attempt,
       e.emotion AS emotion, round(e.confidence, 2) AS conf, e.face_id,
       round(g.t_session - e.t_session, 3) AS emotion_age_s   -- NULL: no observation yet
FROM events g
LEFT JOIN events e ON e.event_id = (
    SELECT x.event_id FROM events x
    WHERE x.session_id = g.session_id AND x.source = 'femotion'
      AND x.t_session <= g.t_session
    ORDER BY x.t_session DESC, x.seq DESC
    LIMIT 1)
WHERE g.session_id = :session AND g.source = 'game'
ORDER BY g.t_session, g.seq;

-- name: trial_summary
-- Per trial (one attempt at one item): robot actions in order, the emotion
-- at the start of the trial and the emotion transitions during it.
WITH trial AS (
    SELECT session_id, trial_id, block_id, condition, item, attempt,
           MIN(t_session) AS t_start, MAX(t_session) AS t_end,
           MAX(feedback_type) AS feedback_type
    FROM events
    WHERE session_id = :session AND source = 'game' AND trial_id IS NOT NULL
    GROUP BY session_id, trial_id
)
SELECT t.trial_id, t.condition, printf('%.3f', t.t_start) AS t_start,
       printf('%.1f', t.t_end - t.t_start) AS dur_s,
       (SELECT group_concat(action, ' > ') FROM (
            SELECT r.action FROM events r
            WHERE r.session_id = t.session_id AND r.trial_id = t.trial_id AND r.actor = 'robot'
            ORDER BY r.t_session, r.seq)) AS robot_actions,
       t.feedback_type,
       (SELECT x.emotion FROM events x
        WHERE x.session_id = t.session_id AND x.source = 'femotion' AND x.t_session <= t.t_start
        ORDER BY x.t_session DESC, x.seq DESC LIMIT 1) AS emotion_at_start,
       (SELECT group_concat(emotion, ' > ') FROM (
            SELECT coalesce(x.emotion, '(none)') AS emotion FROM events x
            WHERE x.session_id = t.session_id AND x.source = 'femotion'
              AND x.t_session > t.t_start AND x.t_session <= t.t_end
            ORDER BY x.t_session, x.seq)) AS emotions_during,
       (SELECT round(avg(x.confidence), 2) FROM events x
        WHERE x.session_id = t.session_id AND x.source = 'femotion'
          AND x.t_session > t.t_start AND x.t_session <= t.t_end) AS mean_conf
FROM trial t
ORDER BY t.t_start;

-- name: counts
-- Event counts and time range per source.
SELECT source, COUNT(*) AS n_events, COUNT(DISTINCT writer_id) AS n_runs,
       printf('%.3f', MIN(t_session)) AS first_t, printf('%.3f', MAX(t_session)) AS last_t,
       group_concat(DISTINCT clock_basis) AS clocks
FROM events
WHERE session_id = :session
GROUP BY source;

-- name: sources
-- Each process that joined the session; an empty 'left' means it crashed or is running.
SELECT s.source, s.pid, datetime(s.joined_wall, 'unixepoch') AS joined_utc,
       coalesce(datetime(s.left_wall, 'unixepoch'), 'NOT CLOSED') AS left_utc,
       (SELECT COUNT(*) FROM events e WHERE e.writer_id = s.writer_id) AS n_events
FROM session_sources s
WHERE s.session_id = :session
ORDER BY s.joined_wall;

-- name: integrity
-- Session-integrity checks; see README "Validation" for expected values.
SELECT 'status' AS check_name, status AS value FROM sessions WHERE session_id = :session
UNION ALL
SELECT 'game session_start rows', COUNT(*) FROM events
WHERE session_id = :session AND source = 'game' AND action = 'session_start'
UNION ALL
SELECT 'game end rows', coalesce(group_concat(action), 'none (crash?)') FROM events
WHERE session_id = :session AND source = 'game' AND action IN ('session_end', 'session_aborted')
UNION ALL
SELECT 'missing rows (seq gaps, see spool)', coalesce(SUM(gap), 0) FROM (
    SELECT MAX(seq) - COUNT(*) AS gap FROM events WHERE session_id = :session GROUP BY writer_id)
UNION ALL
SELECT 'events before session start', COUNT(*) FROM events
WHERE session_id = :session AND t_session < 0
UNION ALL
SELECT 'max |wall - mono| skew (s)', printf('%.3f', MAX(ABS((e.t_wall - s.t0_wall) - e.t_session)))
FROM events e JOIN sessions s USING (session_id)
WHERE e.session_id = :session AND e.clock_basis = 'mono'
UNION ALL
SELECT 'sources not closed', COUNT(*) FROM session_sources
WHERE session_id = :session AND left_wall IS NULL;
