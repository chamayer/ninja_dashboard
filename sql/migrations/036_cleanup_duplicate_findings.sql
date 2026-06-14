-- Clean historical finding noise created while compliance_findings was
-- append-only and old rows stayed active forever.
--
-- Keep:
--   * the latest row for each finding_signature
--   * any row referenced by alert_events, so delivery audit history
--     remains intact
--
-- Delete only unreferenced duplicate rows.

WITH ranked AS (
    SELECT
        f.finding_id,
        ROW_NUMBER() OVER (
            PARTITION BY f.finding_signature
            ORDER BY f.last_seen_at DESC, f.finding_id DESC
        ) AS rn
    FROM ninja_agent_compliance.compliance_findings f
)
DELETE FROM ninja_agent_compliance.compliance_findings f
USING ranked r
WHERE f.finding_id = r.finding_id
  AND r.rn > 1
  AND NOT EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.alert_events ae
      WHERE ae.finding_id = f.finding_id
  );

WITH latest AS (
    SELECT DISTINCT ON (finding_signature)
        finding_id,
        finding_signature
    FROM ninja_agent_compliance.compliance_findings
    ORDER BY finding_signature, last_seen_at DESC, finding_id DESC
)
UPDATE ninja_agent_compliance.compliance_findings f
SET status = 'resolved'
WHERE f.status = 'active'
  AND NOT EXISTS (
      SELECT 1
      FROM latest l
      WHERE l.finding_id = f.finding_id
  );
