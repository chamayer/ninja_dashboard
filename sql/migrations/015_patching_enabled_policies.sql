-- =============================================================================
-- 015_patching_enabled_policies.sql
-- Persist policy allowlist used to mark server patching as enabled.
-- Rebuilds v_active_devices so patching_scope can honor the allowlist plus
-- device-level patchingEnabled overrides.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ninja_core.patching_enabled_policies (
    policy_name text PRIMARY KEY
);

INSERT INTO ninja_core.patching_enabled_policies (policy_name)
SELECT DISTINCT policy_name
FROM ninja_core.patching_enabled_policies
ON CONFLICT (policy_name) DO NOTHING;

DROP MATERIALIZED VIEW IF EXISTS ninja_core.device_troubleshooting_signal;
DROP MATERIALIZED VIEW IF EXISTS ninja_core.v_active_devices;

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
          'patchingEnabled',
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
        bool_or(value_bool) FILTER (WHERE field_name = 'patchingEnabled') AS device_patching_enabled,
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
    COALESCE(dcf.device_patching_enabled, FALSE) AS patching_enabled,
    CASE
        WHEN COALESCE(
            dcf.device_patching_disabled,
            ocf.org_patching_disabled,
            lcf.location_patching_disabled,
            FALSE
        ) THEN TRUE
        WHEN COALESCE(dcf.device_patching_enabled, FALSE) THEN FALSE
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
        WHEN COALESCE(dcf.device_patching_enabled, FALSE) THEN 'Included'
        WHEN d.node_class = 'WINDOWS_SERVER'
            AND EXISTS (
                SELECT 1
                FROM ninja_core.patching_enabled_policies pep
                WHERE pep.policy_name = COALESCE(
                    (SELECT p.name FROM ninja_core.policies p WHERE p.id = d.policy_id),
                    (SELECT p.name FROM ninja_core.policies p WHERE p.id = d.role_policy_id)
                )
            ) THEN 'Included'
        WHEN d.node_class = 'WINDOWS_SERVER' THEN 'Excluded'
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
WHERE d.is_current = TRUE
  AND d.approval_status = 'APPROVED'
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

