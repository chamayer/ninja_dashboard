-- L1: database size and when activity counters were last reset; metadata only.
SELECT pg_catalog.pg_database_size(current_database()) AS database_bytes,
       d.stats_reset
  FROM pg_catalog.pg_stat_database d
 WHERE d.datname = current_database();
-- L2: total size per schema (tables, indexes, TOAST, materialized views).
SELECT n.nspname AS schema_name, count(*) AS relations,
       sum(pg_catalog.pg_total_relation_size(c.oid)) AS total_bytes
  FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'm', 'p')
   AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
 GROUP BY 1
 ORDER BY 3 DESC;
-- L3: every table and materialized view in the legacy schemas, plus the 25 largest elsewhere, with read/write activity.
WITH rel AS (
    SELECT c.oid, n.nspname AS schema_name, c.relname, c.relkind,
           pg_catalog.pg_total_relation_size(c.oid) AS total_bytes
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind IN ('r', 'm', 'p')
       AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
), picked AS (
    SELECT * FROM rel
     WHERE schema_name IN ('ninja_core', 'ninja_agent_compliance', 'agent_compliance',
                           'ninja_activities', 'ninja_patches', 'ninja_inventory')
    UNION
    SELECT * FROM (SELECT * FROM rel ORDER BY total_bytes DESC LIMIT 25) top
)
SELECT p.schema_name, p.relname, p.relkind, p.total_bytes,
       s.n_live_tup, s.seq_scan, s.last_seq_scan, s.idx_scan, s.last_idx_scan,
       s.n_tup_ins, s.n_tup_upd, s.n_tup_del
  FROM picked p
  LEFT JOIN pg_catalog.pg_stat_user_tables s ON s.relid = p.oid
 ORDER BY p.total_bytes DESC;
-- L4: views and materialized views outside the legacy schemas that depend on legacy relations.
SELECT DISTINCT dep_ns.nspname AS dependent_schema, dep.relname AS dependent_name,
       dep.relkind AS dependent_kind, ref_ns.nspname AS referenced_schema,
       ref.relname AS referenced_name
  FROM pg_catalog.pg_depend d
  JOIN pg_catalog.pg_rewrite r ON r.oid = d.objid
  JOIN pg_catalog.pg_class dep ON dep.oid = r.ev_class
  JOIN pg_catalog.pg_namespace dep_ns ON dep_ns.oid = dep.relnamespace
  JOIN pg_catalog.pg_class ref ON ref.oid = d.refobjid
  JOIN pg_catalog.pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
 WHERE d.classid = 'pg_catalog.pg_rewrite'::regclass
   AND dep.oid <> ref.oid
   AND (ref_ns.nspname IN ('ninja_core', 'ninja_agent_compliance', 'agent_compliance',
                           'ninja_activities', 'ninja_patches', 'ninja_inventory')
        OR ref.relname IN ('source_record_seen_daily'))
 ORDER BY 1, 2, 4, 5;
-- L5: roles holding SELECT on legacy schema tables or on the daily presence table.
SELECT g.grantee, g.table_schema, count(*) AS tables
  FROM information_schema.role_table_grants g
 WHERE g.privilege_type = 'SELECT'
   AND (g.table_schema IN ('ninja_core', 'ninja_agent_compliance', 'agent_compliance',
                           'ninja_activities', 'ninja_patches', 'ninja_inventory')
        OR g.table_name IN ('source_record_seen_daily', 'ninja_device_seen_daily_shadow'))
 GROUP BY 1, 2
 ORDER BY 1, 2;
-- L6: last write to the frozen Ninja snapshot tables.
SELECT (SELECT max(snapshot_at) FROM ninja_core.device_snapshots) AS device_snapshots_last,
       (SELECT max(snapshot_at) FROM ninja_core.device_health_snapshots) AS device_health_snapshots_last;
-- L7: last activity in the legacy agent-compliance schema.
SELECT (SELECT max(started_at) FROM ninja_agent_compliance.source_runs) AS source_runs_last,
       (SELECT max(observed_at) FROM ninja_agent_compliance.platform_observations) AS platform_observations_last,
       (SELECT max(evaluated_at) FROM ninja_agent_compliance.compliance_matrix_history) AS matrix_history_last;
