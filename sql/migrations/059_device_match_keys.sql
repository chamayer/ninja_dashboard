-- Device match-key support for Mac separator variants and manual merges.
--
-- The ingest pipeline can now evaluate a device under a merged match key
-- while keeping raw platform observations intact. These views expose the
-- same match-key logic to dashboards and drilldowns.

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_merge_candidates AS
WITH latest_obs AS (
    SELECT DISTINCT ON (resolved_client_id, platform, COALESCE(NULLIF(platform_device_id, ''), hostname))
        resolved_client_id AS client_id,
        resolved_client_name AS client_name,
        platform,
        platform_device_id,
        hostname,
        norm_name,
        os_name,
        last_seen_at,
        observed_at,
        regexp_replace(split_part(lower(coalesce(hostname, '')), '.', 1), '[^a-z0-9]', '', 'g') AS loose_norm
    FROM ninja_agent_compliance.platform_observations
    WHERE resolved_client_id IS NOT NULL
      AND hostname IS NOT NULL
      AND (
          os_name ILIKE '%macOS%'
          OR os_name ILIKE '%OS X%'
          OR os_name ILIKE '%Darwin%'
      )
    ORDER BY resolved_client_id, platform, COALESCE(NULLIF(platform_device_id, ''), hostname), observed_at DESC
),
groups AS (
    SELECT
        client_id,
        client_name,
        loose_norm,
        COUNT(DISTINCT platform) AS platform_count,
        COUNT(DISTINCT norm_name) AS norm_count,
        COUNT(*) AS device_count
    FROM latest_obs
    WHERE loose_norm <> ''
    GROUP BY client_id, client_name, loose_norm
    HAVING COUNT(DISTINCT platform) > 1
       AND COUNT(DISTINCT norm_name) > 1
),
ranked AS (
    SELECT
        o.*,
        ROW_NUMBER() OVER (
            PARTITION BY o.client_id, o.loose_norm
            ORDER BY
                CASE WHEN o.platform = 'Ninja' THEN 0 ELSE 1 END,
                length(o.norm_name),
                o.hostname
        ) AS target_rank
    FROM latest_obs o
    JOIN groups g
      ON g.client_id = o.client_id
     AND g.loose_norm = o.loose_norm
),
targets AS (
    SELECT *
    FROM ranked
    WHERE target_rank = 1
)
SELECT
    r.client_id,
    r.client_name,
    r.loose_norm,
    r.platform AS source_platform,
    r.hostname AS source_hostname,
    r.norm_name AS source_norm_name,
    t.platform AS target_platform,
    t.hostname AS target_hostname,
    t.norm_name AS target_norm_name,
    ARRAY_AGG(DISTINCT r2.platform ORDER BY r2.platform) AS platforms,
    ARRAY_AGG(DISTINCT r2.hostname ORDER BY r2.hostname) AS hostnames,
    ARRAY_AGG(DISTINCT r2.norm_name ORDER BY r2.norm_name) AS norm_names,
    MAX(r2.last_seen_at) AS last_seen_at
FROM ranked r
JOIN targets t
  ON t.client_id = r.client_id
 AND t.loose_norm = r.loose_norm
JOIN ranked r2
  ON r2.client_id = r.client_id
 AND r2.loose_norm = r.loose_norm
WHERE r.norm_name <> t.norm_name
  AND NOT EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.v_human_decisions_current d
      WHERE d.decision_type = 'same_device'
        AND d.client_id = r.client_id
        AND d.norm_name = r.norm_name
        AND d.candidate_name = t.norm_name
  )
GROUP BY
    r.client_id, r.client_name, r.loose_norm,
    r.platform, r.hostname, r.norm_name,
    t.platform, t.hostname, t.norm_name
