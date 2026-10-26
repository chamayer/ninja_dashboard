# PLAN-017 — Phase 3 incidence query draft

2026-10-26. Status: **unexecuted draft for review and user approval.** No
statement below has been sent to any database. It follows the protocol of the
[Phase 1 diagnostic drafts](PLAN-017-diagnostic-queries.md): read-only
wrapper, P0 preflight, plain plans before SELECTs, aggregate output only, stop
on any mismatch. It measures how often the mechanisms reproduced in
[Phase 2](PLAN-017-phase-2-results.md) occur in production.

## What is already answered

**F01** needs no new query. Phase 1 D5.2 (uncapped 30 days, captured
2026-10-25, [results](PLAN-017-ab1-retry-results.md)) found **0** successful
zero-row receipts for every `_FETCHERS` platform (Hudu 124 receipts, LogMeIn
132, R-U-ON 72, ScreenConnect 131, SentinelOne 127). F01's exposure was
therefore not observed in that window; the mechanism remains.

## Scope

| Query | Finding | Question | Signal |
| --- | --- | --- | --- |
| M0 | all | Do the relations, columns and indexes these bodies assume exist, and how far back do the tables reach? | Catalog metadata and retention bounds |
| M1 | F08 | How often has a source group been withdrawn by a complete snapshot and then returned? | Org history intervals closed by a snapshot run and followed by a later interval, per platform |
| M2 | F02 | Has any activity run come near the per-filter cap (200 pages × 500 = 100,000)? | Ninja source events captured per run window and event type |
| M3 | F03 | How many activity runs failed, and how many software events fell inside failed runs? | `run_log` kind `activities` plus `source_events` in failed windows |
| M4 | U04 | Did any consumed software target receive new demand while its consuming findings run was in progress? | Matcher coalescing bumps `queued_at`; a consumed target with `queued_at` inside the consuming run is a direct loss candidate |
| M5 | U04 | How often did a producer job (inventory or matcher) overlap or finish inside a findings run? | `operator_job_runs` window overlap |
| L1 | F02, F08 | Optional, separate approval: how many cap and sites-failure warnings do the ingest logs hold? | Line counts only |

M1–M5 never return identifiers, names, payloads, titles, errors or
customer values; only counts, percentiles and window bounds.

## Execution role, wrapper and limits

