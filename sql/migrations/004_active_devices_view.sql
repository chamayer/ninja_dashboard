-- =============================================================================
-- 004_active_devices_view.sql
-- Defines the "active device" view used by Overview / Detail / Drilldown
-- dashboards. Patch Coverage intentionally bypasses this view because
-- its purpose is to surface devices that AREN'T being managed (including
-- ones that haven't checked in for a long time).
--
-- "Active" = approved AND last contact within 30 days. The view exposes
-- the latest device_snapshots fields inline so downstream queries don't
-- need to re-join the snapshots table.
-- =============================================================================

CREATE OR REPLACE VIEW ninja_core.v_active_devices AS
WITH latest_snap AS (
    SELECT DISTINCT ON (device_id)
        device_id,
        snapshot_at,
        last_contact,
        last_boot,
        needs_reboot,
        needs_reboot_reasons,
        offline,
        last_user,
        maintenance_status,
        maintenance_start,
        maintenance_end
    FROM ninja_core.device_snapshots
    ORDER BY device_id, snapshot_at DESC
)
SELECT
    d.*,
    ls.snapshot_at         AS last_snapshot_at,
    ls.last_contact,
    ls.last_boot,
    ls.needs_reboot,
    ls.needs_reboot_reasons,
    ls.offline,
    ls.last_user,
    ls.maintenance_status,
    ls.maintenance_start,
    ls.maintenance_end
FROM ninja_core.devices d
INNER JOIN latest_snap ls ON ls.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND ls.last_contact > NOW() - INTERVAL '30 days';
