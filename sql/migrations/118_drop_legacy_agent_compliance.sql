-- 118: drop the legacy agent-compliance and inventory schemas (PLAN-022 A3a).
--
-- Operations replaced agent compliance (PLAN-006, now absorbed by PLAN-022).
-- Its Jobs are retired legacy bridges whose schedules the registry keeps
-- disabled, so nothing has written the schema since 2026-10-06 (last run
-- requested 2026-10-07), although AGENT_COMPLIANCE_ENABLED is still true in
-- the production env file. The bridge code is removed in the same change.
-- ninja_inventory holds empty materialized views over the legacy schema, and
-- nothing calls its refresh. About 12.8 GB. Every table was exported with
-- pg_dump before this migration (archive in PLAN-022).
--
-- The guard refuses to run if any view, materialized view or foreign key
-- outside these two schemas depends on them. Routines, triggers, policies,
-- defaults and every other catalog dependency were checked read-only in
-- production before this shipped (PLAN-022 L14-L16: none outside).

DO $$
DECLARE
    dependents text;
BEGIN
    SELECT string_agg(DISTINCT dep_ns.nspname || '.' || dep.relname, ', ')
      INTO dependents
      FROM pg_catalog.pg_depend d
      JOIN pg_catalog.pg_rewrite r ON r.oid = d.objid
      JOIN pg_catalog.pg_class dep ON dep.oid = r.ev_class
      JOIN pg_catalog.pg_namespace dep_ns ON dep_ns.oid = dep.relnamespace
      JOIN pg_catalog.pg_class ref ON ref.oid = d.refobjid
      JOIN pg_catalog.pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
     WHERE d.classid = 'pg_catalog.pg_rewrite'::regclass
       AND ref_ns.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
       AND dep_ns.nspname NOT IN ('ninja_agent_compliance', 'ninja_inventory');
    IF dependents IS NOT NULL THEN
        RAISE EXCEPTION 'legacy schema has outside view dependents: %', dependents;
    END IF;

    SELECT string_agg(DISTINCT con.conrelid::regclass::text, ', ')
      INTO dependents
      FROM pg_catalog.pg_constraint con
      JOIN pg_catalog.pg_class ref ON ref.oid = con.confrelid
      JOIN pg_catalog.pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
      JOIN pg_catalog.pg_class src ON src.oid = con.conrelid
      JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src.relnamespace
     WHERE con.contype = 'f'
       AND ref_ns.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
       AND src_ns.nspname NOT IN ('ninja_agent_compliance', 'ninja_inventory');
    IF dependents IS NOT NULL THEN
        RAISE EXCEPTION 'legacy schema has outside foreign keys: %', dependents;
    END IF;
END $$;

DROP SCHEMA IF EXISTS ninja_inventory CASCADE;
DROP SCHEMA IF EXISTS ninja_agent_compliance CASCADE;
