\pset pager off
\echo === sizes / counts ===
SELECT 'ninja_patches.patch_facts' AS rel, pg_size_pretty(pg_total_relation_size('ninja_patches.patch_facts')) AS size,
       (SELECT count(*) FROM ninja_patches.patch_facts) AS rows;
SELECT 'ninja_patches.device_patch_signal' AS rel, pg_size_pretty(pg_total_relation_size('ninja_patches.device_patch_signal')) AS size,
       (SELECT count(*) FROM ninja_patches.device_patch_signal) AS rows;
SELECT 'ninja_patches.current_patch_state' AS rel, pg_size_pretty(pg_total_relation_size('ninja_patches.current_patch_state')) AS size,
       (SELECT count(*) FROM ninja_patches.current_patch_state) AS rows;
SELECT 'operations.v_device' AS rel, 'view' AS size,
       (SELECT count(*) FROM operations.v_device WHERE tenant_id = 1) AS rows;
SELECT 'operations.device_links' AS rel, pg_size_pretty(pg_total_relation_size('operations.device_links')) AS size,
       (SELECT count(*) FROM operations.device_links WHERE tenant_id = 1) AS rows;
SELECT 'operations.findings (patching, active)' AS rel, NULL AS size,
       (SELECT count(*) FROM operations.findings f
          JOIN operations.finding_types ft ON ft.id = f.finding_type_id
          JOIN operations.finding_categories fc ON fc.id = ft.category_id
         WHERE f.tenant_id = 1 AND fc.name = 'patching'
           AND f.status IN ('open','acknowledged','snoozed')) AS rows;

\echo === patch_facts by fact_type ===
SELECT fact_type, count(*) FROM ninja_patches.patch_facts GROUP BY 1 ORDER BY 2 DESC;

\echo === indexes on patch_facts ===
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='ninja_patches' AND tablename='patch_facts';

\echo === matview freshness ===
SELECT relname, pg_stat_get_last_analyze_time(oid) AS last_analyze
FROM pg_class WHERE relnamespace = 'ninja_patches'::regnamespace
  AND relname IN ('device_patch_signal','current_patch_state','latest_install_outcome');
