-- PLAN-056: metadata only; no source/customer rows or environment values.
-- Run with psql -X -v ON_ERROR_STOP=1 in the reviewed target database.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '1s';

WITH expected(name) AS (
    VALUES ('0405_jobs_claim_successor_guard'),
           ('0406_batch_source_client_evidence'),
           ('0407_software_overview_aggregate'),
           ('0408_software_overview_expiry'),
           ('0409_software_overview_publication_fence'),
           ('0410_software_overview_protected_read')
)
SELECT expected.name, EXISTS (
    SELECT 1 FROM operations.django_migrations applied
     WHERE applied.app = 'operations' AND applied.name = expected.name
) AS applied
FROM expected ORDER BY expected.name;

WITH required(relation) AS (
    VALUES ('operations.finding_types'), ('operations.findings'),
           ('operations.software_device_readiness'),
           ('operations.condition_assessments'),
           ('operations.condition_participants'),
           ('operations.device_software_exposure_current')
)
SELECT relation, to_regclass(relation) IS NOT NULL AS present,
       has_table_privilege('ninja_ingest', to_regclass(relation), 'SELECT') AS ingest_select,
       pg_has_role('ninja_ingest', relation_owner.relowner, 'USAGE') AS ingest_owner_rights
FROM required
LEFT JOIN pg_class relation_owner ON relation_owner.oid = to_regclass(relation)
ORDER BY relation;

WITH protected(relation) AS (
    VALUES ('operations.software_overview_current'), ('operations.v_software_overview')
)
SELECT relation, to_regclass(relation) IS NOT NULL AS present,
       has_table_privilege('operations_app', to_regclass(relation), 'SELECT') AS app_select,
       has_table_privilege('ninja_ingest', to_regclass(relation), 'UPDATE') AS ingest_update
FROM protected ORDER BY relation;

SELECT relation.relname, owner.rolname AS owner_role,
       pg_has_role('ninja_ingest', relation.relowner, 'USAGE') AS ingest_owner_rights
  FROM pg_class relation JOIN pg_namespace schema ON schema.oid = relation.relnamespace
  JOIN pg_roles owner ON owner.oid = relation.relowner
 WHERE schema.nspname = 'operations'
   AND relation.relname IN ('finding_types', 'device_software_exposure_current')
 ORDER BY relation.relname;

-- Inspect observed ingest pools without exposing connection strings or queries.
-- Zero observed roles is inconclusive; this does not identify worker processes.
WITH runtime AS (
    SELECT DISTINCT usesysid FROM pg_stat_activity
     WHERE application_name = 'ingest' AND datname = current_database()
)
SELECT count(*) AS observed_pool_roles,
       bool_and(role.rolname = 'ninja_ingest') AS all_use_declared_ingest_role,
       bool_or(role.rolsuper) AS any_superuser,
       bool_and(has_table_privilege(runtime.usesysid,
           'operations.finding_types'::regclass, 'SELECT')) AS all_can_read_finding_types,
       bool_and(role.rolsuper OR pg_has_role(runtime.usesysid,
           exposure.relowner, 'USAGE')) AS all_have_exposure_owner_rights
  FROM runtime JOIN pg_roles role ON role.oid = runtime.usesysid
 CROSS JOIN pg_class exposure
 WHERE exposure.oid = 'operations.device_software_exposure_current'::regclass;

ROLLBACK;
