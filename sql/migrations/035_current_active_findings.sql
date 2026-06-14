-- Active findings must be current and deduped, not one row per run.
-- The findings table is append/history-oriented; dashboards and alert
-- review need the latest active row per finding signature.

CREATE OR REPLACE VIEW ninja_agent_compliance.v_active_findings AS
WITH latest AS (
    SELECT DISTINCT ON (f.finding_signature)
        f.*
    FROM ninja_agent_compliance.compliance_findings f
    WHERE f.status = 'active'
    ORDER BY f.finding_signature, f.last_seen_at DESC, f.finding_id DESC
)
SELECT f.*
FROM latest f
WHERE NOT EXISTS (
    SELECT 1
    FROM ninja_agent_compliance.alert_suppressions s
    WHERE s.enabled
      AND (s.client_id IS NULL OR s.client_id = f.client_id)
      AND (s.norm_name IS NULL OR s.norm_name = f.norm_name)
      AND (s.finding_type IS NULL OR s.finding_type = f.finding_type)
      AND (s.affected_platform IS NULL OR s.affected_platform = f.affected_platform)
      AND (s.expires_at IS NULL OR s.expires_at > now())
)
ORDER BY severity DESC, last_seen_at DESC;
