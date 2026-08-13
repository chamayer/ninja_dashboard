\pset pager off
BEGIN;
CREATE MATERIALIZED VIEW ninja_patches.device_patch_activity AS
SELECT
    pf.device_id,
    MAX(COALESCE(pf.installed_at, pf.ninja_observed_at, pf.last_observed_at))
        AS last_patch_activity_at
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type IN ('patch_state', 'install_outcome')
GROUP BY pf.device_id;
CREATE UNIQUE INDEX device_patch_activity_device_idx
    ON ninja_patches.device_patch_activity (device_id);

SET LOCAL operations.tenant_id = 1;

-- Full posture rollup as the rewritten view would run it.
EXPLAIN (ANALYZE, BUFFERS, SUMMARY OFF)
WITH scoped_devices AS (
    SELECT v.device_id, v.client_id, v.canonical_hostname,
           v.device_role, v.os_group, v.last_contact_at,
           v.needs_reboot, v.effective_patching_scope
    FROM operations.v_device v
    WHERE v.tenant_id = 1 AND v.lifecycle_status <> 'retired'
), ninja_links AS (
    SELECT DISTINCT dl.device_id, dl.external_id::integer AS ninja_device_id
    FROM operations.device_links dl
    JOIN operations.sources s ON s.id = dl.source_id
    WHERE dl.tenant_id = 1 AND LOWER(s.name) = 'ninja'
      AND dl.external_id ~ '^\d+$'
), patch_signal AS (
    SELECT nl.device_id,
           BOOL_OR(COALESCE(dps.ever_installed, FALSE)) AS ever_installed
    FROM ninja_links nl
    JOIN ninja_patches.device_patch_signal dps
      ON dps.device_id = nl.ninja_device_id
    GROUP BY nl.device_id
), patch_activity AS (
    SELECT nl.device_id,
           MAX(dpa.last_patch_activity_at) AS last_patch_activity_at
    FROM ninja_links nl
    JOIN ninja_patches.device_patch_activity dpa
      ON dpa.device_id = nl.ninja_device_id
    GROUP BY nl.device_id
), device_posture AS (
    SELECT sd.*, pa.last_patch_activity_at,
           COALESCE(ps.ever_installed, FALSE) AS ever_installed,
           sd.last_contact_at >= NOW() - INTERVAL '7 days' AS is_active,
           pa.last_patch_activity_at >= NOW() - INTERVAL '35 days'
               AS has_recent_patch_activity
    FROM scoped_devices sd
    LEFT JOIN patch_signal ps ON ps.device_id = sd.device_id
    LEFT JOIN patch_activity pa ON pa.device_id = sd.device_id
)
SELECT dp.client_id, c.slug, c.display_name,
       COUNT(*)::int AS total,
       COUNT(*) FILTER (WHERE dp.is_active)::int AS active,
       COUNT(*) FILTER (WHERE dp.is_active AND dp.effective_patching_scope = 'Included')::int AS active_in_scope,
       GROUPING(dp.client_id) AS is_total
FROM device_posture dp
LEFT JOIN operations.clients c ON c.id = dp.client_id AND c.deleted_at IS NULL
GROUP BY GROUPING SETS ((), (dp.client_id, c.slug, c.display_name))
ORDER BY is_total DESC, total DESC;

ROLLBACK;
