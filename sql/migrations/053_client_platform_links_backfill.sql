-- One-time backfill of client_platform_links from existing
-- observations + matrix, then resolve the 3 known duplicate-client
-- pairs that name-only discovery created during the 2026-06-18
-- platform renames (PCHC, City Painting via CPS, GF Supplies).
--
-- Per locked decision in BLUEPRINT.md:
--   * Keep the OLD client_ids (22, 7, 10). Demote the new duplicates
--     (1299, 1300, 1301). Treat the rename as if the duplicate-mint
--     never happened.
--   * Refresh `clients.client_name` on every kept client to the
--     current upstream name.
--   * For GoFlow/Goflow (id 1273, no duplicate created), apply the
--     same name-refresh rule.
--   * Close any org_candidates rows superseded by the new id-link
--     mapping.
--
-- Important sequencing note: `clients` has a UNIQUE constraint on
-- client_name. The 3 duplicate rows currently hold the canonical
-- names (`PCHC - Parent Care`, `City Painting`,
-- `GF Supplies / Sigo Signs`) that we want to assign to the kept
-- clients. We must first rename the duplicates with a `[demoted ...]`
-- suffix to release the unique names, then rename the keepers.

BEGIN;

-- ---------------------------------------------------------------
-- Step 1: backfill link rows from current observations + matrix
-- ---------------------------------------------------------------
-- For each (platform, platform_group_id, source_id) seen in the last
-- 30 days of observations, attribute it to the client_id that owns
-- the matching matrix rows. Tiebreak per locked decision: lowest
-- client_id wins (i.e., the older row, before discovery created
-- duplicates).

WITH obs_client_map AS (
    SELECT
        po.platform,
        po.platform_group_id,
        po.source_id,
        m.client_id,
        po.platform_group_name,
        po.observed_at
    FROM ninja_agent_compliance.platform_observations po
    JOIN ninja_agent_compliance.compliance_matrix_current m
        ON m.norm_name = po.norm_name
    WHERE po.platform_group_id IS NOT NULL
      AND po.platform_group_id <> ''
      AND po.observed_at > now() - interval '30 days'
),
candidates AS (
    SELECT
        platform,
        platform_group_id,
        source_id,
        client_id,
        COUNT(*) AS device_count,
        MIN(observed_at) AS first_seen_at,
        MAX(observed_at) AS last_seen_at,
        (array_agg(platform_group_name ORDER BY observed_at DESC))[1] AS last_seen_name,
        (array_agg(platform_group_name ORDER BY observed_at ASC))[1] AS first_seen_name
    FROM obs_client_map
    GROUP BY platform, platform_group_id, source_id, client_id
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY platform, platform_group_id, COALESCE(source_id, 0)
            ORDER BY client_id ASC
        ) AS winner_rn
    FROM candidates
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
    'backfill_migration_053'
FROM ranked
WHERE winner_rn = 1
ON CONFLICT (platform, platform_group_id, COALESCE(source_id, 0))
DO NOTHING;

-- ---------------------------------------------------------------
-- Step 2: rename the 3 duplicate clients with a suffix so we can
-- free the canonical names for the kept clients. Also demotes them
-- (enabled=false, source='demoted') in the same statement.
-- ---------------------------------------------------------------
UPDATE ninja_agent_compliance.clients
SET client_name = client_name ||
                  ' [demoted 2026-06-18 dup of #' ||
                  CASE client_id
                      WHEN 1299 THEN '22'
                      WHEN 1300 THEN '7'
                      WHEN 1301 THEN '10'
                  END || ']',
    enabled = false,
    source = 'demoted',
    notes = COALESCE(notes, '') ||
            CASE WHEN COALESCE(notes, '') = '' THEN '' ELSE E'\n' END ||
            'Demoted 2026-06-18 by migration 053: duplicate of client_id ' ||
            CASE client_id
                WHEN 1299 THEN '22 (PCHC) -- rename of Ninja org 15'
                WHEN 1300 THEN '7 (City Painting / CPS) -- rename of Ninja org 32'
                WHEN 1301 THEN '10 (GF Supplies) -- rename of Ninja org 34'
            END,
    updated_at = now(),
    updated_by = 'id_link_migration'
