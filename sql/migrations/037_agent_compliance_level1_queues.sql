-- Level 1 operations model for Agent Compliance.
--
-- These views separate the human queues from the raw compliance tables:
-- device work, notification readiness, customer-name review, setup state,
-- and source/system health. Dashboards should read from these views rather
-- than re-interpreting raw matrix/finding rows in each card.

DROP VIEW IF EXISTS ninja_agent_compliance.v_device_ignores_current;

CREATE VIEW ninja_agent_compliance.v_device_ignores_current AS
SELECT
    s.suppression_id,
    s.client_id,
    c.client_name,
    COALESCE(NULLIF(s.display_name, ''), s.norm_name) AS display_name,
    s.norm_name,
    s.reason,
    s.expires_at,
    CASE
        WHEN s.expires_at IS NULL THEN 'No expiry'
        WHEN s.expires_at <= now() THEN 'Expired'
        ELSE TO_CHAR(s.expires_at, 'YYYY-MM-DD')
    END AS expires,
    s.updated_at,
    s.updated_by
FROM ninja_agent_compliance.alert_suppressions s
JOIN ninja_agent_compliance.clients c ON c.client_id = s.client_id
WHERE s.enabled
  AND s.finding_type IS NULL
  AND s.affected_platform IS NULL
  AND s.norm_name IS NOT NULL
