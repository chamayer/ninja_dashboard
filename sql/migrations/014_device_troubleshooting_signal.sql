-- =============================================================================
-- 014_device_troubleshooting_signal.sql
-- One-row-per-device troubleshooting rollup for Issues / Device Status.
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS ninja_core.device_troubleshooting_signal;

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
