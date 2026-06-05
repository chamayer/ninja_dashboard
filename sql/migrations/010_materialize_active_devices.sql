-- =============================================================================
-- 010_materialize_active_devices.sql
-- Converts ninja_core.v_active_devices from a live view into a materialized
-- view. Dashboard scope/org/device filters now hit stored, indexed columns
-- instead of recomputing custom-field inheritance once per card.
-- =============================================================================

DROP VIEW IF EXISTS ninja_core.v_active_devices;

CREATE MATERIALIZED VIEW ninja_core.v_active_devices AS
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
),
device_fields AS (
    SELECT DISTINCT ON (entity_id, field_name)
        entity_id,
        field_name,
        value_bool,
        value_text
    FROM ninja_core.custom_field_values
    WHERE entity_type = 'DEVICE'
      AND field_name IN (
          'patchingDisabled',
          'serverPatchingDisabled',
          'workstationPatchingDisabled',
          'patchingNotes'
      )
    ORDER BY entity_id, field_name, last_observed_at DESC, first_observed_at DESC
),
organization_fields AS (
    SELECT DISTINCT ON (entity_id, field_name)
        entity_id,
        field_name,
        value_bool,
        value_text
    FROM ninja_core.custom_field_values
    WHERE entity_type = 'ORGANIZATION'
      AND field_name IN (
          'patchingDisabled',
          'serverPatchingDisabled',
          'workstationPatchingDisabled',
          'patchingNotes'
      )
    ORDER BY entity_id, field_name, last_observed_at DESC, first_observed_at DESC
),
location_fields AS (
    SELECT DISTINCT ON (entity_id, field_name)
        entity_id,
        field_name,
        value_bool,
        value_text
    FROM ninja_core.custom_field_values
    WHERE entity_type = 'LOCATION'
      AND field_name IN (
          'patchingDisabled',
          'serverPatchingDisabled',
          'workstationPatchingDisabled',
          'patchingNotes'
      )
    ORDER BY entity_id, field_name, last_observed_at DESC, first_observed_at DESC
),
device_cf AS (
    SELECT
        entity_id AS device_id,
        bool_or(value_bool) FILTER (WHERE field_name = 'patchingDisabled') AS device_patching_disabled,
        bool_or(value_bool) FILTER (WHERE field_name = 'serverPatchingDisabled') AS device_server_patching_disabled,
        bool_or(value_bool) FILTER (WHERE field_name = 'workstationPatchingDisabled') AS device_workstation_patching_disabled,
        MAX(value_text) FILTER (WHERE field_name = 'patchingNotes') AS device_patching_notes
    FROM device_fields
    GROUP BY entity_id
),
organization_cf AS (
    SELECT
        entity_id AS organization_id,
        bool_or(value_bool) FILTER (WHERE field_name = 'patchingDisabled') AS org_patching_disabled,
        bool_or(value_bool) FILTER (WHERE field_name = 'serverPatchingDisabled') AS org_server_patching_disabled,
        bool_or(value_bool) FILTER (WHERE field_name = 'workstationPatchingDisabled') AS org_workstation_patching_disabled,
        MAX(value_text) FILTER (WHERE field_name = 'patchingNotes') AS org_patching_notes
    FROM organization_fields
    GROUP BY entity_id
),
location_cf AS (
    SELECT
        entity_id AS location_id,
        bool_or(value_bool) FILTER (WHERE field_name = 'patchingDisabled') AS location_patching_disabled,
        bool_or(value_bool) FILTER (WHERE field_name = 'serverPatchingDisabled') AS location_server_patching_disabled,
        bool_or(value_bool) FILTER (WHERE field_name = 'workstationPatchingDisabled') AS location_workstation_patching_disabled,
        MAX(value_text) FILTER (WHERE field_name = 'patchingNotes') AS location_patching_notes
    FROM location_fields
    GROUP BY entity_id
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
    ls.maintenance_end,
    CASE
        WHEN COALESCE(
            dcf.device_patching_disabled,
            ocf.org_patching_disabled,
            lcf.location_patching_disabled,
            FALSE
        ) THEN TRUE
        WHEN d.node_class = 'WINDOWS_SERVER'
            AND COALESCE(
                dcf.device_server_patching_disabled,
                ocf.org_server_patching_disabled,
                lcf.location_server_patching_disabled,
                FALSE
            ) THEN TRUE
        WHEN d.node_class = 'WINDOWS_WORKSTATION'
            AND COALESCE(
                dcf.device_workstation_patching_disabled,
                ocf.org_workstation_patching_disabled,
                lcf.location_workstation_patching_disabled,
                FALSE
            ) THEN TRUE
        ELSE FALSE
    END AS patching_disabled,
    CASE
        WHEN COALESCE(
            dcf.device_patching_disabled,
            ocf.org_patching_disabled,
            lcf.location_patching_disabled,
            FALSE
        ) THEN 'Excluded'
        WHEN d.node_class = 'WINDOWS_SERVER'
            AND COALESCE(
                dcf.device_server_patching_disabled,
                ocf.org_server_patching_disabled,
                lcf.location_server_patching_disabled,
                FALSE
            ) THEN 'Excluded'
        WHEN d.node_class = 'WINDOWS_WORKSTATION'
            AND COALESCE(
                dcf.device_workstation_patching_disabled,
                ocf.org_workstation_patching_disabled,
                lcf.location_workstation_patching_disabled,
                FALSE
            ) THEN 'Excluded'
        ELSE 'Included'
    END AS patching_scope,
    COALESCE(
        NULLIF(dcf.device_patching_notes, ''),
        NULLIF(ocf.org_patching_notes, ''),
        NULLIF(lcf.location_patching_notes, '')
    ) AS patching_notes
FROM ninja_core.devices d
INNER JOIN latest_snap ls ON ls.device_id = d.id
LEFT JOIN device_cf dcf ON dcf.device_id = d.id
LEFT JOIN organization_cf ocf ON ocf.organization_id = d.organization_id
LEFT JOIN location_cf lcf ON lcf.location_id = d.location_id
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND ls.last_contact > NOW() - INTERVAL '30 days';

CREATE UNIQUE INDEX v_active_devices_id_idx
    ON ninja_core.v_active_devices (id);
CREATE INDEX v_active_devices_scope_idx
    ON ninja_core.v_active_devices (patching_scope);
CREATE INDEX v_active_devices_scope_org_idx
    ON ninja_core.v_active_devices (patching_scope, organization_id);
CREATE INDEX v_active_devices_org_idx
    ON ninja_core.v_active_devices (organization_id);
CREATE INDEX v_active_devices_location_idx
    ON ninja_core.v_active_devices (location_id);
CREATE INDEX v_active_devices_class_idx
    ON ninja_core.v_active_devices (node_class);
CREATE INDEX v_active_devices_system_name_idx
    ON ninja_core.v_active_devices (system_name);
CREATE INDEX v_active_devices_last_contact_idx
    ON ninja_core.v_active_devices (last_contact DESC);
