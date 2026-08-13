-- 089: a stable uuid handle on the installation, so a finding can name the
-- device-and-software pair as its subject.
--
-- ADR-0015 §2 assigns `install_path_suspicious` to the installation: "The path
-- belongs to the device-and-software pair, so the finding belongs to the
-- relationship." That clause was never implemented -- step 3 moved the five
-- title-scoped types onto software subjects and left this one on `device`.
-- ADR-0015 explicitly left the mechanism open: "whether a relationship subject
-- needs more than that is an implementation question this record does not
-- settle." This migration settles it the same way 076 did for the catalog.
--
-- Minted, not derived -- and the case here is stronger than 076's.
--
-- 076 rejected a derived id because publisher aliases collapse the long tail
-- and "a derived id would silently re-identify products on every alias
-- addition, orphaning their findings with no record of when or why". The
-- installation has a sharper version of the same problem. Its primary key is
-- (tenant_id, client_id, device_id, canonical_name) and deliberately EXCLUDES
-- the version, so a software upgrade updates `version` and
-- `software_version_id` in place on the same row. A subject derived from
-- (device_id, version_uuid) would therefore change on EVERY update, closing
-- and reopening the finding even though the install path never moved. Measured
-- 2026-08-12: 490,733 rows, 0 soft-deleted, PK as above.
--
-- That same PK is what makes minting durable: one row per (device, title),
-- deletes are soft (deleted_at / deleted_reason), and version is an attribute
-- rather than part of the identity. The handle therefore survives version
-- upgrades, uninstall/reinstall and catalog re-normalization.
--
-- gen_random_uuid() is core in PostgreSQL 13+; the server is 16. pgcrypto is
-- not installed and is not needed.

-- This DOES rewrite the heap, and that is the measured-cheaper option.
--
-- gen_random_uuid() is volatile (pg_proc.provolatile = 'v'), so PostgreSQL
-- 11+'s fast-path ADD COLUMN ... DEFAULT does not apply and the table is
-- rewritten under ACCESS EXCLUSIVE. Verified on this server 2026-08-12: with
-- the volatile default the relfilenode changed and atthasmissing was false;
-- with a constant default it did not and atthasmissing was true.
--
-- The obvious remedy -- add the column nullable, mint in an UPDATE, then set
-- NOT NULL -- was written, rehearsed, and REJECTED on measurement. The ingest
-- runner applies each migration file in ONE transaction, and ALTER TABLE takes
-- ACCESS EXCLUSIVE at the first statement and holds it until commit. So the
-- "slow step without a lock" does not exist here: the UPDATE runs while the
-- exclusive lock is already held.
--
-- Rehearsed against production in rolled-back transactions, 2026-08-12,
-- 490,733 rows / 1,154 MB heap / 1,412 MB total:
--
--   one-liner rewrite ...................... 12.94 s
--   add nullable + UPDATE + SET NOT NULL ... 61.52 s  (UPDATE alone 58.39 s)
--
-- The split holds the same lock 4.75x longer, exceeds the 30 s gunicorn worker
-- timeout, and leaves ~1.15 GB of dead tuples for autovacuum, where a rewrite
-- compacts and leaves none. Rewriting is both shorter and cleaner.
--
-- Deployment note: this blocks every reader of the table -- the software pages
-- and the classifier -- for ~13 s plus ~2 s for the unique index.
ALTER TABLE operations.software_installations_current
    ADD COLUMN IF NOT EXISTS installation_uuid uuid NOT NULL DEFAULT gen_random_uuid();

-- Unique, because this is an identity. Not the primary key: the natural key
-- above keeps its existing job, and repointing a 490k-row PK would rewrite
-- every referencing index for no gain.
--
-- `ADD CONSTRAINT` has no IF NOT EXISTS in PostgreSQL. The runner records
-- applied versions and each file runs in its own transaction, so a re-run
-- cannot happen after success and a failure rolls the whole file back -- but
-- this is guarded anyway to match the idempotent style of 074-076.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_software_installations_current_uuid'
    ) THEN
        ALTER TABLE operations.software_installations_current
            ADD CONSTRAINT uq_software_installations_current_uuid
            UNIQUE (installation_uuid);
    END IF;
END
$$;

-- No grant changes. A new column inherits the table's privileges and no new
-- relation is created here, so the read-model revoke rule in
-- operations/AGENTS.md does not apply.
