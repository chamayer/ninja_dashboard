-- 116: indexes for the active software-installation decision lookups.
--
-- The user-exposure and cleanup pages join the small set of operator
-- decisions to the current installation projection twice: once by canonical
-- title and once by case-insensitive publisher.  Without these access paths,
-- each branch scans every current installation (about 580k rows in production)
-- before applying the decision match.  The pages are read-only projections;
-- these indexes do not change classification, finding generation, approval
-- precedence, or any source-derived state.
--
-- Keep the predicates exactly aligned with the application queries.  Retired
-- and stale installations cannot participate in either result and should not
-- consume index maintenance or storage.
--
-- The raw migration runner applies one file in a transaction, so PostgreSQL
-- cannot use CREATE INDEX CONCURRENTLY here.  This is an additive index-only
-- migration; startup holds the normal index-build lock while it completes.

CREATE INDEX IF NOT EXISTS idx_sic_active_tenant_canonical
    ON operations.software_installations_current (tenant_id, canonical_name)
    WHERE deleted_at IS NULL AND stale_since IS NULL;

CREATE INDEX IF NOT EXISTS idx_sic_active_tenant_publisher_lower
    ON operations.software_installations_current (tenant_id, LOWER(publisher))
    WHERE deleted_at IS NULL AND stale_since IS NULL;

COMMENT ON INDEX operations.idx_sic_active_tenant_canonical IS
    'Supports active software-decision title lookups in Operations user exposure and cleanup.';

COMMENT ON INDEX operations.idx_sic_active_tenant_publisher_lower IS
    'Supports active software-decision case-insensitive publisher lookups in Operations user exposure and cleanup.';
