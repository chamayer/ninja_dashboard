-- Repair migration: rebuild client_platform_links from scratch.
--
-- Migration 053's backfill joined platform_observations to
-- compliance_matrix_current on `norm_name` alone (no client_id), so
-- any hostname collision between unrelated customers attributed the
-- upstream group_id to whichever client had the lowest client_id
-- after `ORDER BY client_id ASC`. Result: client_id 7 (City
-- Painting) ended up linked to Abco - Omni Dental, Landau Realty,
-- Prompt across all three platforms — all because shared hostnames
-- like "DESKTOP-01" exist at multiple clients and the JOIN
-- broadcasted the link.
--
-- This repair:
--   1. TRUNCATEs client_platform_links to discard the contaminated
--      data. Nothing else writes to this table, and no FKs point at
--      it, so TRUNCATE is contained.
--   2. Re-backfills using each observation's `resolved_client_id`
--      that was written AT INGEST TIME. We use only observations
--      resolved BEFORE migration 053 applied, since post-053 runs
--      may have used the contaminated link table for resolution.
--   3. Remaps any historic resolution to demoted client_ids
--      (1299, 1300, 1301) onto the kept ones (22, 7, 10) so the
--      link table matches the post-053 client model.
--   4. Tiebreaks by COUNT(*) DESC, then client_id ASC, so the
--      majority owner of each (platform, group_id) wins. PCHC,
--      City Painting, and GF Supplies still resolve to the kept
--      client_ids per BLUEPRINT decision #1, because pre-053
--      observations resolved to the old client_ids.
--
-- Side note for the matrix: `_write_matrix` in ingest.py does
-- DELETE FROM compliance_matrix_current then INSERT on every run,
-- so the next /run/agent-compliance fully rebuilds the matrix from
-- fresh observations resolved against the corrected link table.
-- No matrix repair needed here.

BEGIN;

-- Step 1: wipe the contaminated link rows.
TRUNCATE TABLE ninja_agent_compliance.client_platform_links;

-- Step 2: re-backfill from pre-053 observations using their
-- at-ingest resolved_client_id.
WITH cutoff AS (
    SELECT COALESCE(
        (
            SELECT applied_at
            FROM ninja_core.schema_migrations
            WHERE version = '053_client_platform_links_backfill'
            LIMIT 1
        ),
        now() - interval '6 hours'
    ) AS pre_053
),
remap AS (
    -- Pre-053 observations for the 3 renamed customers may carry
    -- resolved_client_id = 1299/1300/1301 if discovery had already
    -- minted the duplicate before 053 ran. Remap to the kept ids.
    SELECT 1299::bigint AS old_id, 22::bigint  AS new_id UNION ALL
    SELECT 1300::bigint, 7::bigint              UNION ALL
    SELECT 1301::bigint, 10::bigint
),
safe_obs AS (
    SELECT
        po.platform,
        po.platform_group_id,
        po.source_id,
        po.platform_group_name,
        po.observed_at,
        COALESCE(r.new_id, po.resolved_client_id) AS client_id
    FROM ninja_agent_compliance.platform_observations po
    CROSS JOIN cutoff
    LEFT JOIN remap r ON r.old_id = po.resolved_client_id
    WHERE po.platform_group_id IS NOT NULL
      AND po.platform_group_id <> ''
      AND po.resolved_client_id IS NOT NULL
      AND po.observed_at < cutoff.pre_053
      AND po.observed_at > cutoff.pre_053 - interval '30 days'
),
per_pair_per_client AS (
    SELECT
        platform,
        platform_group_id,
        source_id,
        client_id,
        COUNT(*) AS cnt,
        MIN(observed_at) AS first_seen_at,
        MAX(observed_at) AS last_seen_at,
        (array_agg(platform_group_name ORDER BY observed_at DESC))[1]
            AS last_seen_name,
        (array_agg(platform_group_name ORDER BY observed_at ASC))[1]
            AS first_seen_name
    FROM safe_obs
    GROUP BY platform, platform_group_id, source_id, client_id
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY platform, platform_group_id, COALESCE(source_id, 0)
            ORDER BY cnt DESC, client_id ASC
        ) AS winner_rn
    FROM per_pair_per_client
)
INSERT INTO ninja_agent_compliance.client_platform_links
    (client_id, platform, platform_group_id, source_id,
     first_seen_name, last_seen_name,
     first_seen_at, last_seen_at,
     updated_by)
SELECT
    client_id,
    platform,
    platform_group_id,
    source_id,
    first_seen_name,
    last_seen_name,
    first_seen_at,
    last_seen_at,
    'backfill_migration_054'
FROM ranked
WHERE winner_rn = 1
ON CONFLICT (platform, platform_group_id, COALESCE(source_id, 0))
DO NOTHING;

COMMIT;

-- Post-flight checks (run manually):
--   -- A: no (platform, group_id) maps to more than one client
--   SELECT platform, platform_group_id, COUNT(DISTINCT client_id)
--   FROM ninja_agent_compliance.client_platform_links
--   GROUP BY 1, 2 HAVING COUNT(DISTINCT client_id) > 1;
--   -- expected: 0 rows
--
--   -- B: client 7 only owns its own Ninja/S1/LMI group ids
--   SELECT client_id, platform, platform_group_id, last_seen_name
--   FROM ninja_agent_compliance.client_platform_links
--   WHERE client_id IN (7, 22, 10, 1273)
--   ORDER BY client_id, platform;
--   -- expected: client 7 has rows only for org id 32 (City
--   -- Painting / CPS) per platform; no Abco / Landau / Prompt
--   -- rows.
--
--   -- C: nothing points at a demoted client
--   SELECT client_id, COUNT(*)
--   FROM ninja_agent_compliance.client_platform_links
--   WHERE client_id IN (1299, 1300, 1301)
--   GROUP BY 1;
--   -- expected: 0 rows
