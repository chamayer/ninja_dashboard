-- 082: let an operator pin a mapping to a version range and an explicit cycle.
--
-- The projector derives the release cycle by longest numeric-dotted prefix of
-- the installed version. Measured 2026-08-10, that fails in two shapes it can
-- never recover from:
--
--   * 47 corpus products label their cycles with something other than a plain
--     dotted number, across 1,419 releases -- measured shapes include '20h2',
--     '2008-r2-sp1', 'se-3' and 'pro-6'. No numeric version prefix-matches
--     those.
--   * 3,057 of our titles carry the version in the *name* while the file
--     version is unrelated -- 'Microsoft Office 2010' installs as 14.0.x --
--     covering 3,810 devices. The CVE matcher already handles this by parsing
--     year/semver tokens out of the title; the EOL projector did not, which
--     made it strictly weaker than the matcher for no reason.
--
-- Both are fixed by making the mapping expressible rather than only derived.
-- Rows leaving these columns NULL behave exactly as before, so nothing
-- regresses; the hard cases get pinned explicitly. `priority` already decides
-- precedence, so a specific row beats a general one.

ALTER TABLE operations.eol_product_map
    ADD COLUMN IF NOT EXISTS version_pattern text NOT NULL DEFAULT '';

ALTER TABLE operations.eol_product_map
    ADD COLUMN IF NOT EXISTS eol_cycle text NOT NULL DEFAULT '';

COMMENT ON COLUMN operations.eol_product_map.version_pattern IS
    'Optional ILIKE pattern over the installed version. Empty means the row '
    'applies to every version of a matching title. Use it to split one title '
    'across cycles, e.g. version_pattern ''14.%'' for Office 2010.';

COMMENT ON COLUMN operations.eol_product_map.eol_cycle IS
    'Optional explicit release cycle in the corpus. Empty means derive it by '
    'longest version prefix, or from a year token in the title. Needed for '
    'cycles no version can prefix-match, e.g. ''20h2'' or ''2008-r2-sp1''.';

-- The uniqueness key must include the version dimension, or a second row
-- pinning a different version range of the same title collides with the first.
DROP INDEX IF EXISTS operations.uq_eol_product_map;

CREATE UNIQUE INDEX IF NOT EXISTS uq_eol_product_map
    ON operations.eol_product_map
       (tenant_id, LOWER(raw_pattern), LOWER(version_pattern), eol_product);