-- L8: owners of legacy-schema relations.
SELECT n.nspname AS schema_name, pg_catalog.pg_get_userbyid(c.relowner) AS owner, count(*) AS relations
  FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname IN ('ninja_core', 'ninja_agent_compliance', 'ninja_inventory')
   AND c.relkind IN ('r', 'm', 'v', 'p')
 GROUP BY 1, 2
 ORDER BY 1, 2;
-- L9: rows per operations table that name a removed Job key (agent compliance and parity check).
WITH cols AS (
    SELECT table_name, column_name
      FROM information_schema.columns
     WHERE table_schema = 'operations'
       AND column_name IN ('job_key', 'definition_key', 'successor_key', 'prerequisite_key', 'predecessor_key')
       AND table_name IN (SELECT table_name FROM information_schema.tables
                           WHERE table_schema = 'operations' AND table_type = 'BASE TABLE')
)
SELECT table_name, column_name,
       (xpath('/row/c/text()', query_to_xml(format(
           'SELECT count(*) AS c FROM operations.%I WHERE %I IN (%L, %L, %L, %L)',
           table_name, column_name, 'agent-compliance', 'agent-compliance-evaluate',
           'agent-compliance-review-digest', 'parity-check'), false, true, '')))[1]::text::bigint AS rows
  FROM cols
 ORDER BY 1, 2;
-- L10: state of the schedules that belong to removed Jobs.
SELECT definition_key, enabled
  FROM operations.job_schedules
 WHERE definition_key IN ('agent-compliance', 'agent-compliance-evaluate',
                          'agent-compliance-review-digest', 'parity-check')
 ORDER BY 1;
-- L11: run states for the removed Jobs (every request belongs to a run; a non-terminal run would reach the worker).
SELECT status, count(*) AS rows, max(requested_at) AS last_requested
  FROM operations.operator_job_runs
 WHERE job_key IN ('agent-compliance', 'agent-compliance-evaluate',
                   'agent-compliance-review-digest', 'parity-check')
 GROUP BY status
 ORDER BY 1;
-- L12: migration 118's guard checks, read-only: outside view dependents and outside foreign keys.
SELECT 'view' AS kind, string_agg(DISTINCT dep_ns.nspname || '.' || dep.relname, ', ') AS dependents
  FROM pg_catalog.pg_depend d
  JOIN pg_catalog.pg_rewrite r ON r.oid = d.objid
  JOIN pg_catalog.pg_class dep ON dep.oid = r.ev_class
  JOIN pg_catalog.pg_namespace dep_ns ON dep_ns.oid = dep.relnamespace
  JOIN pg_catalog.pg_class ref ON ref.oid = d.refobjid
  JOIN pg_catalog.pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
 WHERE d.classid = 'pg_catalog.pg_rewrite'::regclass
   AND ref_ns.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
   AND dep_ns.nspname NOT IN ('ninja_agent_compliance', 'ninja_inventory')
UNION ALL
SELECT 'foreign_key', string_agg(DISTINCT con.conrelid::regclass::text, ', ')
  FROM pg_catalog.pg_constraint con
  JOIN pg_catalog.pg_class ref ON ref.oid = con.confrelid
  JOIN pg_catalog.pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
  JOIN pg_catalog.pg_class src ON src.oid = con.conrelid
  JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src.relnamespace
 WHERE con.contype = 'f'
   AND ref_ns.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
   AND src_ns.nspname NOT IN ('ninja_agent_compliance', 'ninja_inventory');
-- L13: foreign keys and view dependents on the snapshot and daily-presence tables (117, 0350).
SELECT 'view' AS kind, string_agg(DISTINCT dep_ns.nspname || '.' || dep.relname, ', ') AS dependents
  FROM pg_catalog.pg_depend d
  JOIN pg_catalog.pg_rewrite r ON r.oid = d.objid
  JOIN pg_catalog.pg_class dep ON dep.oid = r.ev_class
  JOIN pg_catalog.pg_namespace dep_ns ON dep_ns.oid = dep.relnamespace
 WHERE d.classid = 'pg_catalog.pg_rewrite'::regclass
   AND d.refobjid IN ('ninja_core.device_snapshots'::regclass, 'ninja_core.device_health_snapshots'::regclass,
                      'operations.source_record_seen_daily'::regclass)
   AND dep.oid NOT IN ('operations.ninja_device_seen_daily_shadow'::regclass)
