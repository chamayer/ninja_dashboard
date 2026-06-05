-- =============================================================================
-- 013_device_health.sql
-- Device health summary from /v2/queries/device-health.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ninja_core.device_health_snapshots (
    snapshot_at                      timestamptz NOT NULL,
    device_id                        integer NOT NULL REFERENCES ninja_core.devices(id),
    pending_reboot_reason            text,
    failed_os_patches_count          integer,
    pending_os_patches_count         integer,
    failed_software_patches_count    integer,
    pending_software_patches_count   integer,
    alert_count                      integer,
    active_job_count                 integer,
    health_status                    text,
    active_threats_count             integer,
    quarantined_threats_count        integer,
    blocked_threats_count            integer,
    critical_vulnerability_count     integer,
    high_vulnerability_count         integer,
    medium_vulnerability_count       integer,
    low_vulnerability_count          integer,
    installation_issues_count        integer,
    offline                          boolean,
    parent_offline                   boolean,
    products_installation_statuses   jsonb,
    data                             jsonb NOT NULL,
    PRIMARY KEY (snapshot_at, device_id)
);

CREATE INDEX IF NOT EXISTS device_health_snapshots_device_time_idx
    ON ninja_core.device_health_snapshots (device_id, snapshot_at DESC);

CREATE MATERIALIZED VIEW IF NOT EXISTS ninja_core.latest_device_health AS
SELECT DISTINCT ON (device_id)
    snapshot_at,
    device_id,
    pending_reboot_reason,
    failed_os_patches_count,
    pending_os_patches_count,
    failed_software_patches_count,
    pending_software_patches_count,
    alert_count,
    active_job_count,
    health_status,
    active_threats_count,
    quarantined_threats_count,
    blocked_threats_count,
    critical_vulnerability_count,
    high_vulnerability_count,
    medium_vulnerability_count,
    low_vulnerability_count,
    installation_issues_count,
    offline,
    parent_offline,
    products_installation_statuses,
    data
FROM ninja_core.device_health_snapshots
ORDER BY device_id, snapshot_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS latest_device_health_device_idx
    ON ninja_core.latest_device_health (device_id);
CREATE INDEX IF NOT EXISTS latest_device_health_status_idx
    ON ninja_core.latest_device_health (health_status);
CREATE INDEX IF NOT EXISTS latest_device_health_reboot_idx
    ON ninja_core.latest_device_health (pending_reboot_reason)
    WHERE pending_reboot_reason IS NOT NULL AND pending_reboot_reason <> '';
