-- 078: end-of-life corpus from endoflife.date, plus the operator-maintained
-- mapping from our catalogue titles onto it.
--
-- `eol_runtime` has been firing on a title regex ("matches end-of-life runtime
-- pattern") because no lifecycle producer ever existed: 0 of 40,541
-- catalog.software_versions rows carry an eol_date, and none of the eight
-- registered intel connectors (nvd, cpe_dict, cisa_kev, epss, winget,
-- chocolatey, otx, abusech) carries lifecycle data. This is the missing
-- producer, not a missing surface.
--
-- Shape follows cpe_dict exactly: the raw feed lands in `intel` as a global
-- reference corpus with no tenant and no RLS, keyed naturally, and a separate
-- mapping step decides what it means for our catalogue. That separation is why
-- a feed refresh never has to re-decide title matching, and why a matching fix
-- never has to re-fetch 462 products.

CREATE SCHEMA IF NOT EXISTS intel;

-- One row per endoflife.date product. Natural key, matching intel.cves.cve_id
-- and intel.cpes.cpe23. `aliases` and `tags` are retained because they are the
-- raw material for mapping suggestions -- discarding them would mean re-fetching
-- the whole corpus to improve matching later.
CREATE TABLE IF NOT EXISTS intel.eol_products (
    name            text PRIMARY KEY,           -- e.g. 'python', 'windows-server'
    label           text NOT NULL DEFAULT '',   -- e.g. 'Python'
    category        text NOT NULL DEFAULT '',   -- os | framework | database | ...
    aliases         jsonb NOT NULL DEFAULT '[]'::jsonb,
    tags            jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS eol_products_category_idx
    ON intel.eol_products (category);

-- One row per release cycle of a product. `cycle` is the series identifier
-- ('3.13'), not a full version ('3.13.2') -- an installed version maps onto it
-- by longest prefix.
--
-- API v1 is used rather than the legacy /api/{product}.json because v1 splits
-- `isEol` (boolean) from `eolFrom` (date). The legacy endpoint overloads a
-- single `eol` field as either a date string or a bare boolean depending on the
-- product, which cannot be typed in a column without losing information.
CREATE TABLE IF NOT EXISTS intel.eol_releases (
    product_name    text NOT NULL REFERENCES intel.eol_products(name) ON DELETE CASCADE,
    cycle           text NOT NULL,              -- '3.13', '2019', '22.04'
    label           text NOT NULL DEFAULT '',
    release_date    date,
    eol_from        date,                       -- NULL when not yet announced
    is_eol          boolean NOT NULL DEFAULT false,
    is_maintained   boolean NOT NULL DEFAULT true,
    is_lts          boolean NOT NULL DEFAULT false,
    latest_version  text NOT NULL DEFAULT '',
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_name, cycle)
);

CREATE INDEX IF NOT EXISTS eol_releases_eol_from_idx
    ON intel.eol_releases (eol_from) WHERE eol_from IS NOT NULL;

-- Which catalogue titles correspond to which endoflife.date product.
--
-- ADR-0012 section 6: a rule mapping one domain value to another is
-- operator-maintainable data, never a constant in code. A hardcoded
-- {'python': 'python', ...} dict would be invisible to the operator it affects
-- and uncorrectable without a deploy. The reference shape is
-- operations.os_group_mappings and operations.publisher_aliases: pattern,
-- target, priority, first match wins.
--
-- `raw_pattern` is an ILIKE pattern over catalog.products.canonical_name, the
-- same operator convention publisher_aliases uses (migration 0088), so an
-- operator writing a mapping does not have to learn a second syntax.
CREATE TABLE IF NOT EXISTS operations.eol_product_map (
    id              bigserial PRIMARY KEY,
    tenant_id       bigint NOT NULL,
    raw_pattern     text NOT NULL,
    eol_product     text NOT NULL REFERENCES intel.eol_products(name) ON DELETE CASCADE,
    priority        int  NOT NULL DEFAULT 100,  -- lower wins
    notes           text NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- No RLS, deliberately and consistently with its neighbours: the tenant-scoped
-- tables created in this SQL migration path (operations.cve_match,
-- operations.safety_signal, both from 072) carry a tenant_id column and no
-- policy, unlike the Django-managed operations tables which have forced RLS.
-- Adding a policy to this one table alone would make the intel surface
-- inconsistent with itself. Recorded here so the asymmetry is a known state
-- rather than an oversight; unifying it is a separate decision covering all
-- three tables.
CREATE UNIQUE INDEX IF NOT EXISTS uq_eol_product_map
    ON operations.eol_product_map (tenant_id, LOWER(raw_pattern), eol_product);

CREATE INDEX IF NOT EXISTS eol_product_map_priority_idx
    ON operations.eol_product_map (tenant_id, priority);

-- Where a version's EOL date came from. catalog.software_versions.eol_source
-- already exists (074) and is empty; this gives it a value with provenance
-- rather than a bare date.
COMMENT ON COLUMN catalog.software_versions.eol_source IS
    'Provenance of eol_date, e.g. ''endoflife.date:python#3.13''. Empty means '
    'no lifecycle data has been matched to this version.';

-- Least privilege, matching 072 and 074. The intel corpus is ingest-written and
-- read by everything; the mapping table is operator-maintained, so Operations
-- needs DML on it and ingest only reads it.
GRANT SELECT ON intel.eol_products, intel.eol_releases
    TO operations_app, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON intel.eol_products, intel.eol_releases
    TO ninja_ingest;

GRANT SELECT, INSERT, UPDATE, DELETE ON operations.eol_product_map TO operations_app;
GRANT SELECT ON operations.eol_product_map TO operations_readonly, metabase_ro, ninja_ingest;
GRANT USAGE, SELECT ON SEQUENCE operations.eol_product_map_id_seq TO operations_app;

REVOKE DELETE, TRUNCATE ON intel.eol_products, intel.eol_releases
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
