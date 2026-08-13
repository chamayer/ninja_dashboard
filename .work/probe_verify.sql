\pset pager off
BEGIN;

-- Reproduce the migration body (dry-run: rolls back).
DROP MATERIALIZED VIEW IF EXISTS ninja_patches.device_patch_activity;
CREATE MATERIALIZED VIEW ninja_patches.device_patch_activity AS
SELECT
    pf.device_id,
    MAX(COALESCE(pf.installed_at, pf.ninja_observed_at, pf.last_observed_at))
        AS last_patch_activity_at
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type IN ('patch_state', 'install_outcome')
GROUP BY pf.device_id;

SELECT 'matview rows' AS metric, COUNT(*)::text AS value FROM ninja_patches.device_patch_activity;

-- Sample: does the join shape work end-to-end?
SELECT COUNT(*) AS devices,
       COUNT(dpa.last_patch_activity_at) AS with_activity
FROM operations.v_device v
LEFT JOIN operations.device_links dl
       ON dl.device_id = v.device_id AND dl.tenant_id = 1
LEFT JOIN operations.sources s ON s.id = dl.source_id AND LOWER(s.name) = 'ninja'
LEFT JOIN ninja_patches.device_patch_activity dpa
       ON dl.external_id ~ '^\d+$' AND dpa.device_id = dl.external_id::integer
WHERE v.tenant_id = 1;

ROLLBACK;
