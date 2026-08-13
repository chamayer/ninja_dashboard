\pset pager off
SELECT connector, last_status, last_run_at, last_success_at, rows_touched, LEFT(last_error, 120) AS err
FROM operations.intel_ingest_status ORDER BY connector;

SELECT 'intel.cves rows' AS what, COUNT(*)::text AS n FROM intel.cves
UNION ALL SELECT 'intel.cpes', COUNT(*)::text FROM intel.cpes
UNION ALL SELECT 'operations.cve_match', COUNT(*)::text FROM operations.cve_match
UNION ALL SELECT 'operations.safety_signal', COUNT(*)::text FROM operations.safety_signal
UNION ALL SELECT 'kev-flagged CVEs', COUNT(*)::text FROM intel.cves WHERE kev_flag;
