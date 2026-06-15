-- Restore the "online in" wording introduced by migration 040.
-- Migration 041 rebuilt v_device_work_queue and v_all_devices_human
-- from an older copy and reintroduced "seen online in".
--
-- Also promote the actionable cross-customer case back into the device
-- work queue: when a device is missing a required platform under one
-- customer while the same hostname is observed running that platform
-- under another customer, it is a Fix now item. The broader
-- same-name-across-customers noise stays demoted.
--
-- cross_customer_actionable_platforms is appended at the end of each
-- view (CREATE OR REPLACE requires preserving existing column order;
-- new columns must go at the end). The classified CTE is split into
-- two stages so the work_state CASE can reference the new column
-- without the SQL alias-self-reference error.

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_work_queue AS
WITH base AS (
    SELECT
        m.*,
        ARRAY(
            SELECT p
            FROM unnest(m.missing_required_platforms) AS p
            WHERE NOT (p = 'SentinelOne' AND m.s1_exempt)
              AND p <> ALL(m.source_failed_platforms)
        )::text[] AS action_missing_platforms,
        ARRAY(
            SELECT p
            FROM unnest(m.stale_required_platforms) AS p
            WHERE p <> ALL(m.source_failed_platforms)
        )::text[] AS action_stale_platforms,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN m.ninja_online THEN 'Ninja' END,
            CASE WHEN m.screenconnect_online THEN 'ScreenConnect' END,
            CASE WHEN m.sentinelone_online THEN 'SentinelOne' END,
            CASE WHEN m.logmein_online THEN 'LogMeIn' END
        ], NULL)::text[] AS online_platforms,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN m.in_ninja THEN 'Ninja' END,
            CASE WHEN m.in_screenconnect THEN 'ScreenConnect' END,
            CASE WHEN m.in_sentinelone THEN 'SentinelOne' END,
            CASE WHEN m.in_logmein THEN 'LogMeIn' END
        ], NULL)::text[] AS found_platforms,
        GREATEST(
            m.ninja_last_seen,
            m.screenconnect_last_seen,
            m.sentinelone_last_seen,
            m.logmein_last_seen
        ) AS last_seen_anywhere,
        EXISTS (
            SELECT 1
            FROM ninja_agent_compliance.alert_suppressions s
            WHERE s.enabled
              AND (s.client_id IS NULL OR s.client_id = m.client_id)
              AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
              AND (s.expires_at IS NULL OR s.expires_at > now())
        ) AS ignored
    FROM ninja_agent_compliance.compliance_matrix_current m
    WHERE NOT EXISTS (
        SELECT 1
        FROM ninja_agent_compliance.org_excludes e
        WHERE e.enabled
          AND e.pattern = lower(trim(m.client_name))
    )
),
with_actionable AS (
    SELECT
        b.*,
        ARRAY(
            SELECT DISTINCT p
            FROM unnest(b.action_missing_platforms) AS p
            WHERE EXISTS (
                SELECT 1
                FROM ninja_agent_compliance.compliance_matrix_current other
                WHERE other.norm_name = b.norm_name
                  AND other.client_id <> b.client_id
                  AND p = ANY(other.observed_platforms)
            )
        )::text[] AS cross_customer_actionable_platforms
    FROM base b
),
classified AS (
    SELECT
        a.*,
        CASE
            WHEN cardinality(a.cross_customer_actionable_platforms) > 0
                THEN 'Missing '
                     || array_to_string(a.cross_customer_actionable_platforms, ', ')
                     || '; same name under another customer'
            WHEN cardinality(a.action_missing_platforms) > 0
                 AND cardinality(a.online_platforms) > 0
                THEN 'Missing ' || array_to_string(a.action_missing_platforms, ', ')
                     || '; online in ' || array_to_string(a.online_platforms, ', ')
            WHEN cardinality(a.action_missing_platforms) > 0
                THEN 'Missing ' || array_to_string(a.action_missing_platforms, ', ')
            WHEN cardinality(a.action_stale_platforms) > 0
                THEN 'Stale ' || array_to_string(a.action_stale_platforms, ', ')
            WHEN a.is_degraded THEN 'Agent looks degraded'
            ELSE 'Needs review'
        END AS issue,
        CASE
            WHEN cardinality(a.cross_customer_actionable_platforms) > 0 THEN 'Fix now'
            WHEN cardinality(a.action_missing_platforms) > 0
                 AND cardinality(a.online_platforms) > 0 THEN 'Fix now'
            WHEN cardinality(a.action_missing_platforms) > 0 THEN 'Review'
            WHEN a.is_degraded THEN 'Review'
            WHEN cardinality(a.action_stale_platforms) > 0 THEN 'Stale'
            ELSE 'Review'
        END AS work_state
    FROM with_actionable a
)
SELECT
    client_id,
    client_name,
    norm_name,
    hostname,
    device_type,
    os_name,
    domain_name,
    required_platforms,
    found_platforms,
    action_missing_platforms AS missing_platforms,
    action_stale_platforms AS stale_platforms,
    source_failed_platforms,
    online_platforms,
    last_seen_anywhere,
    issue,
    work_state,
    s1_exempt,
    is_degraded,
    is_stale,
    cross_client_conflict,
    finding_signature,
    evaluated_at,
    cross_customer_actionable_platforms
