\pset pager off
SELECT kind, COUNT(*) AS runs, MAX(started_at) AS last, BOOL_OR(ok) AS any_ok
FROM operations.run_log
GROUP BY kind
ORDER BY last DESC NULLS LAST;
