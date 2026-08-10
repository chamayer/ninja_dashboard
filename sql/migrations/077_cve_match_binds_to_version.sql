-- 077: bind CVE matches to a product+version instead of a bare title.
--
-- `operations.cve_match` has carried a `version_range` column since 072 and
-- every row has it empty. The consequence is recorded in the ADR-0008
-- amendment of 2026-08-06 and again in ADR-0015: every device running any
-- version of a matched product is flagged identically, including patched ones,
-- so `vulnerable_software` reports product-level suspicion while reading as
-- per-device vulnerability. ADR-0012 s5 governs and binds CVEs to
-- software+version.
--
-- The matcher already computes the version filter it needs
-- (`_filter_by_version_prefix`) and then discards it at INSERT. It also derives
-- the prefix from the *title text* rather than the installed `version` column,
-- so today nothing in the pipeline reads the version we actually observed.
-- This migration gives the match somewhere to put it.

-- The resolved catalogue version this match applies to. Nullable: a CPE with a
-- version-agnostic version ('*', '-', or absent) genuinely applies to the whole
-- product, and forcing those onto an arbitrary version would be a fabrication.
-- Those rows keep software_version_id NULL and stay product-level, which is now
-- an explicit, queryable state rather than the silent default for everything.
ALTER TABLE operations.cve_match
    ADD COLUMN IF NOT EXISTS software_version_id bigint
    REFERENCES catalog.software_versions(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS cve_match_software_version_idx
    ON operations.cve_match (software_version_id)
    WHERE software_version_id IS NOT NULL;

-- The old uniqueness key cannot express one CVE hitting two versions of the
-- same title, which is the entire point of this change. Replace it with a key
-- that includes the version.
--
-- NULLS NOT DISTINCT so that product-level matches (software_version_id NULL)
-- still deduplicate against each other -- without it every re-run would insert
-- a fresh NULL row, since NULL <> NULL under the default. 075 applied the same
-- treatment to catalog.products for the same reason. Requires PostgreSQL 15+;
-- the server is 16.
-- 072 created it as a unique *index* named cve_match_scope_idx, not a table
-- constraint, so this is a DROP INDEX. `ingest/intel/matcher.py` infers its
-- ON CONFLICT target from these same columns and is updated in the same change;
-- leaving one without the other breaks the insert.
DROP INDEX IF EXISTS operations.cve_match_scope_idx;

CREATE UNIQUE INDEX IF NOT EXISTS cve_match_scope_idx
    ON operations.cve_match (
        tenant_id, canonical_name, software_version_id, cve_id, match_kind
    ) NULLS NOT DISTINCT;

COMMENT ON COLUMN operations.cve_match.software_version_id IS
    'Catalogue version this match applies to. NULL means the CPE was '
    'version-agnostic and the match is genuinely product-level -- not that the '
    'version is unknown.';

COMMENT ON COLUMN operations.cve_match.version_range IS
    'The CPE version expression that produced this match, retained as '
    'evidence for why software_version_id was chosen.';
