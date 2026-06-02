-- =============================================================================
-- 002_patches.sql
-- Creates ninja_patches schema. Sources both
-- /v2/queries/os-patch-installs (INSTALLED, FAILED) and
-- /v2/queries/os-patches (PENDING, APPROVED, REJECTED) into one fact
-- table, distinguished by `status`.
--
-- SCD-2 pattern: a (device, patch) pair's status changes over time
-- (e.g. PENDING → APPROVED → INSTALLED). We insert a new row only when
-- the content hash changes; otherwise we update last_observed_at on the
-- existing row. This gives us the full state-transition history per
-- (device, patch) pair without snapshot bloat.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ninja_patches;

CREATE TABLE IF NOT EXISTS ninja_patches.patch_facts (
    id                  bigserial PRIMARY KEY,
    device_id           integer NOT NULL REFERENCES ninja_core.devices(id),
    patch_uid           uuid NOT NULL,            -- Ninja's patch `id`
    kb_number           text,
    name                text,
    status              text NOT NULL,            -- INSTALLED | FAILED | PENDING | APPROVED | REJECTED
    severity            text,
    type                text,
    installed_at        timestamptz,              -- from Ninja, for INSTALLED/FAILED
    ninja_observed_at   timestamptz,              -- Ninja's `timestamp` field (latest seen)
    content_hash        text NOT NULL,            -- hash(status, installed_at, severity, type, kb, name)
    first_observed_at   timestamptz NOT NULL,     -- our snapshot when this state first appeared
    last_observed_at    timestamptz NOT NULL,     -- our snapshot when we last saw this state
    data                jsonb NOT NULL,
    UNIQUE (device_id, patch_uid, content_hash)
);

CREATE INDEX IF NOT EXISTS patch_facts_device_idx
    ON ninja_patches.patch_facts (device_id);
CREATE INDEX IF NOT EXISTS patch_facts_status_idx
    ON ninja_patches.patch_facts (status);
CREATE INDEX IF NOT EXISTS patch_facts_first_observed_idx
    ON ninja_patches.patch_facts (first_observed_at);
CREATE INDEX IF NOT EXISTS patch_facts_last_observed_idx
    ON ninja_patches.patch_facts (last_observed_at);
CREATE INDEX IF NOT EXISTS patch_facts_installed_idx
    ON ninja_patches.patch_facts (installed_at)
    WHERE installed_at IS NOT NULL;
-- For "current state of patch X on device Y" lookups:
CREATE INDEX IF NOT EXISTS patch_facts_current_state_idx
    ON ninja_patches.patch_facts (device_id, patch_uid, last_observed_at DESC);
