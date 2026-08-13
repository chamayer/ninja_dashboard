-- 086: match EOL candidates on whole words and aliases, not substrings.
--
-- The candidate matcher in 081 compared our titles to corpus product names with
-- `canonical_name ILIKE '%' || name || '%'`, and ignored the `aliases` array
-- entirely even though the connector stores it. Measured 2026-08-11 across
-- 21,437 titles and 462 corpus products:
--
--   A  substring on name/label (what 081 does)  20,899 pairs   780,486 device-weight
--   B  exact on name/label/alias                    38 pairs     3,619
--   C  whole-word on name/label/alias            8,019 pairs   103,285
--   A-only, i.e. rejected by C                   6,937 pairs   365,411
--
-- That last line is the defect, quantified: 6,937 pairs -- a third of all
-- pairs and 47% of device weight -- existed only because a corpus term appeared
-- buried inside a longer word. 'Intel(R) Trusted Connect Services Client'
-- matched `rust`. So did 'ClickOnce Bootstrapper' -> bootstrap,
-- 'ExpressConnect' -> express (Express.js), '.net.sdk.tvos.manifest' -> tvos.
--
-- Word-boundary matching removes all of them without a single judgement call,
-- and after the change `\mrust\M` matches 0 of our 'trusted connect' titles.
-- The top of the queue by real impact is now chrome, visual-studio, firefox,
-- dotnetfx and powershell -- the previous top 15 contained rust four times.
--
-- Aliases matter independently: they are curated identity from the corpus, so
-- an exact hit on one is identity rather than resemblance. Those are marked
-- `exact` so an operator can accept them in bulk without reading each.

DROP MATERIALIZED VIEW IF EXISTS operations.v_eol_mapping_candidates;

CREATE MATERIALIZED VIEW operations.v_eol_mapping_candidates AS
WITH terms AS (
    -- Every identity string the corpus offers for a product.
    SELECT e.name AS eol_product, lower(t.term) AS term, t.src, e.category
      FROM intel.eol_products e
      CROSS JOIN LATERAL (VALUES (e.name, 'name'), (e.label, 'label')) AS t(term, src)
     WHERE length(t.term) >= 3
       AND EXISTS (SELECT 1 FROM intel.eol_releases r
                    WHERE r.product_name = e.name AND r.eol_from IS NOT NULL)
    UNION
    SELECT e.name, lower(a.value), 'alias', e.category
      FROM intel.eol_products e
      CROSS JOIN LATERAL jsonb_array_elements_text(e.aliases) AS a(value)
     WHERE length(a.value) >= 3
       AND EXISTS (SELECT 1 FROM intel.eol_releases r
                    WHERE r.product_name = e.name AND r.eol_from IS NOT NULL)
),
unmapped AS (
    SELECT p.id, p.canonical_name, lower(p.canonical_name) AS cname
      FROM catalog.products p
     WHERE NOT EXISTS (
            SELECT 1 FROM operations.eol_product_map m
             WHERE p.canonical_name ILIKE m.raw_pattern
           )
),
matched AS (
    SELECT u.id, u.canonical_name, t.eol_product, t.category,
           -- Exact identity beats a word appearing inside a longer title.
           MAX(CASE WHEN u.cname = t.term THEN 2 ELSE 1 END) AS match_rank
      FROM unmapped u
      JOIN terms t
        -- Whole word, not substring. The regex-escape keeps terms containing
        -- '.', '+' or '-' (e.g. 'notepad-plus-plus') from acting as patterns.
        ON u.cname ~ ('\m' || regexp_replace(t.term, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g') || '\M')
     GROUP BY 1, 2, 3, 4
)
SELECT m.canonical_name,
       m.eol_product        AS suggested_eol_product,
       m.category           AS suggested_category,
       CASE WHEN m.match_rank = 2 THEN 'exact' ELSE 'word' END AS match_kind,
       COUNT(DISTINCT sv.id)                                 AS versions_would_match,
       COUNT(DISTINCT sic.device_id)                         AS devices,
       COUNT(DISTINCT sv.id) FILTER (WHERE r.is_eol)         AS versions_already_eol,
       COUNT(DISTINCT sic.device_id) FILTER (WHERE r.is_eol) AS devices_on_eol,
       MIN(r.eol_from) FILTER (WHERE r.is_eol)               AS earliest_eol
  FROM matched m
  JOIN catalog.software_versions sv ON sv.product_id = m.id AND sv.version <> ''
  JOIN intel.eol_releases r
    ON r.product_name = m.eol_product
   AND (sv.version = r.cycle OR sv.version LIKE r.cycle || '.%')
  JOIN operations.software_installations_current sic
    ON sic.software_version_id = sv.id
   AND sic.stale_since IS NULL AND sic.deleted_at IS NULL
 GROUP BY 1, 2, 3, 4;

CREATE INDEX IF NOT EXISTS eol_mapping_candidates_impact_idx
    ON operations.v_eol_mapping_candidates (devices_on_eol DESC, devices DESC);
CREATE INDEX IF NOT EXISTS eol_mapping_candidates_name_idx
    ON operations.v_eol_mapping_candidates (canonical_name);
CREATE INDEX IF NOT EXISTS eol_mapping_candidates_kind_idx
    ON operations.v_eol_mapping_candidates (match_kind);

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_eol_mapping_candidates
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON operations.v_eol_mapping_candidates
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON MATERIALIZED VIEW operations.v_eol_mapping_candidates IS
    'Suggestions for operations.eol_product_map, matched on whole words against '
    'the corpus name, label and aliases -- never on substrings, which produced '
    '6,937 false pairs including rust matching "Trusted Connect". match_kind '
    '''exact'' is a full-string hit on a curated corpus identity and is safe to '
    'accept in bulk; ''word'' needs judgement. Ranked by devices_on_eol.';
