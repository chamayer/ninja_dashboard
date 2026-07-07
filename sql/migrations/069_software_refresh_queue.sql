-- 069_software_refresh_queue.sql
-- Three software refresh queues.
--
-- Q1  software_scheduled_queue  one entry per Ninja org, filled by
--                                enqueue_all_orgs() on schedule
-- Q2  software_demand_queue     operator-triggered; fires immediately
--                                on enqueue, status tracked per job
-- Q3  software_activity_queue   device-level, filled by activity
--                                processor on SOFTWARE_* events
--
-- Q1 and Q3 share the background worker (Q3 drained first).
-- Q2 is processed in its own thread and never touched by the worker.
--
-- Dedup: one pending entry per df value per queue.
-- Retries: attempts / max_attempts columns; worker resets to pending
-- until max_attempts, then leaves as failed.
-- Lease: started_at allows recovery of stuck processing entries
-- (worker resets any processing row older than 30 min back to pending).
-- worker_id: reserved for future parallel workers.

CREATE TABLE IF NOT EXISTS ninja_core.software_scheduled_queue (
    id           BIGSERIAL    PRIMARY KEY,
    df           TEXT         NOT NULL,
    reason       TEXT         NOT NULL DEFAULT '',
    queued_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status       TEXT         NOT NULL DEFAULT 'pending',
    attempts     SMALLINT     NOT NULL DEFAULT 0,
    max_attempts SMALLINT     NOT NULL DEFAULT 3,
    worker_id    TEXT,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    rows_seen    INTEGER,
    error        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS software_scheduled_queue_pending_df_idx
    ON ninja_core.software_scheduled_queue (df)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS software_scheduled_queue_status_queued_idx
    ON ninja_core.software_scheduled_queue (status, queued_at);


CREATE TABLE IF NOT EXISTS ninja_core.software_demand_queue (
    id           BIGSERIAL    PRIMARY KEY,
    df           TEXT         NOT NULL,
    reason       TEXT         NOT NULL DEFAULT '',
    queued_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status       TEXT         NOT NULL DEFAULT 'pending',
    attempts     SMALLINT     NOT NULL DEFAULT 0,
    max_attempts SMALLINT     NOT NULL DEFAULT 3,
    worker_id    TEXT,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    rows_seen    INTEGER,
    error        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS software_demand_queue_pending_df_idx
    ON ninja_core.software_demand_queue (df)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS software_demand_queue_status_queued_idx
    ON ninja_core.software_demand_queue (status, queued_at DESC);


CREATE TABLE IF NOT EXISTS ninja_core.software_activity_queue (
    id           BIGSERIAL    PRIMARY KEY,
    df           TEXT         NOT NULL,
    reason       TEXT         NOT NULL DEFAULT '',
    queued_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status       TEXT         NOT NULL DEFAULT 'pending',
    attempts     SMALLINT     NOT NULL DEFAULT 0,
    max_attempts SMALLINT     NOT NULL DEFAULT 3,
    worker_id    TEXT,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    rows_seen    INTEGER,
    error        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS software_activity_queue_pending_df_idx
    ON ninja_core.software_activity_queue (df)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS software_activity_queue_status_queued_idx
    ON ninja_core.software_activity_queue (status, queued_at);
