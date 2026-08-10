-- 081: seed the five verified EOL mappings, and surface everything still
-- unmapped so it is visible rather than silently unevaluated.
--
-- Measured 2026-08-10 against the live corpus (462 products, 8,308 releases).
-- Naive substring matching of our 21,395 catalogue titles produced mostly
-- FALSE POSITIVES, which is why this table is operator judgement and not a
-- matcher:
--
--   'Intel(R) Trusted Connect Services Client'  -> rust   ("trust" ⊃ "rust")
--   'ClickOnce Bootstrapper Package for .NET'   -> bootstrap
--   'ExpressConnect Drivers & Services'         -> express  (Express.js)
--   'microsoft.net.sdk.tvos.manifest-8.0.100'   -> tvos
--
-- The first alone would have put a confident, precisely dated, entirely wrong
-- end-of-life finding on 282 devices.
--
-- Patterns below are anchored, not '%substring%', for exactly that reason.

INSERT INTO operations.eol_product_map
    (tenant_id, raw_pattern, eol_product, priority, notes)
VALUES
    -- 3,285 devices, 781 already on end-of-life releases.
    (1, 'google chrome',     'chrome',            10,
     'Verified 2026-08-10: 121 installed versions match Chrome release cycles.'),
    -- 186 + 54 devices across the two builds.
    (1, 'mozilla firefox%',  'firefox',           10,
     'Verified 2026-08-10: covers both (x64 en-US) and (x86 en-US) builds.'),
    -- 147 devices, 101 on end-of-life releases.
    (1, 'notepad++%',        'notepad-plus-plus', 10,
     'Verified 2026-08-10.'),
    -- 111 devices, 55 on end-of-life releases.
    (1, 'powershell 7%',     'powershell',        10,
     'Verified 2026-08-10. Windows PowerShell 5.x is OS-bundled and follows the '
     'OS lifecycle, so it is deliberately not mapped here.')
ON CONFLICT DO NOTHING;

-- What is still unmapped, ranked by how much it would matter.
--
-- Without this, an unmapped title simply receives no lifecycle evaluation and
-- nothing says so -- the silent-skip shape that operations/AGENTS.md and
-- ADR-0012 both rule out. This makes the remaining work finite, ordered and
-- visible: it proposes a corpus product for each unmapped title, and states how
-- many devices and versions would be affected if an operator accepts it.
--
-- A row here is a SUGGESTION, never an applied mapping. The false positives
-- above will appear in this list; that is correct, because the operator is the
-- one who can tell 'Trusted Connect' from Rust.
--
-- MATERIALIZED, because as a plain view this takes **37 seconds**: it is a
-- 21,395 x 462 ILIKE cross-match, and that cost is inherent to suggesting
-- matches rather than requiring exact names. Behind an operator page that is
-- unusable, and page load time is an active track. The inputs are the corpus
-- (refreshed on the catalogue cadence) and the mapping table (operator edits),
-- so a matview refreshed alongside the corpus is exactly right -- the result is
-- 1,989 rows.
--
-- Refresh is non-concurrent, matching v_software_safety: it briefly locks the
-- matview, but this is a suggestions list refreshed a few times a day, and
-- CONCURRENTLY cannot run inside the projector's transaction.
DROP VIEW IF EXISTS operations.v_eol_mapping_candidates;
CREATE MATERIALIZED VIEW IF NOT EXISTS operations.v_eol_mapping_candidates AS
WITH corpus AS (
    SELECT e.name, e.label, e.category
      FROM intel.eol_products e
     WHERE length(e.name) >= 4
       AND EXISTS (SELECT 1 FROM intel.eol_releases r
                    WHERE r.product_name = e.name AND r.eol_from IS NOT NULL)
),
unmapped AS (
    SELECT p.id, p.canonical_name
      FROM catalog.products p
     WHERE NOT EXISTS (
            SELECT 1 FROM operations.eol_product_map m
             WHERE p.canonical_name ILIKE m.raw_pattern
           )
)
SELECT u.canonical_name,
       c.name     AS suggested_eol_product,
       c.category AS suggested_category,
       COUNT(DISTINCT sv.id)                                 AS versions_would_match,
       COUNT(DISTINCT sic.device_id)                         AS devices,
       COUNT(DISTINCT sv.id) FILTER (WHERE r.is_eol)         AS versions_already_eol,
       COUNT(DISTINCT sic.device_id) FILTER (WHERE r.is_eol) AS devices_on_eol,
       MIN(r.eol_from) FILTER (WHERE r.is_eol)               AS earliest_eol
  FROM unmapped u
  JOIN corpus c
    ON u.canonical_name ILIKE '%' || c.name || '%'
    OR (length(c.label) >= 4 AND u.canonical_name ILIKE '%' || c.label || '%')
  JOIN catalog.software_versions sv ON sv.product_id = u.id AND sv.version <> ''
  JOIN intel.eol_releases r
    ON r.product_name = c.name
   AND (sv.version = r.cycle OR sv.version LIKE r.cycle || '.%')
  JOIN operations.software_installations_current sic
    ON sic.software_version_id = sv.id
   AND sic.stale_since IS NULL AND sic.deleted_at IS NULL
 GROUP BY 1, 2, 3;

CREATE INDEX IF NOT EXISTS eol_mapping_candidates_impact_idx
    ON operations.v_eol_mapping_candidates (devices_on_eol DESC, devices DESC);
CREATE INDEX IF NOT EXISTS eol_mapping_candidates_name_idx
    ON operations.v_eol_mapping_candidates (canonical_name);

-- Read model: no runtime role may write it. See operations/AGENTS.md and the
-- migration 0122 precedent.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_eol_mapping_candidates
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON operations.v_eol_mapping_candidates
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON MATERIALIZED VIEW operations.v_eol_mapping_candidates IS
    'Suggestions only. Catalogue titles with no EOL mapping, paired with corpus '
    'products whose release cycles their installed versions would actually '
    'match, ranked by device impact. Substring-matched, so it contains false '
    'positives by design -- an operator decides, and records the decision in '
    'operations.eol_product_map.';
