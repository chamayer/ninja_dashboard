-- Alerting is first-success only.
--
-- Collection and evaluation create the current issue snapshot. Alerting
-- runs after evaluation and sends only when an active issue has no prior
-- successful delivery for the same finding_signature. Failed deliveries
-- remain retryable on later evaluations.

DROP VIEW IF EXISTS ninja_agent_compliance.v_notifications_ready;

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
