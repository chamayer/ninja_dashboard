-- WP0 evidence only. Run through the approved private validation helper.
-- No identifiers, error text, request payloads, or source-instance keys leave DB.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';

SELECT 'sample' AS metric, now() AS sampled_at,
       'all retained rows; durations in seconds' AS scope;

SELECT 'operator_status' AS metric, status, lane, count(*) AS runs
FROM operations.operator_job_runs GROUP BY status, lane ORDER BY status, lane;

SELECT 'active_duplicates' AS metric, count(*) AS groups,
       COALESCE(sum(n - 1), 0) AS excess
FROM (
    SELECT tenant_id, job_key, count(*) AS n
    FROM operations.operator_job_runs WHERE status IN ('queued', 'running')
    GROUP BY tenant_id, job_key HAVING count(*) > 1
) AS duplicates;

SELECT 'job_duration' AS metric, job_key, status, count(*) AS runs,
       round((percentile_cont(0.5) WITHIN GROUP
           (ORDER BY extract(epoch FROM completed_at - started_at)))::numeric, 1) AS p50,
       round((percentile_cont(0.95) WITHIN GROUP
           (ORDER BY extract(epoch FROM completed_at - started_at)))::numeric, 1) AS p95,
       round(max(extract(epoch FROM completed_at - started_at))::numeric, 1) AS max_seconds
FROM operations.operator_job_runs
WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
GROUP BY job_key, status ORDER BY job_key, status;

SELECT 'job_ages' AS metric,
       count(*) FILTER (WHERE status = 'queued') AS queued,
       round(max(extract(epoch FROM now() - requested_at))
           FILTER (WHERE status = 'queued')::numeric, 1) AS max_wait_seconds,
       count(*) FILTER (WHERE status = 'running') AS running,
       count(*) FILTER (WHERE status = 'running'
           AND started_at < now() - interval '90 minutes') AS running_over_90m,
       count(*) FILTER (WHERE status = 'running'
           AND heartbeat_at < now() - interval '90 minutes') AS stale_heartbeat,
       count(*) FILTER (WHERE status = 'running'
           AND lease_expires_at < now()) AS expired_lease
FROM operations.operator_job_runs;

-- Classification of stored wording; not verified failure causation.
SELECT 'recorded_failure_class' AS metric, status,
       CASE WHEN error ILIKE '%restart%' THEN 'restart_marker'
            WHEN error ~* '(timeout|timed out|deadline|lease expired|stopped responding)'
                THEN 'timeout_or_liveness_wording'
            ELSE 'other' END AS classification,
       count(*) AS runs
FROM operations.operator_job_runs WHERE status IN ('failed', 'stalled')
GROUP BY status, classification ORDER BY status, classification;

SELECT 'domain_queue_status' AS metric, 'source_demand' AS queue, status, count(*) AS rows
FROM operations.source_run_queue GROUP BY status
UNION ALL
SELECT 'domain_queue_status', 'source_action', status, count(*)
FROM operations.source_action_requests GROUP BY status
UNION ALL
SELECT 'domain_queue_status', 'software_scheduled', status, count(*)
FROM ninja_core.software_scheduled_queue GROUP BY status
UNION ALL
SELECT 'domain_queue_status', 'software_demand', status, count(*)
FROM ninja_core.software_demand_queue GROUP BY status
UNION ALL
SELECT 'domain_queue_status', 'software_activity', status, count(*)
FROM ninja_core.software_activity_queue GROUP BY status
ORDER BY queue, status;

SELECT 'source_actions_total' AS metric, count(*) AS rows
FROM operations.source_action_requests;

SELECT 'job_log_linkage' AS metric, count(*) AS jobs,
       count(*) FILTER (WHERE run_log_kind = '') AS blank_kind,
       count(*) FILTER (WHERE run_log_kind <> '' AND EXISTS (
           SELECT 1 FROM operations.run_log l
           WHERE l.tenant_id = j.tenant_id AND l.kind = j.run_log_kind
       )) AS nonblank_matching_kind
FROM operations.operator_job_runs j;

-- Deliberately suppress source-instance suffixes and unfamiliar kind values.
WITH log_rows AS (
    SELECT CASE
        WHEN kind IN ('parity_check', 'patch_findings', 'platform_evaluator',
                      'software_classifier') THEN kind
        WHEN kind LIKE 'source.%' THEN 'source_collection'
        ELSE 'other_kind' END AS family,
        ok, started_at, ended_at
    FROM operations.run_log
)
SELECT 'diagnostic_duration' AS metric, family, ok, count(*) AS rows,
       round((percentile_cont(0.5) WITHIN GROUP
           (ORDER BY extract(epoch FROM ended_at - started_at)))::numeric, 1) AS p50,
       round((percentile_cont(0.95) WITHIN GROUP
           (ORDER BY extract(epoch FROM ended_at - started_at)))::numeric, 1) AS p95,
       round(max(extract(epoch FROM ended_at - started_at))::numeric, 1) AS max_seconds
FROM log_rows GROUP BY family, ok ORDER BY family, ok;

SELECT 'database_stats' AS metric, deadlocks, stats_reset
FROM pg_stat_database WHERE datname = current_database();
SELECT 'ungranted_locks' AS metric, count(*) AS locks
FROM pg_locks WHERE NOT granted
  AND database = (SELECT oid FROM pg_database WHERE datname = current_database());
ROLLBACK;
