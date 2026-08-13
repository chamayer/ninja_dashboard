-- 091: stop discarding three fields Ninja already returns for every install.
--
-- `/queries/software` returns name, publisher, version, location, installDate,
-- size, productCode, isSystemComponent and timestamp. The collector kept the
-- first five and dropped the rest, so evidence the platform was already paying
-- to fetch was thrown away on every cycle.
--
-- Measured 2026-08-12 against the live API, 25,000 rows spanning 3,112 devices
-- and 4,434 distinct titles:
--
--   productCode ......... 93.8% non-empty
--   version ............. 96.5%
--   size ................ 40.4%
--   isSystemComponent ... 7.6% true
--
-- Why productCode matters beyond completeness: every join in the software
-- domain currently runs on a lowercased display name. That is why
-- `operations.software_catalog` matches 0 of its 52 rows against installed
-- titles, and why `publisher_aliases` collapses only 6% of distinct
-- publishers. An MSI ProductCode is a GUID that is stable across spelling,
-- casing and localisation.
--
-- `isSystemComponent` marks OS components nobody installed. 7.6% of rows --
-- relevant to the 12,096 single-install titles that are 3% of the fleet's
-- installs and pure noise on the products surface.
--
-- `timestamp` is deliberately not stored: it is the query's own clock, and
-- `last_observed_at` already records when we saw the row.
--
-- NOT added to the material hash, and that is the load-bearing decision here.
-- `_upsert` hashes (publisher, version, location, install_date) to decide
-- whether an installation materially changed. Adding these three would change
-- every hash on the next run and close and reopen all 490,733 SCD-2 intervals
-- in a single cycle -- a self-inflicted history storm on a 1.4 GB table.
-- They are properties of the product rather than of the installation event:
-- product_code and is_system_component are stable per product, and size varies
-- with version, which is already hashed. So they are written on insert and
-- refreshed in place, without manufacturing a material change.
--
-- Nullable with no default, so this is a catalog-only change: no heap
-- rewrite, unlike 089 whose volatile default forced one. Existing rows carry
-- NULL until the next collection refreshes them, which is an honest "not yet
-- observed" rather than a fabricated value.

ALTER TABLE operations.software_installations_current
    ADD COLUMN IF NOT EXISTS product_code text,
    ADD COLUMN IF NOT EXISTS size_bytes bigint,
    ADD COLUMN IF NOT EXISTS is_system_component boolean;

COMMENT ON COLUMN operations.software_installations_current.product_code IS
    'Ninja productCode -- MSI ProductCode GUID where the installer provides '
    'one. ~94% populated. Stable across name spelling/casing/localisation, so '
    'preferable to canonical_name for joining to external catalogs.';
COMMENT ON COLUMN operations.software_installations_current.size_bytes IS
    'Ninja size. ~40% populated; absent for many non-MSI installers.';
COMMENT ON COLUMN operations.software_installations_current.is_system_component IS
    'Ninja isSystemComponent -- true for OS components nobody installed (~8%).';

-- Partial: the index exists to resolve a title to its product identity, and
-- rows without a product code cannot participate in that.
CREATE INDEX IF NOT EXISTS idx_sw_install_current_product_code
    ON operations.software_installations_current (tenant_id, product_code)
    WHERE product_code IS NOT NULL AND deleted_at IS NULL;

-- No grant changes: new columns inherit the table's privileges and no new
-- relation is created, so the read-model revoke rule in operations/AGENTS.md
-- does not apply.