CREATE MATERIALIZED VIEW ninja_core.device_troubleshooting_signal AS
WITH patch_state_rollup AS (
    SELECT
        device_id,
        COUNT(*) FILTER (WHERE status = 'APPROVED') AS approved_patches,
        COUNT(*) FILTER (WHERE status = 'MANUAL') AS manual_patches,
        COUNT(*) FILTER (WHERE status = 'DELAYED') AS delayed_patches,
        COUNT(*) FILTER (
            WHERE status IN ('MISSING', 'FAILED', 'PENDING', 'APPROVED', 'MANUAL', 'DELAYED')
        ) AS missing_patches,
        MAX(last_observed_at) AS last_patch_state_seen
    FROM ninja_patches.current_patch_state
    GROUP BY device_id
),
install_rollup AS (
    SELECT
        device_id,
        COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_installs,
        MAX(installed_at) FILTER (WHERE status = 'FAILED') AS last_failed_install,
        MAX(installed_at) AS last_install_attempt
    FROM ninja_patches.latest_install_outcome
    GROUP BY device_id
)
SELECT
    d.id AS device_id,
    d.system_name,
    d.display_name,
    d.organization_id,
    o.name AS organization,
    d.location_id,
    d.node_class,
    d.os_name,
    d.approval_status,
    d.patching_scope,
    d.patching_disabled,
    d.patching_notes,
    COALESCE(role_policy.name, assigned_policy.name, '(none)') AS assigned_policy,
    dps.last_seen_at,
    CASE
        WHEN dps.last_seen_at IS NULL THEN 'no_patch_data'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' THEN 'stale_patch_data'
        ELSE 'active_patching'
    END AS patch_status,
    d.last_contact,
    d.offline,
    d.needs_reboot,
    COALESCE(psr.approved_patches, 0) AS approved_patches,
    COALESCE(psr.manual_patches, 0) AS manual_patches,
    COALESCE(psr.delayed_patches, 0) AS delayed_patches,
    COALESCE(psr.missing_patches, 0) AS missing_patches,
    COALESCE(psr.approved_patches, 0)
        + COALESCE(psr.manual_patches, 0)
        + COALESCE(psr.delayed_patches, 0) AS waiting_patches,
    psr.last_patch_state_seen,
    COALESCE(ir.failed_installs, 0) AS failed_installs,
    ir.last_failed_install,
    ir.last_install_attempt,
    ar.last_activity_event,
    ar.last_patch_started,
    ar.last_patch_completed,
    ar.last_patch_failure,
    ar.last_reboot,
    COALESCE(ar.patch_started_events, 0) AS patch_started_events,
    COALESCE(ar.patch_completed_events, 0) AS patch_completed_events,
    COALESCE(ar.patch_failure_events, 0) AS patch_failure_events,
    ar.last_failure_message,
    ldh.health_status,
    ldh.pending_reboot_reason,
    COALESCE(ldh.pending_os_patches_count, 0) AS ninja_pending_os_patches,
    COALESCE(ldh.failed_os_patches_count, 0) AS ninja_failed_os_patches,
    COALESCE(ldh.pending_software_patches_count, 0) AS ninja_pending_software_patches,
    COALESCE(ldh.failed_software_patches_count, 0) AS ninja_failed_software_patches,
    COALESCE(ldh.alert_count, 0) AS alert_count,
    COALESCE(ldh.active_job_count, 0) AS active_job_count,
    COALESCE(ldh.installation_issues_count, 0) AS installation_issues_count,
    COALESCE(ldh.critical_vulnerability_count, 0) AS critical_vulnerability_count,
    COALESCE(ldh.high_vulnerability_count, 0) AS high_vulnerability_count,
    COALESCE(ldh.medium_vulnerability_count, 0) AS medium_vulnerability_count,
    COALESCE(ldh.low_vulnerability_count, 0) AS low_vulnerability_count,
    ldh.products_installation_statuses,
    (
        ar.last_patch_started IS NOT NULL
        AND (
            ar.last_patch_completed IS NULL
            OR ar.last_patch_completed < ar.last_patch_started
        )
    ) AS started_without_completion,
    CASE
        WHEN d.patching_scope = 'Excluded' THEN 'Excluded'
        WHEN dps.last_seen_at IS NULL AND COALESCE(d.offline, FALSE) THEN 'Never patched and offline'
        WHEN dps.last_seen_at IS NULL THEN 'Never patched'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(d.offline, FALSE) THEN 'Stalled and offline'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days'
            AND ar.last_patch_started IS NOT NULL
            AND (
                ar.last_patch_completed IS NULL
                OR ar.last_patch_completed < ar.last_patch_started
            ) THEN 'Stalled after patch start'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(ar.patch_failure_events, 0) > 0 THEN 'Stalled with activity failures'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(ir.failed_installs, 0) > 0 THEN 'Stalled with failures'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(d.needs_reboot, FALSE) THEN 'Stalled with reboot pending'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(psr.manual_patches, 0) > 0 THEN 'Stalled with manual approvals'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(psr.delayed_patches, 0) > 0 THEN 'Stalled with delayed patches'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(psr.approved_patches, 0) > 0 THEN 'Stalled with approved waiting'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' THEN 'Stalled'
        WHEN COALESCE(ir.failed_installs, 0) > 0 THEN 'Active with failures'
        WHEN COALESCE(d.needs_reboot, FALSE) THEN 'Reboot pending'
        WHEN COALESCE(psr.manual_patches, 0) > 0 THEN 'Manual approvals'
        ELSE 'Review'
    END AS issue_type,
    CASE
        WHEN d.patching_scope = 'Excluded' THEN 'Validate exclusion and notes'
        WHEN dps.last_seen_at IS NULL AND COALESCE(d.offline, FALSE) THEN 'Bring online; verify Ninja agent and patch policy'
        WHEN dps.last_seen_at IS NULL THEN 'Verify policy assignment, agent health, and OS patch inventory'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(d.offline, FALSE) THEN 'Bring online; confirm agent check-in'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days'
            AND ar.last_patch_started IS NOT NULL
            AND (
                ar.last_patch_completed IS NULL
                OR ar.last_patch_completed < ar.last_patch_started
            ) THEN 'Review activity feed: patch started but no later completion'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(ar.patch_failure_events, 0) > 0 THEN 'Review patch-management failure activity'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(ir.failed_installs, 0) > 0 THEN 'Review failed install results'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(d.needs_reboot, FALSE) THEN 'Reboot or confirm reboot policy'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(psr.manual_patches, 0) > 0 THEN 'Review manual approvals'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(psr.delayed_patches, 0) > 0 THEN 'Review delay policy/window'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' AND COALESCE(psr.approved_patches, 0) > 0 THEN 'Check why approved patches are not installing'
        WHEN dps.last_seen_at < NOW() - INTERVAL '35 days' THEN 'Check schedule, agent health, maintenance window, and policy'
        WHEN COALESCE(ir.failed_installs, 0) > 0 THEN 'Review failed install results'
        WHEN COALESCE(d.needs_reboot, FALSE) THEN 'Reboot or confirm reboot policy'
        WHEN COALESCE(psr.manual_patches, 0) > 0 THEN 'Review manual approvals'
        ELSE 'Open device drilldown'
    END AS suggested_action
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
LEFT JOIN ninja_patches.device_patch_signal dps ON dps.device_id = d.id
LEFT JOIN patch_state_rollup psr ON psr.device_id = d.id
LEFT JOIN install_rollup ir ON ir.device_id = d.id
LEFT JOIN ninja_activities.device_activity_signal ar ON ar.device_id = d.id
LEFT JOIN ninja_core.latest_device_health ldh ON ldh.device_id = d.id
LEFT JOIN ninja_core.policies assigned_policy ON assigned_policy.id = d.policy_id
LEFT JOIN ninja_core.policies role_policy ON role_policy.id = d.role_policy_id;

CREATE UNIQUE INDEX device_troubleshooting_signal_device_idx
    ON ninja_core.device_troubleshooting_signal (device_id);
CREATE INDEX device_troubleshooting_signal_scope_idx
    ON ninja_core.device_troubleshooting_signal (patching_scope);
CREATE INDEX device_troubleshooting_signal_org_idx
    ON ninja_core.device_troubleshooting_signal (organization_id);
CREATE INDEX device_troubleshooting_signal_policy_idx
    ON ninja_core.device_troubleshooting_signal (assigned_policy);
CREATE INDEX device_troubleshooting_signal_status_idx
    ON ninja_core.device_troubleshooting_signal (patch_status);
CREATE INDEX device_troubleshooting_signal_issue_idx
    ON ninja_core.device_troubleshooting_signal (issue_type);
CREATE INDEX device_troubleshooting_signal_health_idx
    ON ninja_core.device_troubleshooting_signal (health_status);
CREATE INDEX device_troubleshooting_signal_last_seen_idx
    ON ninja_core.device_troubleshooting_signal (last_seen_at DESC);
