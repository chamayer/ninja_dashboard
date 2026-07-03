-- Speed up the v0.35 patch dashboards' broad trend and activity cards.
-- These indexes match the live operator filters: recent installs,
-- recent patch-warning messages, and recent reboot activity.

CREATE INDEX IF NOT EXISTS latest_install_outcome_status_installed_at_idx
ON ninja_patches.latest_install_outcome (status, installed_at DESC, device_id)
WHERE installed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS activities_patch_message_time_device_idx
ON ninja_activities.activities (activity_time DESC, device_id)
WHERE activity_type IN ('PATCH_MANAGEMENT_MESSAGE', 'SOFTWARE_PATCH_MANAGEMENT_MESSAGE');

CREATE INDEX IF NOT EXISTS activities_system_reboot_time_device_idx
ON ninja_activities.activities (activity_time DESC, device_id)
WHERE activity_type = 'SYSTEM_REBOOTED';
