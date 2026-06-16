-- Align notification readiness with the human device state model.
--
-- Missing and Offline are alertable only when the finding is confirmed.
-- Review and fully Stale devices are not alertable. The Python sender has
-- always filtered on confirmed_gap; this makes Metabase show the same reality.
--
-- v_active_findings was defined in migration 035 with `SELECT f.*` from
-- compliance_findings. PostgreSQL fixes a view's column list at CREATE time,
-- so migration 045's `ALTER TABLE ... ADD COLUMN confirmed_gap` did not
-- propagate. CREATE OR REPLACE here re-expands `f.*` (new columns at the
-- end are permitted) so downstream views can reference confirmed_gap.

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

-- v_notification_queue must be dropped (not CREATE OR REPLACE'd) because
-- its column shape changes: SELECT a.* from v_active_findings now expands
-- to include confirmed_gap, which shifts rule_id and the rest one position
-- to the right. CREATE OR REPLACE only allows appending columns at the end.
DROP VIEW IF EXISTS ninja_agent_compliance.v_notifications_ready;
DROP VIEW IF EXISTS ninja_agent_compliance.v_notification_queue;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_notification_queue AS
WITH active AS (
    SELECT f.*
    FROM ninja_agent_compliance.v_active_findings f
    WHERE f.confirmed_gap
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
                THEN COALESCE(a.affected_platform, 'Required platform') || ' offline'
            WHEN a.finding_type = 'source_failure'
                THEN 'Collector failed'
            WHEN a.finding_type = 'cross_client_conflict'
                THEN 'Device appears under more than one customer'
            ELSE a.finding_type
        END AS issue,
        CASE
            WHEN r.rule_id IS NULL THEN 'No enabled notification rule for this customer and issue'
            WHEN nr.route_id IS NULL THEN 'No notification route selected'
            WHEN nr.enabled IS NOT TRUE THEN 'Notification route is off'
            WHEN sent.last_sent_at IS NOT NULL THEN 'Already notified'
            WHEN failed.last_failed_at IS NOT NULL THEN 'Will retry after next evaluation'
            ELSE 'Ready: first notification'
        END AS notification_status,
        CASE
            WHEN r.rule_id IS NULL THEN false
            WHEN nr.route_id IS NULL THEN false
            WHEN nr.enabled IS NOT TRUE THEN false
            WHEN sent.last_sent_at IS NOT NULL THEN false
            ELSE true
        END AS ready_to_notify,
        sent.last_sent_at,
        failed.last_failed_at
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
    LEFT JOIN LATERAL (
        SELECT MAX(ae.attempted_at) AS last_sent_at
        FROM ninja_agent_compliance.alert_events ae
        WHERE ae.finding_signature = a.finding_signature
          AND ae.status = 'sent'
    ) sent ON true
    LEFT JOIN LATERAL (
        SELECT MAX(ae.attempted_at) AS last_failed_at
        FROM ninja_agent_compliance.alert_events ae
        WHERE ae.finding_signature = a.finding_signature
          AND ae.status = 'failed'
    ) failed ON true
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

CREATE OR REPLACE VIEW ninja_agent_compliance.v_customer_alert_setup AS
WITH alert_types(alert_key, finding_type, affected_platform, alert_name) AS (
    VALUES
        ('missing_ninja', 'missing_required_platform', 'Ninja', 'Ninja missing'),
        ('missing_sentinelone', 'missing_required_platform', 'SentinelOne', 'SentinelOne missing'),
        ('missing_logmein', 'missing_required_platform', 'LogMeIn', 'LogMeIn missing'),
        ('missing_screenconnect', 'missing_required_platform', 'ScreenConnect', 'ScreenConnect missing'),
        ('offline', 'stale_required_platform', NULL, 'Required platform offline')
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
            THEN COALESCE(r.affected_platform, 'Required platform') || ' offline'
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
