"""Additive common-findings expansion and dormant tenant guard (PLAN-003 M1).

PLAN-003 converges entity and admin findings on ``operations.findings`` with one
relationship mechanism. This migration only adds the structures that conversion
needs; nothing calls or populates them yet, and existing readers and writers keep
working unchanged:

* ``findings`` gains ``subject_ref`` (structured non-UUID subjects),
  ``condition_namespace`` (entity/admin identity metadata, default entity),
  ``condition_identity`` and ``episode_key``. Active-key uniqueness and the
  NOT NULL ``subject_id`` stay as they are until the M2-M4 cutover.
* ``finding_types.allowed_subject_kinds`` is added unseeded and unenforced.
* Empty tables: ``finding_legacy_refs`` and ``finding_relationships`` (tenant
  scoped, composite tenant FKs to findings, read-only to runtime roles) and the
  global ``finding_action_registry``, ``finding_relationship_rules`` and
  ``finding_relationship_rule_actions``.
* ``finding_state`` and ``source_action_requests`` get composite
  (tenant_id, finding_id) FKs, ``NOT VALID``: new rows are checked now and
  existing rows are validated by the M2 preflight.
* The tenant guard: one transaction-scoped advisory key per tenant with shared
  and exclusive modes. Callers choose the strongest mode they need before any
  row lock; a shared holder cannot upgrade. Protected writers will assert the
  mode they require. PLAN-004 reuses the same helper.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_index i
          JOIN pg_class c ON c.oid = i.indexrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'operations' AND c.relname = 'uq_findings_tenant_id'
           AND i.indisvalid) THEN
        RAISE EXCEPTION 'operations.uq_findings_tenant_id is missing or invalid; '
                        'drop it and re-run migration 0362';
    END IF;
END
$$;

ALTER TABLE operations.findings
    ADD COLUMN subject_ref jsonb NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT findings_subject_ref_object CHECK (jsonb_typeof(subject_ref) = 'object'),
    ADD COLUMN condition_namespace varchar(16) NOT NULL DEFAULT 'entity'
        CONSTRAINT findings_condition_namespace_known
        CHECK (condition_namespace IN ('entity', 'admin')),
    ADD COLUMN condition_identity text NULL,
    ADD COLUMN episode_key text NULL
        CONSTRAINT findings_episode_key_nonempty CHECK (episode_key IS NULL OR episode_key > '');
CREATE UNIQUE INDEX uq_findings_active_episode_key
    ON operations.findings (tenant_id, episode_key)
    WHERE episode_key IS NOT NULL
      AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');

ALTER TABLE operations.finding_types ADD COLUMN allowed_subject_kinds text[] NULL;
UPDATE operations.change_history_registry
   SET recorded_columns = recorded_columns || ARRAY['allowed_subject_kinds']::text[]
 WHERE table_name = 'finding_types'
   AND NOT ('allowed_subject_kinds' = ANY (recorded_columns));

ALTER TABLE operations.finding_state
    ADD CONSTRAINT finding_state_tenant_finding_fkey
    FOREIGN KEY (tenant_id, finding_id) REFERENCES operations.findings (tenant_id, id)
    ON DELETE CASCADE NOT VALID;
ALTER TABLE operations.source_action_requests
    ADD CONSTRAINT source_action_requests_tenant_finding_fkey
    FOREIGN KEY (tenant_id, finding_id) REFERENCES operations.findings (tenant_id, id)
    NOT VALID;

CREATE TABLE operations.finding_legacy_refs (
    tenant_id bigint NOT NULL,
    legacy_kind text NOT NULL CHECK (legacy_kind ~ '^[a-z][a-z0-9_]{0,63}$'),
    legacy_id text NOT NULL CHECK (legacy_id > ''),
    finding_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, legacy_kind, legacy_id),
    FOREIGN KEY (tenant_id, finding_id) REFERENCES operations.findings (tenant_id, id)
);
CREATE INDEX idx_finding_legacy_refs_finding
    ON operations.finding_legacy_refs (tenant_id, finding_id);

CREATE TABLE operations.finding_action_registry (
    action_key text PRIMARY KEY CHECK (action_key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
    kind text NOT NULL CHECK (kind IN ('ui_action', 'system_effect')),
    description text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE operations.finding_relationship_rules (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_type_id smallint NOT NULL REFERENCES operations.finding_types (id),
    child_type_id smallint NOT NULL REFERENCES operations.finding_types (id),
    kind text NOT NULL CHECK (kind IN ('covers', 'requires')),
    scope_matcher text NOT NULL CHECK (scope_matcher ~ '^[a-z][a-z0-9_]{0,63}$'),
    required_match_fields text[] NOT NULL DEFAULT '{}'::text[],
    parent_satisfaction text NOT NULL CHECK (parent_satisfaction ~ '^[a-z][a-z0-9_]{0,63}$'),
    enabled boolean NOT NULL DEFAULT false,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    provenance text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (parent_type_id, child_type_id, kind, scope_matcher)
);

CREATE TABLE operations.finding_relationship_rule_actions (
    rule_id bigint NOT NULL REFERENCES operations.finding_relationship_rules (id)
        ON DELETE CASCADE,
    action_key text NOT NULL REFERENCES operations.finding_action_registry (action_key),
    PRIMARY KEY (rule_id, action_key)
);

CREATE TABLE operations.finding_relationships (
    tenant_id bigint NOT NULL,
    rule_id bigint NOT NULL REFERENCES operations.finding_relationship_rules (id),
    parent_id uuid NOT NULL,
    child_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('covers', 'requires')),
    scope_fingerprint text NOT NULL,
    is_valid boolean NOT NULL DEFAULT true,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, rule_id, parent_id, child_id),
    CHECK (parent_id <> child_id),
    FOREIGN KEY (tenant_id, parent_id) REFERENCES operations.findings (tenant_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, child_id) REFERENCES operations.findings (tenant_id, id)
        ON DELETE CASCADE
);
CREATE INDEX idx_finding_relationships_child
    ON operations.finding_relationships (tenant_id, child_id);

ALTER TABLE operations.finding_legacy_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.finding_legacy_refs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.finding_legacy_refs FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
ALTER TABLE operations.finding_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.finding_relationships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.finding_relationships FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);

REVOKE ALL ON operations.finding_legacy_refs, operations.finding_relationships,
              operations.finding_action_registry, operations.finding_relationship_rules,
              operations.finding_relationship_rule_actions
    FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.finding_legacy_refs, operations.finding_relationships,
       operations.finding_action_registry, operations.finding_relationship_rules,
       operations.finding_relationship_rule_actions
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT
    ON operations.finding_legacy_refs, operations.finding_relationships,
       operations.finding_action_registry, operations.finding_relationship_rules,
       operations.finding_relationship_rule_actions
    TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES
    ('finding_legacy_refs', 'exempt',
     'immutable alias map written once by the findings conversion',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('finding_relationships', 'exempt',
     'derived by the relationship projector from findings and rules; rebuildable',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('finding_action_registry', 'covered', 'platform or operator decision or state',
     ARRAY['action_key', 'kind', 'description']::text[], '{}'::text[],
     ARRAY['action_key']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('finding_relationship_rules', 'covered', 'platform or operator decision or state',
     ARRAY['id', 'parent_type_id', 'child_type_id', 'kind', 'scope_matcher',
           'required_match_fields', 'parent_satisfaction', 'enabled', 'version',
           'provenance']::text[], '{}'::text[],
     ARRAY['id']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger'),
    ('finding_relationship_rule_actions', 'covered', 'platform or operator decision or state',
     ARRAY['rule_id', 'action_key']::text[], '{}'::text[],
     ARRAY['rule_id', 'action_key']::text[], NULL, NULL, NULL, NULL, TRUE, 'trigger')
ON CONFLICT (table_name) DO NOTHING;
SELECT operations.enable_change_history(t)
  FROM unnest(ARRAY['finding_action_registry', 'finding_relationship_rules',
                    'finding_relationship_rule_actions']) AS t;

-- One advisory key per tenant, in a namespace disjoint from the Jobs keys.
CREATE FUNCTION operations.tenant_guard_key(p_tenant bigint) RETURNS bigint
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $fn$
    SELECT hashtextextended('operations.tenant_guard:' || p_tenant::text, 0)
$fn$;

-- The mode this backend holds for the tenant: 'exclusive', 'shared' or NULL.
CREATE FUNCTION operations.tenant_guard_mode(p_tenant bigint) RETURNS text
LANGUAGE sql STABLE
SET search_path = pg_catalog, operations
AS $fn$
    SELECT CASE WHEN bool_or(l.mode = 'ExclusiveLock') THEN 'exclusive'
                WHEN bool_or(l.mode = 'ShareLock') THEN 'shared' END
      FROM pg_locks l
      CROSS JOIN LATERAL (SELECT operations.tenant_guard_key(p_tenant) AS k) key
     WHERE l.locktype = 'advisory' AND l.pid = pg_backend_pid() AND l.granted
       AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
       AND l.objsubid = 1
       AND l.classid::bigint = ((key.k >> 32) & 4294967295)
       AND l.objid::bigint = (key.k & 4294967295)
$fn$;

-- Takes the tenant guard for the rest of the transaction. Call it at the outer
-- transaction boundary, before any row lock, with the strongest mode needed.
CREATE FUNCTION operations.acquire_tenant_guard(p_tenant bigint, p_mode text) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_held text;
BEGIN
    IF p_mode IS NULL OR p_mode NOT IN ('shared', 'exclusive') THEN
        RAISE EXCEPTION 'tenant guard mode must be shared or exclusive, not %', p_mode;
    END IF;
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'the tenant guard needs the session tenant';
    END IF;
    v_held := operations.tenant_guard_mode(p_tenant);
    IF v_held = 'shared' AND p_mode = 'exclusive' THEN
        RAISE EXCEPTION 'tenant guard is held shared and cannot be upgraded; '
                        'retry with exclusive mode at the outer transaction boundary';
    END IF;
    IF v_held IS NOT NULL THEN
        RETURN;
    END IF;
    IF p_mode = 'exclusive' THEN
        PERFORM pg_advisory_xact_lock(operations.tenant_guard_key(p_tenant));
    ELSE
        PERFORM pg_advisory_xact_lock_shared(operations.tenant_guard_key(p_tenant));
    END IF;
END
$fn$;

-- Raises unless this transaction already holds the guard in the required mode.
-- Protected writers call this; they never acquire the guard themselves.
CREATE FUNCTION operations.assert_tenant_guard(p_tenant bigint, p_mode text) RETURNS void
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_held text := operations.tenant_guard_mode(p_tenant);
BEGIN
    IF p_mode IS NULL OR p_mode NOT IN ('shared', 'exclusive') THEN
        RAISE EXCEPTION 'tenant guard mode must be shared or exclusive, not %', p_mode;
    END IF;
    IF v_held IS NULL OR (p_mode = 'exclusive' AND v_held <> 'exclusive') THEN
        RAISE EXCEPTION 'tenant % guard must be held in % mode (held: %)',
                        p_tenant, p_mode, coalesce(v_held, 'none');
    END IF;
END
$fn$;

REVOKE ALL ON FUNCTION operations.tenant_guard_key(bigint),
                       operations.tenant_guard_mode(bigint),
                       operations.acquire_tenant_guard(bigint, text),
                       operations.assert_tenant_guard(bigint, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.tenant_guard_key(bigint),
                          operations.tenant_guard_mode(bigint),
                          operations.acquire_tenant_guard(bigint, text),
                          operations.assert_tenant_guard(bigint, text)
    TO operations_app, ninja_ingest;
"""

REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS operations.assert_tenant_guard(bigint, text);
DROP FUNCTION IF EXISTS operations.acquire_tenant_guard(bigint, text);
DROP FUNCTION IF EXISTS operations.tenant_guard_mode(bigint);
DROP FUNCTION IF EXISTS operations.tenant_guard_key(bigint);
DROP TABLE IF EXISTS operations.finding_relationship_rule_actions_change_history;
DROP TABLE IF EXISTS operations.finding_relationship_rules_change_history;
DROP TABLE IF EXISTS operations.finding_action_registry_change_history;
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('finding_legacy_refs', 'finding_relationships', 'finding_action_registry',
                      'finding_relationship_rules', 'finding_relationship_rule_actions');
DROP TABLE IF EXISTS operations.finding_relationships;
DROP TABLE IF EXISTS operations.finding_relationship_rule_actions;
DROP TABLE IF EXISTS operations.finding_relationship_rules;
DROP TABLE IF EXISTS operations.finding_action_registry;
DROP TABLE IF EXISTS operations.finding_legacy_refs;
ALTER TABLE operations.source_action_requests
    DROP CONSTRAINT IF EXISTS source_action_requests_tenant_finding_fkey;
ALTER TABLE operations.finding_state DROP CONSTRAINT IF EXISTS finding_state_tenant_finding_fkey;
UPDATE operations.change_history_registry
   SET recorded_columns = array_remove(recorded_columns, 'allowed_subject_kinds')
 WHERE table_name = 'finding_types';
ALTER TABLE operations.finding_types DROP COLUMN IF EXISTS allowed_subject_kinds;
DROP INDEX IF EXISTS operations.uq_findings_active_episode_key;
ALTER TABLE operations.findings
    DROP COLUMN IF EXISTS episode_key,
    DROP COLUMN IF EXISTS condition_identity,
    DROP COLUMN IF EXISTS condition_namespace,
    DROP COLUMN IF EXISTS subject_ref;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0362_findings_tenant_id_unique"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
