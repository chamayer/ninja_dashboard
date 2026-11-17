-- PLAN-056 task 4 continuation; explicit monitoring-identity approval required.
-- System catalogs only. No query text, customer records, cancellation or writes.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '3s';
SET LOCAL lock_timeout = '1s';
SET LOCAL idle_in_transaction_session_timeout = '5s';
SET LOCAL application_name = 'plan056_completion';

SELECT jsonb_build_object(
    'section', 'visibility', 'utc', clock_timestamp(),
    'superuser', (SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
    'can_read_all_stats', pg_has_role(current_user,'pg_read_all_stats','MEMBER'),
    'database_matches', current_database()='ninja');

SELECT jsonb_build_object(
    'section', 'operations_activity', 'utc', clock_timestamp(),
    'rows', coalesce(jsonb_agg(to_jsonb(activity)), '[]'))
FROM (
    SELECT pid, backend_start, state, query_start, xact_start,
           wait_event_type, wait_event,
           cardinality(pg_blocking_pids(pid)) AS blocker_count,
           extract(epoch FROM clock_timestamp()-query_start) AS query_age_s,
           backend_start <= '2026-11-09T22:47:11.762Z'::timestamptz AS existed_at_attempt,
           query_start <= '2026-11-09T22:47:11.762Z'::timestamptz AS query_predates_attempt,
           (query ILIKE '%operations.device_requirement_state%'
            OR query ILIKE '%operations.v_hudu_computer_inventory_observation_current%')
               AS resembles_coverage_reader
    FROM pg_stat_activity
    WHERE datname=current_database() AND application_name='operations'
      AND pid<>pg_backend_pid()
    ORDER BY query_start NULLS LAST, pid
    LIMIT 25
) activity;
ROLLBACK;