FROM classified
WHERE NOT ignored
  AND NOT is_unknown
  AND (
      cardinality(action_missing_platforms) > 0
      OR cardinality(action_stale_platforms) > 0
      OR is_degraded
      OR cardinality(cross_customer_actionable_platforms) > 0
  )
ORDER BY
    CASE work_state
        WHEN 'Fix now' THEN 0
        WHEN 'Review' THEN 1
        WHEN 'Stale' THEN 2
        ELSE 3
    END,
    client_name,
    hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_all_devices_human AS
WITH base AS (
    SELECT
        m.*,
        ARRAY(
            SELECT p
            FROM unnest(m.missing_required_platforms) AS p
            WHERE NOT (p = 'SentinelOne' AND m.s1_exempt)
              AND p <> ALL(m.source_failed_platforms)
        )::text[] AS action_missing_platforms,
        ARRAY(
            SELECT p
            FROM unnest(m.stale_required_platforms) AS p
            WHERE p <> ALL(m.source_failed_platforms)
        )::text[] AS action_stale_platforms,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN m.ninja_online THEN 'Ninja' END,
            CASE WHEN m.screenconnect_online THEN 'ScreenConnect' END,
            CASE WHEN m.sentinelone_online THEN 'SentinelOne' END,
            CASE WHEN m.logmein_online THEN 'LogMeIn' END
        ], NULL)::text[] AS online_platforms,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN m.in_ninja THEN 'Ninja' END,
            CASE WHEN m.in_screenconnect THEN 'ScreenConnect' END,
            CASE WHEN m.in_sentinelone THEN 'SentinelOne' END,
            CASE WHEN m.in_logmein THEN 'LogMeIn' END
        ], NULL)::text[] AS found_platforms,
        GREATEST(
            m.ninja_last_seen,
            m.screenconnect_last_seen,
            m.sentinelone_last_seen,
            m.logmein_last_seen
        ) AS last_seen_anywhere,
        EXISTS (
            SELECT 1
            FROM ninja_agent_compliance.alert_suppressions s
            WHERE s.enabled
              AND (s.client_id IS NULL OR s.client_id = m.client_id)
              AND (s.norm_name IS NULL OR s.norm_name = m.norm_name)
              AND (s.expires_at IS NULL OR s.expires_at > now())
        ) AS ignored
    FROM ninja_agent_compliance.compliance_matrix_current m
),
with_actionable AS (
    SELECT
        b.*,
        ARRAY(
            SELECT DISTINCT p
            FROM unnest(b.action_missing_platforms) AS p
            WHERE EXISTS (
                SELECT 1
                FROM ninja_agent_compliance.compliance_matrix_current other
                WHERE other.norm_name = b.norm_name
                  AND other.client_id <> b.client_id
                  AND p = ANY(other.observed_platforms)
            )
        )::text[] AS cross_customer_actionable_platforms
    FROM base b
)
SELECT
    client_id,
    client_name,
    norm_name,
    hostname,
    device_type,
    os_name,
    domain_name,
    required_platforms,
    found_platforms,
    action_missing_platforms AS missing_platforms,
    action_stale_platforms AS stale_platforms,
    source_failed_platforms,
    online_platforms,
    last_seen_anywhere,
    CASE
        WHEN ignored THEN 'Ignored'
        WHEN cardinality(cross_customer_actionable_platforms) > 0 THEN 'Fix now'
        WHEN cardinality(action_missing_platforms) > 0
             AND cardinality(online_platforms) > 0 THEN 'Fix now'
        WHEN cardinality(action_missing_platforms) > 0 THEN 'Review'
        WHEN is_degraded THEN 'Review'
        WHEN is_unknown THEN 'Review'
        WHEN cardinality(action_stale_platforms) > 0 THEN 'Stale'
        WHEN is_compliant THEN 'Good'
        ELSE 'Review'
    END AS state,
    CASE
        WHEN ignored THEN 'Ignored'
        WHEN cardinality(cross_customer_actionable_platforms) > 0 THEN
            'Missing ' || array_to_string(cross_customer_actionable_platforms, ', ')
            || '; same name under another customer'
        WHEN cardinality(action_missing_platforms) > 0 THEN 'Missing ' || array_to_string(action_missing_platforms, ', ')
        WHEN is_degraded THEN 'Agent looks degraded'
        WHEN is_unknown THEN 'Unknown device state'
        WHEN cardinality(action_stale_platforms) > 0 THEN 'Stale ' || array_to_string(action_stale_platforms, ', ')
        WHEN cardinality(source_failed_platforms) > 0 THEN 'Data unavailable from ' || array_to_string(source_failed_platforms, ', ')
        ELSE 'No current issue'
    END AS issue,
    s1_exempt,
    ignored,
    evaluated_at,
    cross_customer_actionable_platforms
FROM with_actionable
ORDER BY client_name, hostname;
