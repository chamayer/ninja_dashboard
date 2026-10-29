-- PLAN-003 R2: the admin-labelled assessments whose finding lives in the entity
-- ledger. Read-only; type, status, times and assessment counts only.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

WITH odd AS (
    SELECT DISTINCT x.finding_id FROM operations.condition_assessments x
     WHERE x.row_kind = 'admin'
       AND NOT EXISTS (SELECT 1 FROM operations.admin_findings a WHERE a.id = x.finding_id)
)
SELECT f.id, t.name AS finding_type, f.status, f.first_seen_at, f.closed_at,
       (SELECT count(*) FROM operations.condition_assessments e
         WHERE e.finding_id = f.id AND e.row_kind = 'entity') AS entity_assessments,
       (SELECT count(*) FROM operations.condition_assessments e
         WHERE e.finding_id = f.id AND e.row_kind = 'admin') AS admin_assessments
  FROM odd JOIN operations.findings f ON f.id = odd.finding_id
  JOIN operations.finding_types t ON t.id = f.finding_type_id
 ORDER BY f.first_seen_at;

ROLLBACK;
