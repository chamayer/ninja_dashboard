\pset pager off
\timing on
SET LOCAL operations.tenant_id = 1;

-- Q1: fleet titles rollup (main table).
EXPLAIN (ANALYZE, SUMMARY OFF)
SELECT canonical_name FROM operations.software_installations_current
WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
GROUP BY canonical_name LIMIT 500;

-- Q2: batch risk lookup for 500 titles.
EXPLAIN (ANALYZE, SUMMARY OFF)
SELECT canonical_name, safety_score, safety_band, cve_count, kev_count, osint_hits
FROM operations.v_software_safety
WHERE tenant_id=1
  AND canonical_name IN (
    SELECT canonical_name FROM operations.software_installations_current
    WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
    GROUP BY canonical_name LIMIT 500);

-- Q3: high-risk COUNT
EXPLAIN (ANALYZE, SUMMARY OFF)
SELECT COUNT(*) FROM operations.v_software_safety WHERE tenant_id=1 AND safety_band='high';

-- Q4: risk distribution
EXPLAIN (ANALYZE, SUMMARY OFF)
SELECT safety_band, COUNT(*)::int FROM operations.v_software_safety
WHERE tenant_id=1 GROUP BY safety_band;
