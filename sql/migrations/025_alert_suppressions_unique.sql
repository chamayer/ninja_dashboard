CREATE UNIQUE INDEX IF NOT EXISTS alert_suppressions_unique_key
ON ninja_agent_compliance.alert_suppressions (
    COALESCE(client_id, 0),
    COALESCE(norm_name, ''),
    COALESCE(finding_type, ''),
    COALESCE(affected_platform, '')
)
WHERE enabled;
