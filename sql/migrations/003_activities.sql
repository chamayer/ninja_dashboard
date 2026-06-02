-- =============================================================================
-- 003_activities.sql
-- Adds:
--   - ninja_core.ingest_state       — small key/value store for ingest cursors
--                                     (e.g. activities.last_id high-water mark)
--   - ninja_activities.activities   — Ninja's built-in event log, filtered.
--
-- Activities are NOT snapshot-style and NOT SCD-2. They're immutable
-- events with stable IDs from Ninja — insert-once, dedup on PK.
--
-- For v1 we ingest patch-application + lifecycle events plus
-- SYSTEM_REBOOTED (closes the loop on "did the post-patch reboot
-- actually happen?"). See INGEST_ACTIVITY_TYPES_INCLUDE in
-- .env.example for the full list. Excluded:
--   - PATCH_MANAGEMENT_SCAN_* — scanning, too noisy.
--   - PATCH_MANAGEMENT_INSTALLED / _INSTALL_FAILED — these are about
--     the Ninja patch-management AGENT, not OS patches. Not useful for
--     patch reporting. Actual patch application uses
--     PATCH_MANAGEMENT_APPLY_PATCH_*.
-- =============================================================================

-- ── Generic ingest state (cursors / high-water marks) ────────────────

CREATE TABLE IF NOT EXISTS ninja_core.ingest_state (
    key             text PRIMARY KEY,
    value           text NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Example usage: key='activities.last_id', value='<max activity id>'

-- ── Activities ───────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS ninja_activities;

CREATE TABLE IF NOT EXISTS ninja_activities.activities (
    id              bigint PRIMARY KEY,         -- Ninja's activity ID (stable, monotonic)
    activity_time   timestamptz NOT NULL,
    device_id       integer REFERENCES ninja_core.devices(id),
    user_id         integer,                    -- nullable for system-triggered
    source_name     text,                       -- PATCH_MANAGEMENT, ...
    source_type     text,                       -- PATCH_JOB, ...
    activity_type   text,                       -- PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED, ...
    severity        text,
    subject         text,
    message         text,
    data            jsonb NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS activities_time_idx
    ON ninja_activities.activities (activity_time DESC);
CREATE INDEX IF NOT EXISTS activities_device_time_idx
    ON ninja_activities.activities (device_id, activity_time DESC);
CREATE INDEX IF NOT EXISTS activities_source_type_idx
    ON ninja_activities.activities (source_name, activity_type);
