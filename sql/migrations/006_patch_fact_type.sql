-- =============================================================================
-- 006_patch_fact_type.sql
-- Marks each patch_facts row with its source semantics:
--   patch_state     = /queries/os-patches
--   install_outcome = /queries/os-patch-installs
--
-- Existing rows are backfilled from status because historical ingest did not
-- persist endpoint/source metadata.
-- =============================================================================

ALTER TABLE ninja_patches.patch_facts
    ADD COLUMN IF NOT EXISTS fact_type text;

UPDATE ninja_patches.patch_facts
SET fact_type = CASE
    WHEN status IN ('INSTALLED', 'FAILED') THEN 'install_outcome'
    ELSE 'patch_state'
END
WHERE fact_type IS NULL;

ALTER TABLE ninja_patches.patch_facts
    ALTER COLUMN fact_type SET NOT NULL,
    ALTER COLUMN fact_type SET DEFAULT 'patch_state';

CREATE INDEX IF NOT EXISTS patch_facts_fact_type_idx
    ON ninja_patches.patch_facts (fact_type);