ORDER BY s.updated_at DESC, c.client_name, s.norm_name;

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
classified AS (
    SELECT
        b.*,
        CASE
            WHEN b.cross_client_conflict THEN 'Device appears under more than one customer'
            WHEN cardinality(b.action_missing_platforms) > 0
                 AND cardinality(b.online_platforms) > 0
                THEN 'Missing ' || array_to_string(b.action_missing_platforms, ', ')
                     || '; seen online in ' || array_to_string(b.online_platforms, ', ')
            WHEN cardinality(b.action_missing_platforms) > 0
                THEN 'Missing ' || array_to_string(b.action_missing_platforms, ', ')
            WHEN cardinality(b.action_stale_platforms) > 0
                THEN 'Stale ' || array_to_string(b.action_stale_platforms, ', ')
            WHEN b.is_degraded THEN 'Agent looks degraded'
            ELSE 'Needs review'
        END AS issue,
        CASE
            WHEN b.cross_client_conflict THEN 'Conflict'
            WHEN cardinality(b.action_missing_platforms) > 0
                 AND cardinality(b.online_platforms) > 0 THEN 'Fix now'
            WHEN cardinality(b.action_missing_platforms) > 0 THEN 'Review'
            WHEN cardinality(b.action_stale_platforms) > 0 THEN 'Stale'
            WHEN b.is_degraded THEN 'Degraded'
            ELSE 'Review'
        END AS work_state
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
    issue,
    work_state,
    s1_exempt,
    is_degraded,
    is_stale,
    cross_client_conflict,
    finding_signature,
    evaluated_at
FROM classified
WHERE NOT ignored
  AND NOT is_unknown
  AND (
      cardinality(action_missing_platforms) > 0
      OR cardinality(action_stale_platforms) > 0
      OR is_degraded
      OR cross_client_conflict
  )
ORDER BY
    CASE work_state
        WHEN 'Fix now' THEN 0
        WHEN 'Conflict' THEN 1
        WHEN 'Degraded' THEN 2
        WHEN 'Review' THEN 3
        WHEN 'Stale' THEN 4
        ELSE 5
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
        WHEN is_unknown THEN 'Unknown'
        WHEN cross_client_conflict THEN 'Conflict'
        WHEN cardinality(action_missing_platforms) > 0
             AND cardinality(online_platforms) > 0 THEN 'Fix now'
        WHEN cardinality(action_missing_platforms) > 0 THEN 'Review'
        WHEN cardinality(action_stale_platforms) > 0 THEN 'Stale'
        WHEN is_degraded THEN 'Degraded'
        WHEN is_compliant THEN 'Good'
        ELSE 'Review'
    END AS state,
    CASE
        WHEN cardinality(action_missing_platforms) > 0 THEN 'Missing ' || array_to_string(action_missing_platforms, ', ')
        WHEN cardinality(action_stale_platforms) > 0 THEN 'Stale ' || array_to_string(action_stale_platforms, ', ')
        WHEN cardinality(source_failed_platforms) > 0 THEN 'Data unavailable from ' || array_to_string(source_failed_platforms, ', ')
        WHEN is_degraded THEN 'Agent looks degraded'
        WHEN ignored THEN 'Ignored'
        ELSE 'No current issue'
    END AS issue,
    s1_exempt,
    ignored,
    evaluated_at
FROM base
ORDER BY client_name, hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_device_gap_summary AS
SELECT
    missing_platform,
    online_platform,
    COUNT(DISTINCT (client_id, norm_name)) AS devices
FROM ninja_agent_compliance.v_device_work_queue q
CROSS JOIN LATERAL unnest(q.missing_platforms) AS missing_platform
CROSS JOIN LATERAL unnest(q.online_platforms) AS online_platform
WHERE online_platform <> missing_platform
GROUP BY missing_platform, online_platform
ORDER BY devices DESC, missing_platform, online_platform;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_notification_queue AS
WITH active AS (
    SELECT f.*
    FROM ninja_agent_compliance.v_active_findings f
),
evaluated AS (
    SELECT
        a.*,
        r.rule_id,
        r.rule_key,
        r.cooldown_hours,
        nr.route_id,
        nr.display_name AS route_name,
        nr.enabled AS route_enabled,
        s.status AS alert_state,
        s.last_alerted_at,
        s.repeat_count,
        CASE
            WHEN a.finding_type = 'missing_required_platform'
                THEN COALESCE(a.affected_platform, 'Required platform') || ' missing'
            WHEN a.finding_type = 'stale_required_platform'
                THEN COALESCE(a.affected_platform, 'Required platform') || ' stale'
            WHEN a.finding_type = 'source_failure'
                THEN 'Collector failed'
            WHEN a.finding_type = 'cross_client_conflict'
                THEN 'Device appears under more than one customer'
            ELSE a.finding_type
        END AS issue,
        CASE
            WHEN r.rule_id IS NULL THEN 'No enabled alert rule for this customer and issue'
            WHEN nr.route_id IS NULL THEN 'No notification route selected'
            WHEN nr.enabled IS NOT TRUE THEN 'Notification route is off'
            WHEN s.finding_signature IS NULL OR s.status = 'resolved' THEN 'Ready: new issue'
            WHEN s.last_alerted_at IS NULL THEN 'Ready: never notified'
            WHEN now() - s.last_alerted_at >= (r.cooldown_hours * INTERVAL '1 hour') THEN 'Ready: repeat due'
            ELSE 'Waiting: repeat limit has not passed'
        END AS notification_status,
        CASE
            WHEN r.rule_id IS NULL THEN false
            WHEN nr.enabled IS NOT TRUE THEN false
            WHEN s.finding_signature IS NULL OR s.status = 'resolved' THEN true
            WHEN s.last_alerted_at IS NULL THEN true
            WHEN now() - s.last_alerted_at >= (r.cooldown_hours * INTERVAL '1 hour') THEN true
            ELSE false
        END AS ready_to_notify
    FROM active a
    LEFT JOIN LATERAL (
        SELECT r.rule_id, r.rule_key, r.cooldown_hours, r.route_id
        FROM ninja_agent_compliance.alert_rules r
        WHERE r.enabled
          AND r.finding_type = a.finding_type
          AND (r.affected_platform IS NULL OR r.affected_platform = a.affected_platform)
          AND (r.client_id IS NULL OR r.client_id = a.client_id)
          AND (r.device_scope IS NULL OR r.device_scope IN ('all', a.device_type))
        ORDER BY r.client_id NULLS LAST, r.affected_platform NULLS LAST, r.device_scope NULLS LAST
        LIMIT 1
    ) r ON true
    LEFT JOIN ninja_agent_compliance.notification_routes nr ON nr.route_id = r.route_id
    LEFT JOIN ninja_agent_compliance.alert_state s ON s.finding_signature = a.finding_signature
)
SELECT *
FROM evaluated
ORDER BY
    CASE WHEN ready_to_notify THEN 0 ELSE 1 END,
    CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
    client_name,
    hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_notifications_ready AS
SELECT *
FROM ninja_agent_compliance.v_notification_queue
WHERE ready_to_notify
ORDER BY
    CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
    client_name,
    hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_customer_name_queue AS
WITH latest_runs AS (
    SELECT DISTINCT ON (platform, source_id)
        platform,
        source_id,
        source_run_id
    FROM ninja_agent_compliance.platform_observations
    ORDER BY platform, source_id, observed_at DESC
),
latest_counts AS (
    SELECT
        po.platform,
        lower(trim(po.platform_group_name)) AS norm_name,
        COUNT(*) AS current_devices
    FROM ninja_agent_compliance.platform_observations po
    JOIN latest_runs lr ON lr.source_run_id = po.source_run_id
    WHERE COALESCE(NULLIF(po.platform_group_name, ''), '') <> ''
    GROUP BY po.platform, lower(trim(po.platform_group_name))
),
suggestions AS (
    SELECT DISTINCT ON (c.candidate_id)
        c.candidate_id,
        t.client_name AS suggested_customer
    FROM ninja_agent_compliance.v_org_candidates_current c
    JOIN ninja_agent_compliance.clients t
      ON t.enabled
     AND t.source NOT IN ('alignment', 'demoted')
     AND lower(trim(t.client_name)) NOT IN ('default site', 'unknown', 'various', '.default')
    WHERE lower(regexp_replace(c.candidate_name, '[[:space:]_.-]', '', 'g'))
              <> lower(regexp_replace(t.client_name, '[[:space:]_.-]', '', 'g'))
      AND (
          lower(regexp_replace(c.candidate_name, '[[:space:]_.-]', '', 'g'))
              LIKE lower(regexp_replace(t.client_name, '[[:space:]_.-]', '', 'g')) || '%'
          OR lower(regexp_replace(t.client_name, '[[:space:]_.-]', '', 'g'))
              LIKE lower(regexp_replace(c.candidate_name, '[[:space:]_.-]', '', 'g')) || '%'
      )
    ORDER BY
        c.candidate_id,
        ABS(length(t.client_name) - length(c.candidate_name)),
        t.client_name
)
SELECT
    c.candidate_id,
    c.candidate_name,
    c.platform,
    COALESCE(l.current_devices, 0) AS current_devices,
    COALESCE(NULLIF(c.suggested_target, ''), s.suggested_customer, '') AS suggested_customer,
    c.last_seen_at,
    CASE
        WHEN COALESCE(NULLIF(c.suggested_target, ''), s.suggested_customer, '') <> ''
            THEN 'Similar customer name found'
        ELSE 'No automatic match'
    END AS review_reason
FROM ninja_agent_compliance.v_org_candidates_current c
LEFT JOIN latest_counts l
  ON l.platform = c.platform
 AND l.norm_name = lower(trim(c.candidate_name))
LEFT JOIN suggestions s ON s.candidate_id = c.candidate_id
ORDER BY c.last_seen_at DESC, c.candidate_name;

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
    COALESCE(max_age_days, 30) AS max_age_days,
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

CREATE OR REPLACE VIEW ninja_agent_compliance.v_customer_alert_setup AS
WITH alert_types(alert_key, finding_type, affected_platform, alert_name) AS (
    VALUES
        ('missing_ninja', 'missing_required_platform', 'Ninja', 'Ninja missing'),
        ('missing_sentinelone', 'missing_required_platform', 'SentinelOne', 'SentinelOne missing'),
        ('missing_logmein', 'missing_required_platform', 'LogMeIn', 'LogMeIn missing'),
        ('missing_screenconnect', 'missing_required_platform', 'ScreenConnect', 'ScreenConnect missing'),
        ('stale', 'stale_required_platform', NULL, 'Required platform stale')
)
SELECT
    c.client_id,
    c.client_name,
    a.alert_key,
    a.alert_name,
    CASE WHEN cr.enabled THEN 'On' WHEN cr.rule_id IS NOT NULL THEN 'Off' ELSE 'Off' END AS customer_alert,
    CASE WHEN cr.enabled THEN true ELSE false END AS enabled_for_customer,
    COALESCE(nr.display_name, 'No route') AS route_name,
    CASE WHEN nr.enabled THEN 'On' WHEN nr.enabled IS FALSE THEN 'Off' ELSE 'No route' END AS route_state
FROM ninja_agent_compliance.clients c
CROSS JOIN alert_types a
LEFT JOIN ninja_agent_compliance.alert_rules cr
       ON cr.client_id = c.client_id
      AND cr.finding_type = a.finding_type
      AND cr.affected_platform IS NOT DISTINCT FROM a.affected_platform
LEFT JOIN ninja_agent_compliance.notification_routes nr ON nr.route_id = cr.route_id
WHERE c.enabled
  AND c.source NOT IN ('alignment', 'demoted')
ORDER BY c.client_name, a.alert_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_alert_rules_human AS
SELECT
    r.rule_key,
    CASE
        WHEN r.finding_type = 'missing_required_platform'
            THEN COALESCE(r.affected_platform, 'Required platform') || ' missing'
        WHEN r.finding_type = 'stale_required_platform'
            THEN COALESCE(r.affected_platform, 'Required platform') || ' stale'
        WHEN r.finding_type = 'source_failure'
            THEN 'Collector failed'
        WHEN r.finding_type = 'cross_client_conflict'
            THEN 'Device appears under more than one customer'
        ELSE r.finding_type
    END AS alert_name,
    COALESCE(c.client_name, 'All customers') AS customer_name,
    COALESCE(r.device_scope, 'any device') AS applies_to,
    r.severity,
    COALESCE(nr.display_name, 'No route') AS route_name,
    CASE WHEN nr.enabled THEN 'On' WHEN nr.enabled IS FALSE THEN 'Off' ELSE 'No route' END AS route_state,
    r.cooldown_hours,
    CASE WHEN r.enabled THEN 'On' ELSE 'Off' END AS rule_state,
    r.enabled
FROM ninja_agent_compliance.alert_rules r
LEFT JOIN ninja_agent_compliance.clients c ON c.client_id = r.client_id
LEFT JOIN ninja_agent_compliance.notification_routes nr ON nr.route_id = r.route_id
ORDER BY
    CASE WHEN r.enabled THEN 0 ELSE 1 END,
    CASE r.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
    alert_name,
    customer_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_notification_routes_human AS
SELECT
    route_key,
    display_name,
    route_type,
    CASE WHEN enabled THEN 'On' ELSE 'Off' END AS state,
    COALESCE(NULLIF(target_ref, ''), 'Not configured') AS setting,
    TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI') AS updated
FROM ninja_agent_compliance.notification_routes
ORDER BY route_type, display_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_system_health_queue AS
SELECT
    work_type,
    severity,
    platform,
    source_name,
    COALESCE(NULLIF(client_name, ''), 'Shared') AS customer_name,
    rows_observed,
    issue
FROM ninja_agent_compliance.v_source_work_current
UNION ALL
SELECT
    'Delivery failed'::text AS work_type,
    80::integer AS severity,
    'Alerts'::text AS platform,
    COALESCE(nr.display_name, 'Unknown route') AS source_name,
    COALESCE(f.client_name, 'Shared') AS customer_name,
    0::integer AS rows_observed,
    COALESCE(NULLIF(ae.response_preview, ''), ae.status) AS issue
FROM ninja_agent_compliance.alert_events ae
LEFT JOIN ninja_agent_compliance.notification_routes nr ON nr.route_id = ae.route_id
LEFT JOIN ninja_agent_compliance.compliance_findings f ON f.finding_id = ae.finding_id
WHERE ae.attempted_at > now() - INTERVAL '7 days'
  AND ae.status NOT IN ('sent', 'skipped_no_route')
ORDER BY severity DESC, platform, source_name, customer_name;
