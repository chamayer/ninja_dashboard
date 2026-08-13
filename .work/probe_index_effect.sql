\pset pager off
\timing on
BEGIN;
CREATE INDEX IF NOT EXISTS software_installations_current_lower_canonical_idx
    ON operations.software_installations_current (tenant_id, LOWER(canonical_name))
    WHERE deleted_at IS NULL AND stale_since IS NULL;

SET LOCAL operations.tenant_id = 1;

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
