\pset pager off
SET operations.tenant_id = 1;

-- 1. Does multi-version-per-device actually occur? (Limit 2)
--    History carries version and is NOT keyed on it, so this is the only
--    place the evidence could survive.
SELECT 'multi_version_per_device_title' AS probe, COUNT(*) AS occurrences
FROM (
    SELECT device_id, canonical_name, COUNT(DISTINCT version) AS versions
      FROM operations.software_installation_history
     WHERE tenant_id = 1 AND active
     GROUP BY device_id, canonical_name
    HAVING COUNT(DISTINCT version) > 1
) x;

-- 2. Per finding type: how many rows collapse to how many distinct titles?
SELECT ft.name AS finding_type,
       COUNT(*) AS open_rows,
       COUNT(DISTINCT lower(f.finding_details->>'canonical_name')) AS distinct_titles,
       COUNT(DISTINCT f.subject_id) AS distinct_devices
  FROM operations.findings f
  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
 WHERE ft.source_module = 'platform.software_findings'
   AND f.tenant_id = 1 AND f.status IN ('open','acknowledged')
 GROUP BY ft.name
 ORDER BY open_rows DESC;

-- 3. Do software findings carry a version in details? (can they bind to
--    software_versions at all, or only to product?)
SELECT ft.name AS finding_type,
       COUNT(*) FILTER (WHERE f.finding_details ? 'version') AS has_version,
       COUNT(*) AS total
  FROM operations.findings f
  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
 WHERE ft.source_module = 'platform.software_findings'
   AND f.tenant_id = 1 AND f.status IN ('open','acknowledged')
 GROUP BY ft.name ORDER BY total DESC;
