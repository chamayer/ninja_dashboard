CREATE OR REPLACE VIEW ninja_agent_compliance.v_active_findings AS
SELECT f.*
FROM ninja_agent_compliance.compliance_findings f
WHERE f.status = 'active'
  AND NOT EXISTS (
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

CREATE OR REPLACE VIEW ninja_agent_compliance.v_remediation_candidates AS
SELECT m.*
FROM ninja_agent_compliance.compliance_matrix_current m
WHERE NOT m.is_compliant
  AND NOT m.is_unknown
  AND NOT EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.alert_suppressions s
      WHERE s.enabled
        AND (s.client_id IS NULL OR s.client_id = m.client_id)
        AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
        AND (s.expires_at IS NULL OR s.expires_at > now())
  )
ORDER BY client_name, hostname;
