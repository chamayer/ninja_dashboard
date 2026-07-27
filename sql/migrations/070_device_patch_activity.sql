-- =============================================================================
-- 070_device_patch_activity.sql
-- Per-device "last patch activity" matview.
--
-- Motivation: the Operations /patching/ posture status cards need one boolean
-- per device — "has this device produced a patch scan or install outcome in
-- the last N days" — but there was no pre-aggregated source for it. The view
-- was re-scanning all 467k ninja_patches.patch_facts rows twice per request
-- to compute MAX(installed_at, ninja_observed_at, last_observed_at) per
-- device. Moving that MAX into a refreshed matview lets the request just
-- join on device_id.
--
-- Separate matview (not folded into device_patch_signal) because
-- device_patch_signal has a dependent matview (device_troubleshooting_signal)
-- that would have to be dropped and recreated in lockstep; keeping this one
-- standalone avoids that entanglement and keeps ownership narrow.
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS ninja_patches.device_patch_activity;

CREATE MATERIALIZED VIEW ninja_patches.device_patch_activity AS
SELECT
    pf.device_id,
    MAX(COALESCE(pf.installed_at, pf.ninja_observed_at, pf.last_observed_at))
        AS last_patch_activity_at
FROM ninja_patches.patch_facts pf
WHERE pf.fact_type IN ('patch_state', 'install_outcome')
GROUP BY pf.device_id;

CREATE UNIQUE INDEX device_patch_activity_device_idx
    ON ninja_patches.device_patch_activity (device_id);

CREATE INDEX device_patch_activity_last_activity_idx
    ON ninja_patches.device_patch_activity (last_patch_activity_at DESC);
