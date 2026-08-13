-- 097: make the agent-compliance stale-age default 180 days.
--
-- This applies to every customer and scope, including existing overrides.
-- Required-platform selections are not changed.

ALTER TABLE ninja_agent_compliance.clients
    ALTER COLUMN default_max_age_days SET DEFAULT 180;

-- Existing client rows use this column when no platform requirement applies.
UPDATE ninja_agent_compliance.clients
SET default_max_age_days = 180,
    updated_at = now(),
    updated_by = 'migration_097'
WHERE default_max_age_days IS DISTINCT FROM 180;

-- Align all existing default and customer-specific scope profiles.
UPDATE ninja_agent_compliance.platform_requirements
SET max_age_days = 180,
    updated_at = now(),
    updated_by = 'migration_097'
WHERE max_age_days IS DISTINCT FROM 180;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_required_platforms_effective AS
WITH customers AS (
    SELECT client_id, client_name
    FROM ninja_agent_compliance.clients
    WHERE enabled
      AND source NOT IN ('alignment', 'demoted')
      AND lower(trim(client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
),
scopes(device_scope, label) AS (
    VALUES
        ('all', 'All devices'),
        ('server', 'Servers'),
        ('workstation', 'Workstations')
),
effective AS (
    SELECT
        c.client_id,
        c.client_name,
        s.device_scope,
        s.label,
        req.required_platforms,
        req.max_age_days,
        req.source,
        req.source_scope,
        req.client_id AS source_client_id
    FROM customers c
    CROSS JOIN scopes s
    JOIN LATERAL (
        SELECT
            pr.client_id,
            pr.device_scope AS source_scope,
            pr.required_platforms,
            pr.max_age_days,
            pr.source
        FROM ninja_agent_compliance.platform_requirements pr
        WHERE pr.enabled
          AND (
              (pr.client_id = c.client_id AND pr.device_scope = s.device_scope)
              OR (pr.client_id = c.client_id AND pr.device_scope = 'all')
              OR (pr.client_id IS NULL AND pr.device_scope = s.device_scope)
              OR (pr.client_id IS NULL AND pr.device_scope = 'all')
          )
        ORDER BY
            CASE
                WHEN pr.client_id = c.client_id AND pr.device_scope = s.device_scope THEN 0
                WHEN pr.client_id = c.client_id AND pr.device_scope = 'all' THEN 1
                WHEN pr.client_id IS NULL AND pr.device_scope = s.device_scope THEN 2
                ELSE 3
            END
        LIMIT 1
    ) req ON true
)
SELECT
    client_id,
    client_name,
    device_scope,
    label,
    required_platforms,
    COALESCE(max_age_days, 180) AS max_age_days,
    CASE WHEN 'Ninja' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS ninja_required,
    CASE WHEN 'SentinelOne' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS sentinelone_required,
    CASE WHEN 'LogMeIn' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS logmein_required,
    CASE WHEN 'ScreenConnect' = ANY(required_platforms) THEN 'On' ELSE 'Off' END AS screenconnect_required,
    CASE
        WHEN source_client_id IS NULL THEN 'Using default'
        WHEN source_scope <> device_scope THEN 'Customer setting from all devices'
        ELSE 'Customer setting'
    END AS setting_source,
    source_client_id IS NOT NULL AND source_scope = device_scope AS can_use_default
FROM effective
ORDER BY client_name, CASE device_scope WHEN 'all' THEN 0 WHEN 'server' THEN 1 ELSE 2 END;