WHERE client_id IN (1299, 1300, 1301)
  AND client_name NOT LIKE '%[demoted%';

-- ---------------------------------------------------------------
-- Step 3: drop duplicate matrix rows owned by the demoted clients.
-- Kept clients already hold rows for the same norm_names; UPDATE of
-- client_id would PK-conflict, so we delete and let the next
-- /run/agent-compliance rebuild them under the kept client_ids.
-- ---------------------------------------------------------------
DELETE FROM ninja_agent_compliance.compliance_matrix_current
WHERE client_id IN (1299, 1300, 1301);

-- ---------------------------------------------------------------
-- Step 4: refresh client_name on kept clients (Ninja-authoritative).
-- Safe now -- duplicates were renamed in Step 2 and no longer hold
-- the unique canonical name slot.
-- ---------------------------------------------------------------
UPDATE ninja_agent_compliance.clients
SET client_name = 'PCHC - Parent Care',
    updated_at = now(),
    updated_by = 'id_link_migration'
WHERE client_id = 22 AND client_name <> 'PCHC - Parent Care';

UPDATE ninja_agent_compliance.clients
SET client_name = 'City Painting',
    updated_at = now(),
    updated_by = 'id_link_migration'
WHERE client_id = 7 AND client_name <> 'City Painting';

UPDATE ninja_agent_compliance.clients
SET client_name = 'GF Supplies / Sigo Signs',
    updated_at = now(),
    updated_by = 'id_link_migration'
WHERE client_id = 10 AND client_name <> 'GF Supplies / Sigo Signs';

-- Ninja casing-only change for org id 7 (GoFlow -> Goflow)
UPDATE ninja_agent_compliance.clients
SET client_name = 'Goflow',
    updated_at = now(),
    updated_by = 'id_link_migration'
WHERE client_id = 1273 AND client_name <> 'Goflow';

-- ---------------------------------------------------------------
-- Step 5: refresh the matrix view's denormalized client_name so
-- dashboards reflect the rename immediately. Next ingest run will
-- also upsert these, but operators see it sooner this way.
-- ---------------------------------------------------------------
UPDATE ninja_agent_compliance.compliance_matrix_current
SET client_name = 'PCHC - Parent Care' WHERE client_id = 22;
UPDATE ninja_agent_compliance.compliance_matrix_current
SET client_name = 'City Painting' WHERE client_id = 7;
UPDATE ninja_agent_compliance.compliance_matrix_current
SET client_name = 'GF Supplies / Sigo Signs' WHERE client_id = 10;
UPDATE ninja_agent_compliance.compliance_matrix_current
SET client_name = 'Goflow' WHERE client_id = 1273;

-- ---------------------------------------------------------------
-- Step 6: close org_candidates rows whose (platform, name) now
-- maps to a client via the new link table.
-- ---------------------------------------------------------------
UPDATE ninja_agent_compliance.org_candidates oc
SET status = 'promoted',
    enabled = false,
    updated_at = now(),
    updated_by = 'id_link_migration'
WHERE oc.enabled
  AND EXISTS (
      SELECT 1
      FROM ninja_agent_compliance.client_platform_links lnk
      JOIN ninja_agent_compliance.platform_observations po
        ON  po.platform          = lnk.platform
        AND po.platform_group_id = lnk.platform_group_id
      WHERE po.platform = oc.platform
        AND lower(trim(po.platform_group_name)) = lower(trim(oc.candidate_name))
  );

COMMIT;

-- Post-flight checks (run manually):
--   SELECT platform, platform_group_id, COUNT(DISTINCT client_id)
--   FROM ninja_agent_compliance.client_platform_links
--   GROUP BY 1, 2 HAVING COUNT(DISTINCT client_id) > 1;
--   -- expected: 0 rows
--
--   SELECT client_id, client_name, enabled, source
--   FROM ninja_agent_compliance.clients
--   WHERE client_id IN (7,10,22,26,1273,1299,1300,1301)
--   ORDER BY client_id;