ORDER BY r.client_name, r.loose_norm, r.platform;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_platform_detail_current AS
WITH raw_latest AS (
    SELECT DISTINCT ON (resolved_client_id, platform, COALESCE(NULLIF(platform_device_id, ''), hostname))
        resolved_client_id AS client_id,
        norm_name AS raw_norm_name,
        match_name,
        platform,
        platform_group_name,
        hostname AS platform_hostname,
        platform_device_id,
        os_name,
        is_online,
        last_seen_at,
        observed_at,
        COALESCE(NULLIF(match_name, ''), norm_name) AS stored_match_name,
        CASE
            WHEN os_name ILIKE '%macOS%'
              OR os_name ILIKE '%OS X%'
              OR os_name ILIKE '%Darwin%'
                THEN regexp_replace(split_part(lower(coalesce(hostname, '')), '.', 1), '[^a-z0-9]', '', 'g')
            ELSE NULL
        END AS mac_loose_name
    FROM ninja_agent_compliance.platform_observations
    WHERE resolved_client_id IS NOT NULL
    ORDER BY resolved_client_id, platform, COALESCE(NULLIF(platform_device_id, ''), hostname), observed_at DESC
),
obs_keys AS (
    SELECT r.*, r.raw_norm_name AS effective_norm_name
    FROM raw_latest r
    WHERE r.raw_norm_name IS NOT NULL
    UNION ALL
    SELECT r.*, r.stored_match_name AS effective_norm_name
    FROM raw_latest r
    WHERE r.stored_match_name IS NOT NULL
      AND r.stored_match_name <> r.raw_norm_name
    UNION ALL
    SELECT r.*, r.mac_loose_name AS effective_norm_name
    FROM raw_latest r
    WHERE r.mac_loose_name IS NOT NULL
      AND r.mac_loose_name <> ''
      AND r.mac_loose_name <> r.raw_norm_name
    UNION ALL
    SELECT r.*, d.candidate_name AS effective_norm_name
    FROM raw_latest r
    JOIN ninja_agent_compliance.v_human_decisions_current d
      ON d.decision_type = 'same_device'
     AND d.client_id = r.client_id
     AND d.norm_name = r.raw_norm_name
     AND d.candidate_name IS NOT NULL
),
latest_obs AS (
    SELECT DISTINCT ON (r.client_id, r.effective_norm_name, r.platform)
        r.client_id,
        r.effective_norm_name AS norm_name,
        r.platform,
        r.platform_group_name,
        r.platform_hostname,
        r.platform_device_id,
        r.is_online,
        r.last_seen_at,
        r.observed_at
    FROM obs_keys r
    WHERE r.effective_norm_name IS NOT NULL
      AND r.effective_norm_name <> ''
    ORDER BY r.client_id, r.effective_norm_name, r.platform, r.observed_at DESC
),
expanded AS (
    SELECT
        d.client_id,
        d.client_name,
        d.norm_name,
        d.hostname,
        s.device_state,
        s.needs_review,
        s.review_reason,
        s.state_reason,
        s.recommended_action,
        p.platform,
        p.platform = ANY(s.required_platforms) AS required,
        p.platform = ANY(s.present_platforms) AS found,
        p.platform = ANY(s.active_platforms) AS active,
        p.platform = ANY(s.missing_platforms) AS missing,
        p.platform = ANY(s.offline_platforms) AS offline,
        p.platform = ANY(s.source_failed_platforms) AS source_failed,
        p.platform = ANY(
            COALESCE(
                ARRAY(
                    SELECT DISTINCT match.value->>'platform'
                    FROM jsonb_array_elements(s.cross_customer_matches) AS match(value)
                ),
                ARRAY[]::text[]
            )
        ) AS found_under_other_customer,
        CASE p.platform
            WHEN 'Ninja' THEN d.ninja_last_seen
            WHEN 'ScreenConnect' THEN d.screenconnect_last_seen
            WHEN 'SentinelOne' THEN d.sentinelone_last_seen
            WHEN 'LogMeIn' THEN d.logmein_last_seen
            ELSE NULL
        END AS last_seen_at,
        CASE p.platform
            WHEN 'Ninja' THEN d.ninja_device_id
            WHEN 'ScreenConnect' THEN d.screenconnect_device_id
            WHEN 'SentinelOne' THEN d.sentinelone_device_id
            WHEN 'LogMeIn' THEN d.logmein_device_id
            ELSE NULL
        END AS platform_device_id
    FROM ninja_agent_compliance.compliance_matrix_current d
    JOIN ninja_agent_compliance.v_device_state_current s
      ON s.client_id = d.client_id
     AND s.norm_name = d.norm_name
    CROSS JOIN (VALUES
        ('Ninja'),
        ('ScreenConnect'),
        ('SentinelOne'),
        ('LogMeIn')
    ) AS p(platform)
)
SELECT
    e.client_id,
    e.client_name,
    e.norm_name,
    e.hostname,
    e.device_state,
    e.needs_review,
    e.review_reason,
    e.state_reason,
    e.recommended_action,
    e.platform,
    e.required,
    e.found,
    e.active,
    e.missing,
    e.offline,
    e.source_failed,
    e.found_under_other_customer,
    CASE
        WHEN e.source_failed THEN 'Source unavailable'
        WHEN NOT e.required THEN 'Not required'
        WHEN e.missing THEN 'Missing'
        WHEN e.offline THEN 'Offline'
        WHEN e.active THEN 'Active'
        WHEN e.found THEN 'Found'
        ELSE 'Not found'
    END AS platform_status,
    e.last_seen_at,
    CASE
        WHEN e.last_seen_at IS NULL THEN 'Never'
        ELSE GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (now() - e.last_seen_at)) / 86400))::int || ' day(s) ago'
    END AS age_text,
    lo.platform_group_name AS platform_customer,
    COALESCE(lo.platform_hostname, e.hostname) AS platform_hostname,
    COALESCE(lo.platform_device_id, e.platform_device_id) AS platform_device_id,
    CASE
        WHEN e.found_under_other_customer THEN 'Possible match under another customer'
        WHEN e.source_failed THEN 'Collector failed; do not blame device'
        WHEN e.missing THEN 'Required platform is absent'
        WHEN e.offline THEN 'Required platform is not checking in'
        WHEN NOT e.required THEN 'Platform is not required for this device'
        ELSE ''
    END AS notes
FROM expanded e
LEFT JOIN latest_obs lo
  ON lo.client_id = e.client_id
 AND lo.norm_name = e.norm_name
 AND lo.platform = e.platform
ORDER BY e.client_name, e.hostname,
    CASE e.platform
        WHEN 'Ninja' THEN 1
        WHEN 'SentinelOne' THEN 2
        WHEN 'LogMeIn' THEN 3
        WHEN 'ScreenConnect' THEN 4
        ELSE 9
    END;
