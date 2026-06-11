ALTER TABLE ninja_agent_compliance.alert_suppressions
    ADD COLUMN IF NOT EXISTS display_name text;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_ignores_current AS
SELECT
    s.suppression_id,
    s.client_id,
    c.client_name,
    COALESCE(NULLIF(s.display_name, ''), s.norm_name) AS display_name,
    s.norm_name,
    s.reason,
    s.expires_at,
    s.updated_at,
    s.updated_by
FROM ninja_agent_compliance.alert_suppressions s
JOIN ninja_agent_compliance.clients c ON c.client_id = s.client_id
WHERE s.enabled
  AND s.finding_type IS NULL
  AND s.affected_platform IS NULL
  AND s.norm_name IS NOT NULL
ORDER BY s.updated_at DESC, c.client_name, s.norm_name;
