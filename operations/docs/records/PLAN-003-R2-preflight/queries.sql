-- PLAN-003 R2 (M2-M4) preflight. Read-only; run as the database owner so every
-- tenant is visible. Each result feeds a conversion or abort decision.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

-- 1. Population by namespace, tenant, type and status group.
SELECT 'entity' AS namespace, f.tenant_id, t.name AS finding_type,
       CASE WHEN f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            THEN 'active' ELSE 'closed' END AS status_group, count(*)
  FROM operations.findings f JOIN operations.finding_types t ON t.id = f.finding_type_id
 GROUP BY 1, 2, 3, 4
UNION ALL
SELECT 'admin', a.tenant_id, t.name,
       CASE WHEN a.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            THEN 'active' ELSE 'closed' END, count(*)
  FROM operations.admin_findings a JOIN operations.finding_types t ON t.id = a.finding_type_id
 GROUP BY 1, 2, 3, 4
 ORDER BY 1, 2, 3, 4;

-- 2. UUIDs present in both ledgers (must be zero: IDs are preserved on copy).
SELECT count(*) AS shared_ids
  FROM operations.findings f JOIN operations.admin_findings a ON a.id = f.id;

-- 3. Active keys present in both ledgers for the same tenant. Allowed after the
--    namespace-qualified uniqueness, but each needs an explicit disposition.
SELECT f.tenant_id, tf.name AS entity_type, ta.name AS admin_type, count(*)
  FROM operations.findings f
  JOIN operations.admin_findings a
    ON a.tenant_id = f.tenant_id AND a.condition_key = f.condition_key
  JOIN operations.finding_types tf ON tf.id = f.finding_type_id
  JOIN operations.finding_types ta ON ta.id = a.finding_type_id
 WHERE f.condition_key > ''
   AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
   AND a.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
 GROUP BY 1, 2, 3 ORDER BY 4 DESC;

-- 4. Admin subject_ref shapes per type (drives subject normalization).
SELECT t.name AS finding_type,
       (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(a.subject_ref) k) AS keys,
       count(*)
  FROM operations.admin_findings a JOIN operations.finding_types t ON t.id = a.finding_type_id
 WHERE jsonb_typeof(a.subject_ref) = 'object'
 GROUP BY 1, 2 ORDER BY 1, 3 DESC;
SELECT count(*) AS admin_subject_ref_not_object
  FROM operations.admin_findings WHERE jsonb_typeof(subject_ref) <> 'object';

-- 5. Assessments and participants by row_kind, and whether their finding resolves
--    in the ledger that row_kind names.
SELECT 'assessments' AS relation, x.row_kind,
       count(*) AS rows,
       count(*) FILTER (WHERE x.row_kind = 'entity' AND f.id IS NULL
                           OR x.row_kind = 'admin' AND a.id IS NULL) AS unresolved
  FROM operations.condition_assessments x
  LEFT JOIN operations.findings f ON f.id = x.finding_id
  LEFT JOIN operations.admin_findings a ON a.id = x.finding_id
 GROUP BY 1, 2
UNION ALL
SELECT 'participants', x.row_kind, count(*),
       count(*) FILTER (WHERE x.row_kind = 'entity' AND f.id IS NULL
                           OR x.row_kind = 'admin' AND a.id IS NULL)
  FROM operations.condition_participants x
  LEFT JOIN operations.findings f ON f.id = x.finding_id
  LEFT JOIN operations.admin_findings a ON a.id = x.finding_id
 GROUP BY 1, 2 ORDER BY 1, 2;

-- 6. Rows the R1 NOT VALID composite FKs would reject on validation (must be zero).
SELECT 'finding_state' AS relation, count(*) AS tenant_mismatch
  FROM operations.finding_state s JOIN operations.findings f ON f.id = s.finding_id
 WHERE s.tenant_id <> f.tenant_id
UNION ALL
SELECT 'source_action_requests', count(*)
  FROM operations.source_action_requests r JOIN operations.findings f ON f.id = r.finding_id
 WHERE r.tenant_id <> f.tenant_id;

-- 7. Runtime-role DML on graph-affecting tables (M3 revokes these).
SELECT table_name, grantee, string_agg(privilege_type, ',' ORDER BY privilege_type)
  FROM information_schema.role_table_grants
 WHERE table_schema = 'operations'
   AND table_name IN ('findings', 'admin_findings', 'condition_assessments',
                      'condition_participants', 'finding_types', 'finding_state')
   AND grantee IN ('operations_app', 'ninja_ingest')
   AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
 GROUP BY 1, 2 ORDER BY 1, 2;

-- 8. Existing cover configuration to seed relationship rules from.
SELECT t.name AS child_type, t.covered_by, t.cover_note
  FROM operations.finding_types t
 WHERE jsonb_array_length(t.covered_by) > 0
 ORDER BY 1;

ROLLBACK;
