\pset pager off
\timing on
SET LOCAL operations.tenant_id = 1;
BEGIN;
-- Pick a real busy title.
\set name 'Google Chrome'
SELECT canonical_name, COUNT(*) AS installations, COUNT(DISTINCT device_id) AS devices
FROM operations.software_installations_current
WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
GROUP BY canonical_name ORDER BY installations DESC LIMIT 5;

-- Fleet rollup (as issued by view)
SELECT COUNT(*) AS installations,
       COUNT(DISTINCT sic.device_id) AS devices,
       COUNT(DISTINCT sic.client_id) AS clients,
       MIN(sic.first_observed_at) AS first_observed,
       MAX(sic.last_observed_at)  AS last_observed,
       MAX(sic.first_observed_at) AS latest_install
FROM operations.software_installations_current sic
WHERE sic.tenant_id=1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
  AND LOWER(sic.canonical_name) = LOWER('Google Chrome');

-- Publisher breakdown
SELECT COALESCE(NULLIF(publisher,''),'(unknown)') AS publisher,
       COUNT(*)::int AS installs, COUNT(DISTINCT device_id)::int AS devices
FROM operations.software_installations_current
WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
  AND LOWER(canonical_name)=LOWER('Google Chrome')
GROUP BY 1 ORDER BY installs DESC;

-- Version breakdown
SELECT COALESCE(NULLIF(version,''),'(unknown)') AS version,
       COUNT(*)::int AS installs, COUNT(DISTINCT device_id)::int AS devices,
       COUNT(DISTINCT client_id)::int AS clients,
       MAX(last_observed_at) AS last_observed
FROM operations.software_installations_current
WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
  AND LOWER(canonical_name)=LOWER('Google Chrome')
GROUP BY 1 ORDER BY installs DESC, version LIMIT 5;

-- Location breakdown
SELECT COALESCE(NULLIF(install_location,''),'(unknown)') AS location, COUNT(*)::int AS installs
FROM operations.software_installations_current
WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
  AND LOWER(canonical_name)=LOWER('Google Chrome')
GROUP BY 1 ORDER BY installs DESC LIMIT 5;

-- Install list (bounded)
EXPLAIN (ANALYZE, SUMMARY OFF)
SELECT sic.device_id, sic.client_id, c.slug, c.display_name,
       d.canonical_hostname, d.device_role, d.os_group,
       sic.version, sic.install_location, sic.install_date,
       sic.first_observed_at, sic.last_observed_at
FROM operations.software_installations_current sic
JOIN operations.clients c ON c.id = sic.client_id
JOIN operations.devices d ON d.id = sic.device_id
WHERE sic.tenant_id=1 AND sic.deleted_at IS NULL AND sic.stale_since IS NULL
  AND LOWER(sic.canonical_name)=LOWER('Google Chrome')
ORDER BY c.display_name, d.canonical_hostname
LIMIT 500;

ROLLBACK;
