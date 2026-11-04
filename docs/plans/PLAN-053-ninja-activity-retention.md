# PLAN-053 — Ninja activity retention

**Status: ready.** Registered 2026-11-04; moved from PLAN-019's registry entry,
where it arrived from PLAN-022's backlog hand-off (2026-10-28) outside that
plan's steps. Defined, not started. Production reads, deletes, schema changes,
commits, pushes and deployment each keep their gates.

## Goal

`ninja_activities.activities` keeps Ninja activity events only as long as an
operator need requires, so the table stops growing without limit and the
readers and rollups built on it stay cheap.

## Evidence

- 774k rows, 7.0 GB on 2026-10-28 (PLAN-022), about 9 KB a row; the database
  is about 31 GB (PLAN-050). Nothing deletes rows.
- Insert-once on Ninja's activity id. Software events are already discarded
  before storage (`ingest/activities/ingest.py`); stored rows are patch,
  reboot, system and deletion events with the raw payload in `data`.
- Readers (code search, 2026-11-04):
  - Device page activity timeline: newest 100 events per device, no date
    bound (`operations/apps/core/views.py`, `ninja_activities.activities`
    query near line 3530).
  - Patch activity search: bounded by a user-chosen number of days
    (`views.py`, near line 14550).
  - Materialized views `device_activity_signal`, `patch_warning_events_recent`,
    `system_reboot_events_recent` (sql/migrations 012 and 068), refreshed
    after every activities run. No date filter was found in their definitions
    on a skim; if they cover the whole table, each hourly refresh reads all of
    it (relevant to PLAN-041 CPU and PLAN-050 memory). Not measured.
  - `metabase_ro` holds `SELECT` on one `ninja_activities` relation; Metabase
    is retired (PLAN-008).

## Steps

| Step | Work | Gate |
| --- | --- | --- |
| 1 | Read-only measurement: rows and size by month and by event type; share of size in `data`; the three views' row counts, definitions and refresh time | Read-only production approval |
| 2 | Decide: retention period for rows (and optionally a shorter period for the raw `data` payload); whether the views need a date bound | User decision; record in an ADR if it sets a lasting rule |
| 3 | Implement: a scheduled, batched delete (or payload trim) as a Job with its resource limit, plus view bounds if decided; focused test | Implementation approval; release approval names any migration |
| 4 | One-time cleanup of rows past the period, in batches, in a maintenance window; then reclaim space if needed | Separate approval for the delete and for any `VACUUM FULL`/rewrite |

## Coordination

PLAN-050 (database memory) and PLAN-041 (host CPU) benefit; PLAN-047 owns
write churn generally. PLAN-019 F02 catch-up only adds rows that should have
been stored; it does not change retention.
