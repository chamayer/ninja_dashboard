-- Identity guardrail views for the client_id-first matching model.
--
-- Customer names are labels. The stable customer identity is
-- clients.client_id, normally reached through client_platform_links
-- using native platform customer/group IDs. These views expose cases
-- where a name, hostname, or native device ID could otherwise tempt a
-- name-based merge.

CREATE OR REPLACE VIEW ninja_agent_compliance.v_alias_collisions AS
WITH alias_keys AS (
    SELECT
        a.platform,
        a.alias_type,
        lower(trim(a.alias_value)) AS alias_value_norm,
        array_agg(DISTINCT a.alias_value ORDER BY a.alias_value) AS alias_values,
        array_agg(DISTINCT a.client_id ORDER BY a.client_id) AS client_ids,
        count(DISTINCT a.client_id) AS client_count,
        count(*) AS alias_rows
    FROM ninja_agent_compliance.client_aliases a
    JOIN ninja_agent_compliance.clients c ON c.client_id = a.client_id
    WHERE a.enabled
      AND c.enabled
      AND c.source <> 'demoted'
    GROUP BY a.platform, a.alias_type, lower(trim(a.alias_value))
)
SELECT *
FROM alias_keys
WHERE client_count > 1
ORDER BY platform, alias_type, alias_value_norm;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_platform_link_collisions AS
SELECT
    platform,
    platform_group_id,
    COALESCE(source_id, 0) AS source_id_key,
    array_agg(DISTINCT client_id ORDER BY client_id) AS client_ids,
    count(DISTINCT client_id) AS client_count,
    array_agg(DISTINCT COALESCE(last_seen_name, first_seen_name, '') ORDER BY COALESCE(last_seen_name, first_seen_name, '')) AS names_seen
FROM ninja_agent_compliance.client_platform_links
GROUP BY platform, platform_group_id, COALESCE(source_id, 0)
HAVING count(DISTINCT client_id) > 1
ORDER BY platform, platform_group_id;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_hostname_cross_customer_conflicts AS
SELECT
    norm_name,
    array_agg(DISTINCT client_id ORDER BY client_id) AS client_ids,
    array_agg(DISTINCT client_name ORDER BY client_name) AS client_names,
    count(DISTINCT client_id) AS client_count,
    array_agg(DISTINCT hostname ORDER BY hostname) AS hostnames,
    array_agg(DISTINCT unnest_platform ORDER BY unnest_platform) AS platforms
FROM (
    SELECT
        client_id,
        client_name,
        norm_name,
        hostname,
        unnest(observed_platforms) AS unnest_platform
    FROM ninja_agent_compliance.compliance_matrix_current
) m
GROUP BY norm_name
HAVING count(DISTINCT client_id) > 1
ORDER BY client_count DESC, norm_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_native_device_customer_conflicts AS
SELECT
    platform,
    platform_device_id,
    array_agg(DISTINCT resolved_client_id ORDER BY resolved_client_id) AS client_ids,
    array_agg(DISTINCT resolved_client_name ORDER BY resolved_client_name) AS client_names,
    count(DISTINCT resolved_client_id) AS client_count,
    max(observed_at) AS last_seen_at
FROM ninja_agent_compliance.platform_observations
WHERE resolved_client_id IS NOT NULL
  AND COALESCE(NULLIF(platform_device_id, ''), '') <> ''
GROUP BY platform, platform_device_id
HAVING count(DISTINCT resolved_client_id) > 1
ORDER BY client_count DESC, platform, platform_device_id;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_unmapped_platform_customers AS
SELECT
    po.platform,
    po.source_id,
    po.source_name,
    po.platform_group_id,
    po.platform_group_name,
    count(*) AS observations,
    count(DISTINCT po.norm_name) AS distinct_devices,
    max(po.observed_at) AS last_seen_at
FROM ninja_agent_compliance.platform_observations po
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
