-- 096: capability -> finding registry mapping and LOLRMM corpus storage.
--
-- Capability-to-finding is data, not a Python map. The finding names retain
-- their established public vocabulary (`unauthorized_av`) while the capability
-- vocabulary uses the more accurate `endpoint_security`.

ALTER TABLE catalog.capability
    ADD COLUMN IF NOT EXISTS unauthorized_finding_type text NOT NULL DEFAULT '';

UPDATE catalog.capability
   SET unauthorized_finding_type = CASE key
       WHEN 'endpoint_security' THEN 'unauthorized_av'
       WHEN 'rmm' THEN 'unauthorized_rmm'
       WHEN 'remote_access' THEN 'unauthorized_remote_access'
       ELSE unauthorized_finding_type
   END
 WHERE unauthorized_finding_type = '';

ALTER TABLE catalog.capability
    DROP CONSTRAINT IF EXISTS ck_capability_finding_type_present;
ALTER TABLE catalog.capability
    ADD CONSTRAINT ck_capability_finding_type_present
    CHECK (unauthorized_finding_type <> '');

INSERT INTO catalog.capability_source
    (source_key, authority_class, may_alert, managed_by, notes)
VALUES
    ('lolrmm_candidate', 'community_tag', FALSE, 'migration',
     'LOLRMM normalized-name collision. Candidate only; never alerts.')
ON CONFLICT (source_key) DO NOTHING;

-- LOLRMM is a vetted capability corpus, not a local product identity source.
-- It holds the normalized tool name and its RMM/RAT category. The projector
-- below only emits alertable evidence for a one-to-one exact normalized local
-- product match; collisions become candidates and cannot alert.
CREATE TABLE IF NOT EXISTS catalog.lolrmm_tool (
    normalized_name text PRIMARY KEY,
    display_name    text NOT NULL,
    capability      text NOT NULL REFERENCES catalog.capability(key) ON DELETE RESTRICT,
    source_ref      text NOT NULL,
    raw_record      jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    withdrawn_at    timestamptz,
    withdrawn_reason text NOT NULL DEFAULT '',
    CONSTRAINT ck_lolrmm_tool_withdrawn_reason CHECK (
        (withdrawn_at IS NULL AND withdrawn_reason = '')
        OR (withdrawn_at IS NOT NULL AND withdrawn_reason <> '')
    )
);

CREATE INDEX IF NOT EXISTS idx_lolrmm_tool_current
    ON catalog.lolrmm_tool (capability)
    WHERE withdrawn_at IS NULL;

REVOKE ALL ON catalog.lolrmm_tool FROM PUBLIC;
GRANT SELECT, INSERT ON catalog.lolrmm_tool TO ninja_ingest;
GRANT UPDATE (display_name, capability, source_ref, raw_record, updated_at,
              withdrawn_at, withdrawn_reason)
    ON catalog.lolrmm_tool TO ninja_ingest;
GRANT SELECT ON catalog.lolrmm_tool
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON TABLE catalog.lolrmm_tool IS
    'LOLRMM corpus records. A local product is alertable only after an exact one-to-one normalized title match.';
