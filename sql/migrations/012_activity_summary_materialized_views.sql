-- =============================================================================
-- 012_activity_summary_materialized_views.sql
-- Per-device activity-feed rollup for issue triage.
-- =============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_activities.device_activity_signal AS
SELECT
    device_id,
    MAX(activity_time) FILTER (
        WHERE activity_type IN (
            'PATCH_MANAGEMENT_APPLY_PATCH_STARTED',
            'PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED',
            'PATCH_MANAGEMENT_FAILURE',
            'PATCH_MANAGEMENT_ROLLBACK_PATCH_REQUESTED',
            'PATCH_MANAGEMENT_ROLLBACK_PATCH_STARTED',
            'PATCH_MANAGEMENT_ROLLBACK_PATCH_COMPLETED',
            'SYSTEM_REBOOTED'
        )
    ) AS last_activity_event,
    MAX(activity_time) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_APPLY_PATCH_STARTED'
    ) AS last_patch_started,
    MAX(activity_time) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED'
    ) AS last_patch_completed,
    MAX(activity_time) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_FAILURE'
    ) AS last_patch_failure,
    MAX(activity_time) FILTER (
        WHERE activity_type = 'SYSTEM_REBOOTED'
    ) AS last_reboot,
    COUNT(*) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_APPLY_PATCH_STARTED'
    ) AS patch_started_events,
    COUNT(*) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED'
    ) AS patch_completed_events,
    COUNT(*) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_FAILURE'
    ) AS patch_failure_events,
    MAX(message) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_FAILURE'
    ) AS last_failure_message
FROM ninja_activities.activities
WHERE device_id IS NOT NULL
GROUP BY device_id;

CREATE UNIQUE INDEX IF NOT EXISTS device_activity_signal_device_idx
    ON ninja_activities.device_activity_signal (device_id);
CREATE INDEX IF NOT EXISTS device_activity_signal_activity_idx
    ON ninja_activities.device_activity_signal (last_activity_event DESC);
CREATE INDEX IF NOT EXISTS device_activity_signal_failure_idx
    ON ninja_activities.device_activity_signal (last_patch_failure DESC)
    WHERE last_patch_failure IS NOT NULL;
