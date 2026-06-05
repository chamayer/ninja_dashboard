-- =============================================================================
-- 008_patch_summary_materialized_views.sql
-- Precomputes the latest patch-state / install-outcome rows that many
-- Metabase cards otherwise rebuild independently with DISTINCT ON.
-- =============================================================================

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
CREATE INDEX current_patch_state_observed_idx
    ON ninja_patches.current_patch_state (last_observed_at DESC);

CREATE MATERIALIZED VIEW ninja_patches.latest_install_outcome AS
SELECT DISTINCT ON (pf.device_id, pf.patch_uid)
    pf.id,
    pf.device_id,
    pf.patch_uid,
    pf.status,
    pf.severity,
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
CREATE INDEX latest_install_outcome_installed_idx
    ON ninja_patches.latest_install_outcome (installed_at DESC)
    WHERE installed_at IS NOT NULL;

CREATE MATERIALIZED VIEW ninja_patches.device_patch_signal AS
SELECT
    pf.device_id,
    MAX(pf.installed_at) AS last_seen_at,
    COUNT(*) FILTER (WHERE pf.installed_at IS NOT NULL) AS install_attempts
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type = 'install_outcome'
  AND pf.installed_at IS NOT NULL
GROUP BY pf.device_id;

CREATE UNIQUE INDEX device_patch_signal_device_idx
    ON ninja_patches.device_patch_signal (device_id);
CREATE INDEX device_patch_signal_seen_idx
    ON ninja_patches.device_patch_signal (last_seen_at DESC);
