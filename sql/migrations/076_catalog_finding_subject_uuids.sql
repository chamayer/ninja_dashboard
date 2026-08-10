-- 076: stable uuid handles on the software catalogue, so findings can name a
-- product or a product+version as their subject.
--
-- `operations.findings.subject_id` is a bare uuid column with no foreign key --
-- the subject is polymorphic across client, device, client_user,
-- source_binding and collector_instance, all of which are uuid-keyed rows in
-- `operations.entities`. Software is the first subject that is *not* an owned
-- entity, and per the ADR-0012 amendment of 2026-08-10 it must stay that way:
-- software is global reference data beside `intel.cves`, carrying no tenant and
-- no scope_kind.
--
-- So the catalogue is NOT retyped to look like the entity store. Its primary
-- keys stay bigint and its natural keys stay authoritative, matching how this
-- platform keys reference corpora (`intel.cves.cve_id`, `intel.cpes.cpe23` are
-- both natural text keys). These columns are only the handle the uuid-shaped
-- subject pointer needs.
--
-- Minted, not derived. A uuid v5 over the natural key would be rebuildable, but
-- publisher aliases collapse the unnormalised long tail over time -- measured
-- 2026-08-07 at 84% of installs covered but only 6% of distinct publishers --
-- and a derived id would silently re-identify products on every alias
-- addition, orphaning their findings with no record of when or why. A stored
-- id keeps identity stable across re-normalisation and forces that collapse to
-- be an explicit, audited merge.
--
-- gen_random_uuid() is core in PostgreSQL 13+; the server is 16. pgcrypto is
-- not installed and is not needed.

-- Products: subject of the five title-scoped finding types
-- (whitelist_suggestion, suspicious_name, unauthorized_remote_access,
-- unauthorized_av, known_malicious_hint).
ALTER TABLE catalog.products
    ADD COLUMN IF NOT EXISTS product_uuid uuid NOT NULL DEFAULT gen_random_uuid();

-- Versions: subject of the two release-scoped types (vulnerable_software,
-- eol_runtime). A CVE applies to a release and an EOL date is a release's, so
-- title scope cannot distinguish a patched install from an unpatched one --
-- which is fatal for the two findings whose remedy *is* patching.
ALTER TABLE catalog.software_versions
    ADD COLUMN IF NOT EXISTS version_uuid uuid NOT NULL DEFAULT gen_random_uuid();

-- Unique, because these are identities. Not primary keys: the bigint surrogate
-- and the natural unique key both keep their existing jobs.
--
-- `ADD CONSTRAINT` has no IF NOT EXISTS in PostgreSQL. The runner records
-- applied versions and each file runs in its own transaction, so a re-run
-- cannot happen after success and a failure rolls the whole file back -- but
-- these are guarded anyway to match the idempotent style of 074 and 075.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_catalog_products_uuid'
    ) THEN
        ALTER TABLE catalog.products
            ADD CONSTRAINT uq_catalog_products_uuid UNIQUE (product_uuid);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_catalog_versions_uuid'
    ) THEN
        ALTER TABLE catalog.software_versions
            ADD CONSTRAINT uq_catalog_versions_uuid UNIQUE (version_uuid);
    END IF;
END
$$;

-- No grant changes. 074 already grants SELECT on all catalog tables to
-- operations_app, operations_readonly and metabase_ro, SELECT/INSERT/UPDATE to
-- ninja_ingest, and revokes DELETE/TRUNCATE from all four. A new column
-- inherits the table's privileges, and no new relation is created here, so the
-- read-model revoke rule in operations/AGENTS.md does not apply.