Role `operations_migrate`, as for Phase 1 D1/D2/D3/D5: aggregates must not be
hidden by RLS. Use the [workspace helper](../operations.md#shared-validation-helper)
with its private profile; never print profile values. One connection and one
statement at a time, each inside:

```sql
BEGIN TRANSACTION READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '10s';
SET LOCAL operations.tenant_id = '1';
-- One numbered body.
ROLLBACK;
```

Order: P0 (Phase 1 text, unchanged), then M0, then `EXPLAIN (FORMAT JSON)`
without ANALYZE for M1–M5, then — only if the plans pass review — the M1–M5
SELECTs. Stop on: role or version mismatch, `transaction_read_only` off, a
missing relation or column in M0, any timeout or error, or a plan with a
sequential scan of `entity_observation_history` or `source_events` that review
has not accepted. No retries, no raised limits, no planner changes. Total wall
budget 60 seconds.

## Statements

```sql
-- M0: relations, columns, indexes and retention bounds. Metadata and min/max
-- timestamps only.
SELECT r.rel, to_regclass(r.rel) IS NOT NULL AS present,
       (SELECT count(*) FROM information_schema.columns c
         WHERE c.table_schema = 'operations' AND c.table_name = split_part(r.rel, '.', 2)
           AND c.column_name = ANY (r.cols)) AS columns_found,
       cardinality(r.cols) AS columns_expected
  FROM (VALUES
   ('operations.entity_observation_history',
    ARRAY['tenant_id','platform','entity_type','external_namespace','source_instance_id',
          'parent_external_namespace','parent_external_id','external_id',
          'effective_from','effective_to','closed_by_snapshot_run_id']),
   ('operations.source_events',
    ARRAY['tenant_id','source_instance_id','event_type','received_at']),
   ('operations.source_instances', ARRAY['id','source_id','tenant_id','enabled']),
   ('operations.sources', ARRAY['id','name']),
   ('operations.run_log', ARRAY['tenant_id','kind','started_at','ended_at','ok']),
   ('operations.operator_job_runs',
    ARRAY['tenant_id','job_key','status','requested_at','started_at','completed_at']),
   ('operations.software_reclassification_targets',
    ARRAY['tenant_id','source','queued_at','consumed_at'])
  ) AS r(rel, cols)
 ORDER BY r.rel;

-- M0b: installed index definitions on those tables (capped).
SELECT tablename, indexname, indexdef
  FROM pg_indexes
 WHERE schemaname = 'operations'
   AND tablename IN ('entity_observation_history','source_events','run_log',
                     'operator_job_runs','software_reclassification_targets')
 ORDER BY tablename, indexname
 LIMIT 100;

-- M0c: how far back each source reaches (bounds only).
SELECT (SELECT min(effective_from) FROM operations.entity_observation_history
         WHERE tenant_id = 1 AND entity_type = 'org') AS org_history_from,
       (SELECT min(received_at) FROM operations.source_events
         WHERE tenant_id = 1) AS source_events_from,
       (SELECT min(started_at) FROM operations.run_log
         WHERE tenant_id = 1 AND kind = 'activities') AS activities_runs_from,
       (SELECT min(requested_at) FROM operations.operator_job_runs
         WHERE tenant_id = 1) AS job_runs_from,
       (SELECT min(consumed_at) FROM operations.software_reclassification_targets
         WHERE tenant_id = 1 AND consumed_at IS NOT NULL) AS consumed_targets_from;

-- M1 (F08): org withdrawals by a complete snapshot and later returns, per
-- platform, over retained history.
WITH org AS MATERIALIZED (
 SELECT platform, effective_to, closed_by_snapshot_run_id,
        lead(effective_from) OVER (
          PARTITION BY source_instance_id, external_namespace,
                       parent_external_namespace, parent_external_id, external_id
          ORDER BY effective_from) AS next_from
   FROM operations.entity_observation_history
  WHERE tenant_id = 1 AND entity_type = 'org'
)
SELECT platform,
       count(*) AS org_intervals,
       count(*) FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL) AS absence_closures,
       count(*) FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL
                          AND next_from IS NOT NULL) AS closures_then_returned,
       count(*) FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL
                          AND next_from - effective_to <= interval '1 day') AS returned_within_1d,
       percentile_cont(0.5) WITHIN GROUP (
         ORDER BY extract(epoch FROM next_from - effective_to))
         FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL AND next_from IS NOT NULL)
         AS median_return_gap_seconds
  FROM org
 GROUP BY platform
 ORDER BY platform;

-- M2 (F02): Ninja events captured per activity run and event type, 30 days.
WITH ninja AS MATERIALIZED (
 SELECT si.id FROM operations.source_instances si
   JOIN operations.sources s ON s.id = si.source_id
  WHERE si.tenant_id = 1 AND lower(s.name) = 'ninja'
), runs AS MATERIALIZED (
 SELECT started_at, ended_at FROM operations.run_log
  WHERE tenant_id = 1 AND kind = 'activities' AND ended_at IS NOT NULL
    AND started_at >= now() - interval '30 days' AND started_at < now()
), per_run AS (
 SELECT r.started_at, e.event_type, count(*) AS captured
   FROM runs r
   JOIN operations.source_events e
     ON e.tenant_id = 1 AND e.source_instance_id IN (SELECT id FROM ninja)
    AND e.received_at >= r.started_at AND e.received_at <= r.ended_at
  GROUP BY r.started_at, e.event_type
)
SELECT (SELECT count(*) FROM runs) AS activity_runs_30d,
       count(*) AS run_type_pairs,
       max(captured) AS max_captured_one_type_one_run,
       count(*) FILTER (WHERE captured >= 10000) AS pairs_over_10k,
       count(*) FILTER (WHERE captured >= 50000) AS pairs_over_50k,
       count(*) FILTER (WHERE captured >= 99500) AS pairs_at_cap
  FROM per_run;

-- M3 (F03): failed activity runs and software events inside them, 30 days.
WITH runs AS MATERIALIZED (
 SELECT started_at, ended_at, ok FROM operations.run_log
  WHERE tenant_id = 1 AND kind = 'activities'
    AND started_at >= now() - interval '30 days' AND started_at < now()
)
SELECT count(*) AS activity_runs_30d,
       count(*) FILTER (WHERE ok IS FALSE) AS failed_runs,
       (SELECT count(*) FROM runs r
          JOIN operations.source_events e
            ON e.tenant_id = 1 AND e.event_type LIKE 'SOFTWARE\_%'
           AND e.received_at >= r.started_at
           AND e.received_at <= coalesce(r.ended_at, r.started_at + interval '1 hour')
         WHERE r.ok IS FALSE) AS software_events_in_failed_runs
  FROM runs;

-- M4 (U04 direct): consumed targets whose demand arrived during the run that
-- consumed them, per producer source, 30 days.
WITH consumer AS MATERIALIZED (
 SELECT started_at, completed_at FROM operations.operator_job_runs
  WHERE tenant_id = 1
    AND job_key IN ('software-classify', 'software-classify-only', 'software-classify-full')
    AND status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL
    AND requested_at >= now() - interval '31 days'
)
SELECT t.source,
       count(*) AS consumed_targets_30d,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM consumer c
          WHERE t.consumed_at BETWEEN c.started_at AND c.completed_at
            AND t.queued_at > c.started_at)) AS queued_during_consuming_run
  FROM operations.software_reclassification_targets t
 WHERE t.tenant_id = 1 AND t.consumed_at >= now() - interval '30 days'
 GROUP BY t.source
 ORDER BY t.source;

-- M5 (U04 overlap): producer jobs overlapping, or finishing inside, a
-- findings run, 30 days.
WITH consumer AS MATERIALIZED (
 SELECT started_at, completed_at FROM operations.operator_job_runs
  WHERE tenant_id = 1
    AND job_key IN ('software-classify', 'software-classify-only', 'software-classify-full')
    AND started_at IS NOT NULL AND completed_at IS NOT NULL
    AND requested_at >= now() - interval '30 days'
), producer AS MATERIALIZED (
 SELECT job_key, started_at, completed_at FROM operations.operator_job_runs
  WHERE tenant_id = 1
    AND job_key IN ('software-queue-drain', 'software-enqueue-orgs', 'intel-matcher')
    AND started_at IS NOT NULL AND completed_at IS NOT NULL
    AND requested_at >= now() - interval '30 days'
)
SELECT p.job_key,
       count(*) AS producer_runs,
       (SELECT count(*) FROM consumer) AS consumer_runs,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM consumer c
          WHERE p.started_at < c.completed_at AND p.completed_at > c.started_at))
         AS overlapping_a_consumer,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM consumer c
          WHERE p.completed_at > c.started_at AND p.completed_at < c.completed_at))
         AS finished_inside_a_consumer
  FROM producer p
 GROUP BY p.job_key
 ORDER BY p.job_key;
```

## How the results will be read

- **M1.** Returns within one collection cycle on SentinelOne, with few or
  none elsewhere, fit F08's swallowed sites failure. Real deletions rarely
  come back. History older than the 90-day purge is gone, so M0c bounds the
  window. Closures caused by content changes have no
  `closed_by_snapshot_run_id` and are excluded.
- **M2.** `source_events` holds the rows each filter kept, which is a lower
  bound on fetched pages. A pair at or above 99,500 means the cap was hit.
  Values far below 10,000 make F02 unlikely at the current volume. This
  assumes the configured allowlist (one `status=` filter per event type); the
  type-based fallback would group differently.
- **M3.** Failed runs bound how often F03's interruption could have
  happened; they do not prove a lost enqueue.
- **M4.** Only matcher (`cve_match`) coalescing moves `queued_at`, so a
  non-zero count for `cve_match` is a direct U04 loss candidate. For
  `inventory` the count means "created between job start and capture" and is
  benign; inventory coalescing leaves no trace, hence M5.
- **M5.** Producers finishing inside a findings run make the inventory loss
  window possible. Zero overlap means the scheduler already serializes them in
  practice.

## Revision 1 — after M0 and the M1/M4/M5 plans (awaiting approval)

M0 and the plans exposed three drafting errors; M2, M3 and M1 were stopped
under the rules above and are replaced by the bodies below. M4 and M5 ran as
approved.

- **M2/M3** read `operations.run_log` kind `activities`, which has no rows.
  The activity ingest logs to `ninja_core.run_log` (`domain = 'activities'`,
  status `ok`/`failed`/`running`; `ingest/runlog.py`). `source_events` also has
  no `received_at` index, so per-run receipt windows would scan it. M2r uses
  the indexed `event_at` per day instead; M3r reads `ninja_core.run_log`,
  including the longest gap between successful runs (a long gap is when a
  backlog could exceed the cap).
- **M1** planned a parallel sequential scan of `entity_observation_history`.
  M1r restricts to the SentinelOne and ScreenConnect source instances (the
  latter as a comparison platform with groups) so the
  `source_instance_id` index can be used. If the plan still scans the table,
  M1r stops.
- **L1** targeted `operations-ingest`, which started 2026-10-26 13:28 UTC and
  does not run the scheduled collection jobs; those run in
  `ninja-jobs-worker`. L1r repeats the same count-only commands there.

```sql
-- M1r (F08): org withdrawals then returns, SentinelOne and ScreenConnect only.
WITH inst AS MATERIALIZED (
 SELECT si.id, s.name AS platform
   FROM operations.source_instances si
   JOIN operations.sources s ON s.id = si.source_id
  WHERE si.tenant_id = 1 AND s.name IN ('SentinelOne', 'ScreenConnect')
), org AS MATERIALIZED (
 SELECT i.platform, h.effective_to, h.closed_by_snapshot_run_id,
        lead(h.effective_from) OVER (
          PARTITION BY h.source_instance_id, h.external_namespace,
                       h.parent_external_namespace, h.parent_external_id, h.external_id
          ORDER BY h.effective_from) AS next_from
   FROM operations.entity_observation_history h
   JOIN inst i ON i.id = h.source_instance_id
  WHERE h.tenant_id = 1 AND h.entity_type = 'org'
)
SELECT platform,
       count(*) AS org_intervals,
       count(*) FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL) AS absence_closures,
       count(*) FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL
                          AND next_from IS NOT NULL) AS closures_then_returned,
       count(*) FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL
                          AND next_from - effective_to <= interval '1 day') AS returned_within_1d,
       percentile_cont(0.5) WITHIN GROUP (
         ORDER BY extract(epoch FROM next_from - effective_to))
         FILTER (WHERE closed_by_snapshot_run_id IS NOT NULL AND next_from IS NOT NULL)
         AS median_return_gap_seconds
  FROM org
 GROUP BY platform
 ORDER BY platform;

-- M2r (F02): Ninja events per event type per day by activity time, 30 days.
WITH ninja AS MATERIALIZED (
 SELECT si.id FROM operations.source_instances si
   JOIN operations.sources s ON s.id = si.source_id
  WHERE si.tenant_id = 1 AND lower(s.name) = 'ninja'
), per_day AS (
 SELECT e.event_type, date_trunc('day', e.event_at) AS day, count(*) AS events
   FROM operations.source_events e
  WHERE e.tenant_id = 1 AND e.source_instance_id IN (SELECT id FROM ninja)
    AND e.event_at >= now() - interval '30 days' AND e.event_at < now()
  GROUP BY e.event_type, date_trunc('day', e.event_at)
)
SELECT count(*) AS type_days,
       max(events) AS max_events_one_type_one_day,
       count(*) FILTER (WHERE events >= 10000) AS type_days_over_10k,
       count(*) FILTER (WHERE events >= 50000) AS type_days_over_50k
  FROM per_day;

-- M3r (F02/F03): activity runs, failures, and the longest gap between
-- successful runs, 30 days.
WITH runs AS MATERIALIZED (
 SELECT started_at, status FROM ninja_core.run_log
  WHERE domain = 'activities'
    AND started_at >= now() - interval '30 days' AND started_at < now()
), ok AS (
 SELECT started_at - lag(started_at) OVER (ORDER BY started_at) AS gap
   FROM runs WHERE status = 'ok'
)
SELECT (SELECT count(*) FROM runs) AS activity_runs_30d,
       (SELECT count(*) FROM runs WHERE status = 'failed') AS failed_runs,
       (SELECT count(*) FROM runs WHERE status = 'running') AS unfinished_runs,
       (SELECT min(started_at) FROM runs) AS window_from,
       max(gap) AS longest_gap_between_ok_runs,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM gap))
         AS median_gap_seconds
  FROM ok;
```

L1r (count-only, through the helper's SSH profile):

```sh
docker logs --since 720h ninja-jobs-worker 2>&1 | grep -c 'page cap for'
docker logs --since 720h ninja-jobs-worker 2>&1 | grep -c 'SentinelOne sites fetch failed'
docker inspect -f '{{.State.StartedAt}}' ninja-jobs-worker
```

## Revision 2 — M2r with a 15-second statement timeout (approved)

M2r timed out at 5 seconds after an index-only scan plan. The user approved
one rerun of the unchanged M2r body with `statement_timeout = '15s'` (the
limit Phase 1 allowed for D4); every other wrapper setting and stop rule is
unchanged. F08 is decided on mechanism and not measured further (M1r is not
rewritten).

## Optional L1 — ingest log line counts (separate approval)

Container logs are a different exposure (they can contain host names and
errors), so L1 is a separate choice. Through the helper's SSH profile, count
lines only and print nothing else:

```sh
docker logs --since 720h operations-ingest 2>&1 | grep -c 'page cap for'
docker logs --since 720h operations-ingest 2>&1 | grep -c 'SentinelOne sites fetch failed'
```

Log retention depends on container restarts, so a zero is weak evidence; the
earliest available log time is reported with `docker inspect` start time only.

## Not included

Writer/refresh/capacity costs and ordinary-user reader parity, carried from
Phase 1, are not in this draft; each needs its own justified scope. No
EXPLAIN ANALYZE, HTTP request, source API call, maintenance or setting change
is included.

## Approval requested

- **A — M0, plain plans for M1–M5, then M1–M5 SELECTs if the plans pass
  review.** Role `operations_migrate`, wrapper and stop rules above.
- **B — L1 log line counts** (optional, independent of A).
