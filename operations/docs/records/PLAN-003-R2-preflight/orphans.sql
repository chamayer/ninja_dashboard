-- PLAN-003 R2: inspect admin assessments/participants whose admin finding is
-- missing. Read-only; identifiers, kinds and times only.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

SELECT 'assessment' AS relation, x.finding_id, x.participant_kind, x.participant_role,
       x.policy_version, x.assessed_at,
       EXISTS (SELECT 1 FROM operations.findings f WHERE f.id = x.finding_id) AS in_entity_ledger
  FROM operations.condition_assessments x
 WHERE x.row_kind = 'admin'
   AND NOT EXISTS (SELECT 1 FROM operations.admin_findings a WHERE a.id = x.finding_id)
UNION ALL
SELECT 'participant', x.finding_id, x.participant_kind, x.participant_role, NULL, NULL,
       EXISTS (SELECT 1 FROM operations.findings f WHERE f.id = x.finding_id)
  FROM operations.condition_participants x
 WHERE x.row_kind = 'admin'
   AND NOT EXISTS (SELECT 1 FROM operations.admin_findings a WHERE a.id = x.finding_id)
 ORDER BY 2, 1;

-- Recorded history for those finding IDs, if admin_findings is history-covered.
SELECT h.entity_key, h.operation, h.recorded_at, a.reason,
       h.before_values ->> 'finding_type_id' AS finding_type_id,
       h.before_values ->> 'status' AS status_before
  FROM operations.admin_findings_change_history h
  JOIN operations.change_actions a ON a.id = h.action_id
 WHERE h.entity_key IN (
       SELECT x.finding_id::text FROM operations.condition_assessments x
        WHERE x.row_kind = 'admin'
          AND NOT EXISTS (SELECT 1 FROM operations.admin_findings f WHERE f.id = x.finding_id))
 ORDER BY h.entity_key, h.recorded_at;

ROLLBACK;
