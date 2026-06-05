-- =============================================================================
-- 016_install_signal_and_patch_category.sql
-- Two changes folded into one migration because they touch the same MVs:
--
-- 1. Never-Patched bug fix. device_patch_signal previously filtered
--    `installed_at IS NOT NULL` at source, which dropped devices whose
--    only INSTALLED rows lack a Ninja `installedAt` (~6 devices today).
--    Those devices were classified as never-patched even though Ninja
--    knows they ARE installed. Fix: drop the source filter and add
--    `ever_installed` bool. last_seen_at retains its prior semantics
--    (strict MAX(installed_at) of real install dates) so the 53
--    references in metabase_bootstrap.py keep working.
--
-- 2. Surface patch_category (from patch_facts.type) on
--    current_patch_state and latest_install_outcome so dashboards
--    can render it and the bootstrap exclude fragment can filter it.
--
-- Dependency order: device_troubleshooting_signal (mig 015) reads
-- both current_patch_state and latest_install_outcome, so it must be
-- dropped first and recreated last. Its body is duplicated from 015
-- with three CASE-block updates (patch_status, issue_type,
-- suggested_action) to use the new ever_installed signal and to add
-- explicit branches for "Stalled (install dates missing)".
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS ninja_core.device_troubleshooting_signal;
DROP MATERIALIZED VIEW IF EXISTS ninja_patches.device_patch_signal;
DROP MATERIALIZED VIEW IF EXISTS ninja_patches.latest_install_outcome;
DROP MATERIALIZED VIEW IF EXISTS ninja_patches.current_patch_state;

CREATE MATERIALIZED VIEW ninja_patches.current_patch_state AS
SELECT DISTINCT ON (pf.device_id, pf.patch_uid)
    pf.id,
    pf.device_id,
    pf.patch_uid,
    pf.status,
    pf.severity,
    pf.type AS patch_category,
    pf.name AS patch_name,
    pf.kb_number,
    pf.installed_at,
    pf.first_observed_at,
    pf.last_observed_at
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type = 'patch_state'
ORDER BY pf.device_id, pf.patch_uid, pf.last_observed_at DESC, pf.id DESC;

CREATE UNIQUE INDEX current_patch_state_device_patch_idx
    ON ninja_patches.current_patch_state (device_id, patch_uid);
CREATE INDEX current_patch_state_status_idx
    ON ninja_patches.current_patch_state (status);
CREATE INDEX current_patch_state_severity_idx
    ON ninja_patches.current_patch_state (severity);
CREATE INDEX current_patch_state_category_idx
    ON ninja_patches.current_patch_state (patch_category);
CREATE INDEX current_patch_state_observed_idx
    ON ninja_patches.current_patch_state (last_observed_at DESC);

CREATE MATERIALIZED VIEW ninja_patches.latest_install_outcome AS
SELECT DISTINCT ON (pf.device_id, pf.patch_uid)
    pf.id,
    pf.device_id,
    pf.patch_uid,
    pf.status,
    pf.severity,
    pf.type AS patch_category,
    pf.name AS patch_name,
    pf.kb_number,
    pf.installed_at,
    pf.ninja_observed_at,
    pf.last_observed_at
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type = 'install_outcome'
ORDER BY
    pf.device_id,
    pf.patch_uid,
    pf.installed_at DESC NULLS LAST,
    pf.ninja_observed_at DESC NULLS LAST,
    pf.last_observed_at DESC,
    pf.id DESC;

CREATE UNIQUE INDEX latest_install_outcome_device_patch_idx
    ON ninja_patches.latest_install_outcome (device_id, patch_uid);
CREATE INDEX latest_install_outcome_status_idx
    ON ninja_patches.latest_install_outcome (status);
CREATE INDEX latest_install_outcome_category_idx
    ON ninja_patches.latest_install_outcome (patch_category);
CREATE INDEX latest_install_outcome_installed_idx
    ON ninja_patches.latest_install_outcome (installed_at DESC)
    WHERE installed_at IS NOT NULL;

-- device_patch_signal:
-- - ever_installed: existence-only check. TRUE if device has ANY
--   install_outcome / INSTALLED row, regardless of whether
--   installed_at is populated. Drives the new "Never patched" gate
--   in metabase_bootstrap and device_troubleshooting_signal.
-- - last_seen_at: STRICTLY the latest real installed_at. NULL when
--   ever_installed is TRUE but Ninja never gave us dates (the
--   "Stalled (install dates missing)" case, ~6 devices today).
-- - install_attempts: count of dated install rows (semantics unchanged).
CREATE MATERIALIZED VIEW ninja_patches.device_patch_signal AS
SELECT
    pf.device_id,
    BOOL_OR(pf.status = 'INSTALLED') AS ever_installed,
    MAX(pf.installed_at) FILTER (WHERE pf.installed_at IS NOT NULL) AS last_seen_at,
    COUNT(*) FILTER (WHERE pf.installed_at IS NOT NULL) AS install_attempts
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type = 'install_outcome'
GROUP BY pf.device_id;

CREATE UNIQUE INDEX device_patch_signal_device_idx
    ON ninja_patches.device_patch_signal (device_id);
CREATE INDEX device_patch_signal_seen_idx
    ON ninja_patches.device_patch_signal (last_seen_at DESC);
CREATE INDEX device_patch_signal_ever_installed_idx
    ON ninja_patches.device_patch_signal (ever_installed);

-- =============================================================================
-- device_troubleshooting_signal — duplicated from migration 015 with the
-- three CASE blocks (patch_status, issue_type, suggested_action) updated
-- to read dps.ever_installed (existence check) instead of inferring
-- "never patched" from dps.last_seen_at IS NULL, plus new branches for
-- the "Stalled (install dates missing)" case.
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