UNION ALL
SELECT 'foreign_key', string_agg(DISTINCT con.conrelid::regclass::text, ', ')
  FROM pg_catalog.pg_constraint con
 WHERE con.contype = 'f'
   AND con.confrelid IN ('ninja_core.device_snapshots'::regclass, 'ninja_core.device_health_snapshots'::regclass,
                         'operations.source_record_seen_daily'::regclass);
-- L14: routines outside the dropped objects whose body names a dropped schema or table (by text).
SELECT n.nspname AS schema_name, p.proname, p.prokind,
       (p.prosrc ~* 'ninja_agent_compliance') AS names_agent_compliance,
       (p.prosrc ~* 'ninja_inventory') AS names_inventory,
       (p.prosrc ~* 'device_snapshots|device_health_snapshots') AS names_snapshots,
       (p.prosrc ~* 'source_record_seen_daily|seen_daily_shadow') AS names_daily_presence
  FROM pg_catalog.pg_proc p
  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'ninja_agent_compliance', 'ninja_inventory')
   AND p.prosrc ~* 'ninja_agent_compliance|ninja_inventory|device_snapshots|device_health_snapshots|source_record_seen_daily|seen_daily_shadow'
 ORDER BY 1, 2;
-- L15: triggers, event triggers, policies and column defaults outside the dropped objects that touch them.
SELECT 'trigger' AS kind, tgrelid::regclass::text AS on_object, tgname AS name, tgfoid::regprocedure::text AS detail
  FROM pg_catalog.pg_trigger t
  JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
 WHERE NOT t.tgisinternal
   AND (n.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
        OR tgrelid IN (SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace cn ON cn.oid = c.relnamespace
                        WHERE (cn.nspname, c.relname) IN (('ninja_core','device_snapshots'), ('ninja_core','device_health_snapshots'),
                                                          ('operations','source_record_seen_daily'))))
UNION ALL
SELECT 'event_trigger', evtevent, evtname, evtfoid::regprocedure::text FROM pg_catalog.pg_event_trigger
UNION ALL
SELECT 'policy', pol.polrelid::regclass::text, pol.polname,
       left(coalesce(pg_catalog.pg_get_expr(pol.polqual, pol.polrelid), ''), 200)
  FROM pg_catalog.pg_policy pol
 WHERE coalesce(pg_catalog.pg_get_expr(pol.polqual, pol.polrelid), '') || coalesce(pg_catalog.pg_get_expr(pol.polwithcheck, pol.polrelid), '')
       ~* 'ninja_agent_compliance|ninja_inventory|device_snapshots|seen_daily'
UNION ALL
SELECT 'default', d.adrelid::regclass::text, a.attname, left(pg_catalog.pg_get_expr(d.adbin, d.adrelid), 200)
  FROM pg_catalog.pg_attrdef d
  JOIN pg_catalog.pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
 WHERE pg_catalog.pg_get_expr(d.adbin, d.adrelid) ~* 'ninja_agent_compliance|ninja_inventory|device_snapshots|seen_daily';
-- L16: every catalog dependency (any object class) from outside the two schemas onto an object inside them.
WITH inside AS (
    SELECT c.oid, 'pg_catalog.pg_class'::regclass AS classid FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
    UNION ALL
    SELECT t.oid, 'pg_catalog.pg_type'::regclass FROM pg_catalog.pg_type t
      JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
    UNION ALL
    SELECT p.oid, 'pg_catalog.pg_proc'::regclass FROM pg_catalog.pg_proc p
      JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname IN ('ninja_agent_compliance', 'ninja_inventory')
)
SELECT d.classid::regclass::text AS dependent_class,
       pg_catalog.pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent,
       pg_catalog.pg_describe_object(d.refclassid, d.refobjid, 0) AS referenced
  FROM pg_catalog.pg_depend d
  JOIN inside i ON i.oid = d.refobjid AND i.classid = d.refclassid
 WHERE d.deptype IN ('n', 'a')
   AND NOT EXISTS (SELECT 1 FROM inside self WHERE self.oid = d.objid AND self.classid = d.classid)
   AND pg_catalog.pg_describe_object(d.classid, d.objid, d.objsubid)
       !~ '(ninja_agent_compliance|ninja_inventory)\.'
 LIMIT 50;
