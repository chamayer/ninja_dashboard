-- =============================================================================
-- 017_activity_warnings_and_scans.sql
-- Extend device_activity_signal with per-device rollups for OS patch
-- WARNINGS (MESSAGE codes) and SCAN events. Rebuilds the dependent
-- device_troubleshooting_signal so the new columns are surfaced on
-- Issues / Device Drilldown without needing per-card subqueries.
--
-- Dependency order: device_troubleshooting_signal (mig 015 + extended
-- in 016) reads from device_activity_signal, so drop dependent first.
-- =============================================================================

-- Fail fast if a query takes longer than 5 minutes, instead of hanging
-- until container restart timeout. Prior versions of this migration
-- used a correlated subquery that triggered an O(N²) plan over the
-- ~500k-row activities table; the statement_timeout keeps future
-- accidents diagnosable.
SET LOCAL statement_timeout = '5min';

DROP MATERIALIZED VIEW IF EXISTS ninja_core.device_troubleshooting_signal;
DROP MATERIALIZED VIEW IF EXISTS ninja_activities.device_activity_signal;

CREATE MATERIALIZED VIEW ninja_activities.device_activity_signal AS
SELECT
    device_id,
    -- Generic "last patch-related activity" timestamp; unchanged from
    -- migration 012 but extended to include warnings and scans.
    MAX(activity_time) FILTER (
        WHERE activity_type IN (
            'PATCH_MANAGEMENT_APPLY_PATCH_STARTED',
            'PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED',
            'PATCH_MANAGEMENT_FAILURE',
            'PATCH_MANAGEMENT_MESSAGE',
            'PATCH_MANAGEMENT_ROLLBACK_PATCH_REQUESTED',
            'PATCH_MANAGEMENT_ROLLBACK_PATCH_STARTED',
            'PATCH_MANAGEMENT_ROLLBACK_PATCH_COMPLETED',
            'PATCH_MANAGEMENT_SCAN_COMPLETED',
            'SOFTWARE_PATCH_MANAGEMENT_SCAN_STARTED',
            'SOFTWARE_PATCH_MANAGEMENT_MESSAGE',
            'SYSTEM_REBOOTED'
        )
    ) AS last_activity_event,
    -- Apply / install lifecycle (unchanged from mig 012).
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
    COUNT(*) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_FAILURE'
          AND activity_time >= NOW() - INTERVAL '30 days'
    ) AS patch_failure_events_30d,
    -- Plain MAX(message) FILTER — matches the migration 012 pattern
    -- (lexically max message rather than latest-by-time). Single-pass,
    -- no sort. ARRAY_AGG ORDER BY was tried and proved too slow at
    -- ~500k-row activities table volume.
    MAX(message) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_FAILURE'
    ) AS last_failure_message,
    -- Warning rollup (NEW). MESSAGE codes from both prefixes carry
    -- operationally critical signals ("outstanding approved patches",
    -- "post reboot scan required", "download error", "scheduled update
    -- skipped", etc.). See CONTEXT.md and ninja_dashboard memory for
    -- the prefix-doesn't-match-scope quirk.
    MAX(activity_time) FILTER (
        WHERE activity_type IN (
            'PATCH_MANAGEMENT_MESSAGE',
            'SOFTWARE_PATCH_MANAGEMENT_MESSAGE'
        )
    ) AS last_warning_at,
    COUNT(*) FILTER (
        WHERE activity_type IN (
            'PATCH_MANAGEMENT_MESSAGE',
            'SOFTWARE_PATCH_MANAGEMENT_MESSAGE'
        )
    ) AS warning_events,
    COUNT(*) FILTER (
        WHERE activity_type IN (
            'PATCH_MANAGEMENT_MESSAGE',
            'SOFTWARE_PATCH_MANAGEMENT_MESSAGE'
        )
          AND activity_time >= NOW() - INTERVAL '30 days'
    ) AS warning_events_30d,
    MAX(message) FILTER (
        WHERE activity_type IN (
            'PATCH_MANAGEMENT_MESSAGE',
            'SOFTWARE_PATCH_MANAGEMENT_MESSAGE'
        )
    ) AS last_warning_message,
    -- Scan rollup (NEW). Pair = SOFTWARE_PATCH_MANAGEMENT_SCAN_STARTED
    -- → PATCH_MANAGEMENT_SCAN_COMPLETED; the SOFTWARE_ prefix on
    -- STARTED is Ninja's API quirk (see memory).
    MAX(activity_time) FILTER (
        WHERE activity_type = 'SOFTWARE_PATCH_MANAGEMENT_SCAN_STARTED'
    ) AS last_scan_started,
    MAX(activity_time) FILTER (
        WHERE activity_type = 'PATCH_MANAGEMENT_SCAN_COMPLETED'
    ) AS last_scan_completed,
    MIN(activity_time) FILTER (
        WHERE activity_type = 'SOFTWARE_PATCH_MANAGEMENT_SCAN_STARTED'
    ) AS first_scan_started,
    COUNT(*) FILTER (
        WHERE activity_type = 'SOFTWARE_PATCH_MANAGEMENT_SCAN_STARTED'
          AND activity_time >= NOW() - INTERVAL '30 days'
    ) AS scan_events_30d
FROM ninja_activities.activities
WHERE device_id IS NOT NULL
GROUP BY device_id;

CREATE UNIQUE INDEX device_activity_signal_device_idx
    ON ninja_activities.device_activity_signal (device_id);
CREATE INDEX device_activity_signal_activity_idx
    ON ninja_activities.device_activity_signal (last_activity_event DESC);
CREATE INDEX device_activity_signal_failure_idx
    ON ninja_activities.device_activity_signal (last_patch_failure DESC)
    WHERE last_patch_failure IS NOT NULL;
CREATE INDEX device_activity_signal_warning_idx
    ON ninja_activities.device_activity_signal (last_warning_at DESC)
    WHERE last_warning_at IS NOT NULL;
CREATE INDEX device_activity_signal_warning_count_idx
    ON ninja_activities.device_activity_signal (warning_events_30d DESC)
    WHERE warning_events_30d > 0;

-- =============================================================================
-- device_troubleshooting_signal — full body duplicated from migration
-- 016 with two changes:
--   1. Reads the new warning + scan columns from ar (device_activity_signal).
--   2. Surfaces them in the SELECT so Issues / Drilldown can use them.
--
-- Issue_type and suggested_action CASE blocks unchanged from 016.
-- =============================================================================
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
    dps.ever_installed,
    dps.last_seen_at,
    CASE
        WHEN NOT COALESCE(dps.ever_installed, FALSE) THEN 'no_patch_data'
        WHEN dps.last_seen_at IS NULL THEN 'stale_patch_data'
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
    COALESCE(ar.patch_failure_events_30d, 0) AS patch_failure_events_30d,
    ar.last_failure_message,
    -- NEW: warning rollup surfaced for Issues / Drilldown.
    ar.last_warning_at,
    COALESCE(ar.warning_events, 0) AS warning_events,
    COALESCE(ar.warning_events_30d, 0) AS warning_events_30d,
    ar.last_warning_message,
    -- NEW: scan rollup surfaced so operators can see "when did Ninja
    -- last scan this device?" and "when did patch management start?"
    ar.last_scan_started,
    ar.last_scan_completed,
    ar.first_scan_started,
    COALESCE(ar.scan_events_30d, 0) AS scan_events_30d,
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
        WHEN NOT COALESCE(dps.ever_installed, FALSE) AND COALESCE(d.offline, FALSE) THEN 'Never patched and offline'
        WHEN NOT COALESCE(dps.ever_installed, FALSE) THEN 'Never patched'
        WHEN dps.last_seen_at IS NULL AND COALESCE(d.offline, FALSE) THEN 'Stalled (install dates missing) and offline'
        WHEN dps.last_seen_at IS NULL THEN 'Stalled (install dates missing)'
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
        WHEN NOT COALESCE(dps.ever_installed, FALSE) AND COALESCE(d.offline, FALSE) THEN 'Bring online; verify Ninja agent and patch policy'
        WHEN NOT COALESCE(dps.ever_installed, FALSE) THEN 'Verify policy assignment, agent health, and OS patch inventory'
        WHEN dps.last_seen_at IS NULL AND COALESCE(d.offline, FALSE) THEN 'Bring online; Ninja reports installs but without dates — verify agent patch reporting'
        WHEN dps.last_seen_at IS NULL THEN 'Ninja reports installs but without dates — verify agent patch reporting'
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
CREATE INDEX device_troubleshooting_signal_warning_idx
    ON ninja_core.device_troubleshooting_signal (warning_events_30d DESC)
    WHERE warning_events_30d > 0;
CREATE INDEX device_troubleshooting_signal_failure_idx
    ON ninja_core.device_troubleshooting_signal (patch_failure_events_30d DESC)
    WHERE patch_failure_events_30d > 0;
