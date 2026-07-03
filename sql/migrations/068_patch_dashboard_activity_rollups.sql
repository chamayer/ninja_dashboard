-- Reporting rollups for first-load patch dashboards. These keep broad
-- trend/category cards off the raw activity event table.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP MATERIALIZED VIEW IF EXISTS ninja_activities.system_reboot_events_recent;
DROP MATERIALIZED VIEW IF EXISTS ninja_activities.patch_warning_events_recent;

CREATE MATERIALIZED VIEW ninja_activities.patch_warning_events_recent AS
SELECT
    a.id AS activity_id,
    a.device_id,
    a.activity_time,
    DATE_TRUNC('day', a.activity_time)::date AS activity_day,
    a.message,
    CASE
        WHEN a.message ILIKE '%outstanding approved patches%' THEN 'Outstanding approved patches'
        WHEN a.message ILIKE '%was skipped because%' THEN 'Scheduled job skipped'
        WHEN a.message ILIKE '%metered connection%' THEN 'Metered connection'
        WHEN a.message ILIKE '%post reboot scan%' THEN 'Post-reboot scan required'
        WHEN a.message ILIKE '%download error%' OR a.message ILIKE '%download failed%' THEN 'OS patch download error'
        WHEN a.message ILIKE '%requires a reboot%' OR a.message ILIKE '%needs to be rebooted%' THEN 'Reboot needed'
        WHEN a.message ILIKE '%Windows Update Agent%out of date%' THEN 'WUA out of date'
        WHEN a.message ILIKE '%reboot%scheduled%' THEN 'Reboot scheduling'
        WHEN a.message ILIKE '%download is complete%' THEN 'Download complete'
        ELSE 'Other'
    END AS warning_category
FROM ninja_activities.activities a
WHERE a.device_id IS NOT NULL
  AND a.activity_type IN ('PATCH_MANAGEMENT_MESSAGE', 'SOFTWARE_PATCH_MANAGEMENT_MESSAGE')
  AND a.activity_time >= NOW() - INTERVAL '180 days';

CREATE UNIQUE INDEX patch_warning_events_recent_activity_idx
ON ninja_activities.patch_warning_events_recent (activity_id);

CREATE INDEX patch_warning_events_recent_day_device_idx
ON ninja_activities.patch_warning_events_recent (activity_day DESC, device_id);

CREATE INDEX patch_warning_events_recent_category_day_idx
ON ninja_activities.patch_warning_events_recent (warning_category, activity_day DESC);

CREATE INDEX patch_warning_events_recent_message_trgm_idx
ON ninja_activities.patch_warning_events_recent
USING gin (message gin_trgm_ops)
WHERE message IS NOT NULL;

CREATE MATERIALIZED VIEW ninja_activities.system_reboot_events_recent AS
SELECT
    DATE_TRUNC('day', a.activity_time)::date AS activity_day,
    a.device_id,
    COUNT(*) AS reboot_events
FROM ninja_activities.activities a
WHERE a.device_id IS NOT NULL
  AND a.activity_type = 'SYSTEM_REBOOTED'
  AND a.activity_time >= NOW() - INTERVAL '180 days'
GROUP BY 1, 2;

CREATE UNIQUE INDEX system_reboot_events_recent_day_device_idx
ON ninja_activities.system_reboot_events_recent (activity_day, device_id);

CREATE INDEX system_reboot_events_recent_device_day_idx
ON ninja_activities.system_reboot_events_recent (device_id, activity_day DESC);
