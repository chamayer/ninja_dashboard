-- Track device hostname renames detected at ingest time.
--
-- When (client_id, platform, platform_device_id) reappears under a
-- different norm_name than its last observation, it is a rename.
-- We record the before/after on Debug only — no findings, no alerts.
-- Compliance state under the new hostname remains source of truth.
--
-- Detection is idempotent: once a rename is recorded, subsequent
-- collections compare new observations against the newly-renamed
-- record, so the same rename never fires twice.

CREATE TABLE IF NOT EXISTS ninja_agent_compliance.device_renames (
    rename_id          BIGSERIAL PRIMARY KEY,
    client_id          integer NOT NULL,
    client_name        text NOT NULL,
    platform           text NOT NULL,
    platform_device_id text NOT NULL,
    old_norm_name      text NOT NULL,
    old_hostname       text NOT NULL,
    new_norm_name      text NOT NULL,
    new_hostname       text NOT NULL,
    detected_at        timestamptz NOT NULL DEFAULT now(),
    run_id             bigint
);

CREATE INDEX IF NOT EXISTS device_renames_client_platform_idx
    ON ninja_agent_compliance.device_renames (client_id, platform, platform_device_id);
CREATE INDEX IF NOT EXISTS device_renames_detected_idx
    ON ninja_agent_compliance.device_renames (detected_at DESC);

-- One-time backfill: compare the latest and second-latest observation
-- per (client_id, platform, platform_device_id) in existing history.
-- Without this, renames that happened just before this migration
-- would be lost (after migration, the next Python detection sees the
-- newly-renamed observation as the "prior" record for future runs).
-- Going forward `_detect_device_renames` in ingest.py handles new
-- rename events; this catch-up only runs once.
INSERT INTO ninja_agent_compliance.device_renames (
    client_id, client_name, platform, platform_device_id,
    old_norm_name, old_hostname, new_norm_name, new_hostname,
    detected_at, run_id
)
WITH ranked AS (
    SELECT
        resolved_client_id,
        resolved_client_name,
        platform,
        platform_device_id,
        norm_name,
        hostname,
        observed_at,
        ROW_NUMBER() OVER (
            PARTITION BY resolved_client_id, platform, platform_device_id
            ORDER BY observed_at DESC
        ) AS rn
    FROM ninja_agent_compliance.platform_observations
    WHERE resolved_client_id IS NOT NULL
      AND platform_device_id IS NOT NULL
      AND platform_device_id <> ''
),
latest AS (SELECT * FROM ranked WHERE rn = 1),
prior  AS (SELECT * FROM ranked WHERE rn = 2)
SELECT
    latest.resolved_client_id,
    latest.resolved_client_name,
    latest.platform,
    latest.platform_device_id,
    prior.norm_name,
    prior.hostname,
    latest.norm_name,
    latest.hostname,
    latest.observed_at,
    NULL
FROM latest
JOIN prior USING (resolved_client_id, platform, platform_device_id)
WHERE latest.norm_name <> prior.norm_name;
