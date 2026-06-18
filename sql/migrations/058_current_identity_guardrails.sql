-- Tighten identity guardrail views to current source state.
--
-- v0.32.7 introduced guardrails over all retained platform_observations.
-- That is useful for forensics but too noisy for operational checks
-- because historical pre-id-link rows keep counting forever. These
-- current-state views use each source's latest successful run.

CREATE OR REPLACE VIEW ninja_agent_compliance.v_native_device_customer_conflicts AS
WITH latest_ok_runs AS (
    SELECT DISTINCT ON (sr.source_id)
        sr.source_id,
        sr.source_run_id
    FROM ninja_agent_compliance.source_runs sr
    WHERE sr.status = 'ok'
    ORDER BY sr.source_id, sr.started_at DESC
),
latest_observations AS (
    SELECT po.*
    FROM ninja_agent_compliance.platform_observations po
    JOIN latest_ok_runs lr ON lr.source_run_id = po.source_run_id
)
SELECT
    platform,
    platform_device_id,
    array_agg(DISTINCT resolved_client_id ORDER BY resolved_client_id) AS client_ids,
    array_agg(DISTINCT resolved_client_name ORDER BY resolved_client_name) AS client_names,
    count(DISTINCT resolved_client_id) AS client_count,
    max(observed_at) AS last_seen_at
FROM latest_observations
WHERE resolved_client_id IS NOT NULL
  AND COALESCE(NULLIF(platform_device_id, ''), '') <> ''
GROUP BY platform, platform_device_id
HAVING count(DISTINCT resolved_client_id) > 1
ORDER BY client_count DESC, platform, platform_device_id;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_unmapped_platform_customers AS
WITH latest_ok_runs AS (
    SELECT DISTINCT ON (sr.source_id)
        sr.source_id,
        sr.source_run_id
    FROM ninja_agent_compliance.source_runs sr
    WHERE sr.status = 'ok'
    ORDER BY sr.source_id, sr.started_at DESC
),
latest_observations AS (
    SELECT po.*
    FROM ninja_agent_compliance.platform_observations po
    JOIN latest_ok_runs lr ON lr.source_run_id = po.source_run_id
)
SELECT
    po.platform,
    po.source_id,
    po.source_name,
    po.platform_group_id,
    po.platform_group_name,
    count(*) AS observations,
    count(DISTINCT po.norm_name) AS distinct_devices,
    max(po.observed_at) AS last_seen_at
FROM latest_observations po
WHERE po.resolved_client_id IS NULL
  AND COALESCE(NULLIF(po.platform_group_name, ''), '') <> ''
  AND NOT EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.org_excludes e
      WHERE e.enabled
        AND e.pattern = lower(trim(po.platform_group_name))
  )
GROUP BY po.platform, po.source_id, po.source_name, po.platform_group_id, po.platform_group_name
ORDER BY last_seen_at DESC, observations DESC;
