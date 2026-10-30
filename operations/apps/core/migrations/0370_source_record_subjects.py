"""Managed source-record subjects and independent assessment (PLAN-004 R4 Stage A).

Every received source record becomes a durable ``source_record`` subject at
intake, independent of Computer identity, class or client mapping (ADR-0049).
Additive and compatible with the deployed writers: nothing here changes how
observations, links or findings are written today.

* ``source_record_subjects``: durable UUID per tenant/source-instance natural
  key, current observation pointer, record role (explicit ``unclassified``
  fallback), presence, input version and association version. Intake-error
  subjects are keyed by source run and item ordinal instead.
* ``source_record_tenant_state``: one transactional ``input_generation`` per
  tenant.
* ``source_record_lookup_keys``: indexed normalized name/serial/VM UUID/MAC keys
  per subject; no bucket table and no pairwise cross-product.
* ``source_record_assessment_queue``: coalesced dirty revisions. Completion
  records the revision it processed, so a newer enqueue survives. Registered in
  ``queue_registry`` so the platform-health evaluator watches its depth and age.
* ``source_record_assessment_current``: one current result per target, rule and
  dimension, with the rule revision, target version and tenant generation it
  was computed from.

Amendment R4-1 (design §3/§7.2): intake takes no tenant guard. A trigger on
``entity_observation_current`` admits the subject, replaces its lookup keys and
enqueues it and its key neighbors inside the observation-write transaction. A
deferred constraint trigger on the subjects advances the tenant generation once
per transaction, at commit. Publication holds the exclusive guard and a share
lock on the generation row (``ingest/source_records.py``).

The new native finding types are not alertable and accept only native subjects.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
-- Block observation writes for the rest of this migration so the backfill and
-- the admission triggers see the same rows. Bounded: a long ingest transaction
-- fails this startup visibly instead of stalling it (0.131.0).
SET LOCAL lock_timeout = '120s';
LOCK TABLE operations.entity_observation_current IN SHARE ROW EXCLUSIVE MODE;
SET LOCAL lock_timeout = 0;

CREATE TABLE operations.source_record_tenant_state (
    tenant_id bigint PRIMARY KEY REFERENCES operations.tenants (id),
    input_generation bigint NOT NULL DEFAULT 0 CHECK (input_generation >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE operations.source_record_subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES operations.tenants (id),
    subject_kind text NOT NULL DEFAULT 'record'
        CHECK (subject_kind IN ('record', 'intake_error')),
    source_instance_id uuid NOT NULL,
    external_namespace varchar(120),
    parent_external_namespace varchar(120),
    parent_external_id text,
    external_id text,
    key_version smallint NOT NULL DEFAULT 1 CHECK (key_version > 0),
    source_run_id uuid,
    item_ordinal integer,
    intake_error text NOT NULL DEFAULT '',
    observation_id uuid,
    platform varchar(80) NOT NULL DEFAULT '',
    entity_type varchar(80) NOT NULL DEFAULT '',
    record_role text NOT NULL DEFAULT 'unclassified',
    presence text NOT NULL DEFAULT 'present' CHECK (presence IN ('present', 'withdrawn')),
    input_version bigint NOT NULL DEFAULT 1 CHECK (input_version > 0),
    association_version bigint NOT NULL DEFAULT 0 CHECK (association_version >= 0),
    admitted_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, source_instance_id)
        REFERENCES operations.source_instances (tenant_id, id),
    CONSTRAINT source_record_subjects_identity CHECK (
        (subject_kind = 'record'
         AND external_namespace > '' AND external_id > ''
         AND parent_external_namespace IS NOT NULL AND parent_external_id IS NOT NULL
         AND source_run_id IS NULL AND item_ordinal IS NULL)
        OR (subject_kind = 'intake_error'
            AND source_run_id IS NOT NULL AND item_ordinal IS NOT NULL
            AND intake_error > ''))
);
CREATE UNIQUE INDEX uq_source_record_subjects_natural
    ON operations.source_record_subjects (
        tenant_id, source_instance_id, external_namespace,
        parent_external_namespace, parent_external_id, external_id)
    WHERE subject_kind = 'record';
CREATE UNIQUE INDEX uq_source_record_subjects_intake_error
    ON operations.source_record_subjects (tenant_id, source_run_id, item_ordinal)
    WHERE subject_kind = 'intake_error';
CREATE INDEX idx_source_record_subjects_observation
    ON operations.source_record_subjects (tenant_id, observation_id);

CREATE TABLE operations.source_record_lookup_keys (
    tenant_id bigint NOT NULL,
    subject_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    record_role text NOT NULL,
    key_family text NOT NULL CHECK (key_family IN ('name', 'serial', 'vm_uuid', 'mac')),
    normalization_version smallint NOT NULL DEFAULT 1,
    normalized_value text NOT NULL CHECK (normalized_value > ''),
    PRIMARY KEY (tenant_id, subject_id, key_family, normalized_value),
    FOREIGN KEY (tenant_id, subject_id)
        REFERENCES operations.source_record_subjects (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_source_record_lookup_keys_value
    ON operations.source_record_lookup_keys (tenant_id, key_family, normalized_value);

CREATE TABLE operations.source_record_assessment_queue (
    tenant_id bigint NOT NULL REFERENCES operations.tenants (id),
    target_kind text NOT NULL CHECK (target_kind IN ('source_record', 'case_key')),
    target_id uuid NOT NULL,
    target_key jsonb NOT NULL DEFAULT '{}'::jsonb,
    dirty_revision bigint NOT NULL DEFAULT 1,
    processed_revision bigint NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),
    queued_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0,
    last_error text NOT NULL DEFAULT '',
    processed_at timestamptz,
    PRIMARY KEY (tenant_id, target_kind, target_id),
    CHECK (processed_revision <= dirty_revision)
);
CREATE INDEX idx_source_record_assessment_queue_pending
    ON operations.source_record_assessment_queue (tenant_id, queued_at)
    WHERE status = 'pending';

CREATE TABLE operations.source_record_assessment_current (
    tenant_id bigint NOT NULL REFERENCES operations.tenants (id),
    target_kind text NOT NULL CHECK (target_kind IN ('source_record', 'source_record_case')),
    target_id uuid NOT NULL,
    rule_key text NOT NULL CHECK (rule_key ~ '^[a-z][a-z0-9_.]{0,63}$'),
    dimension text NOT NULL DEFAULT '',
    rule_revision integer NOT NULL CHECK (rule_revision > 0),
    target_version bigint NOT NULL,
    input_generation bigint NOT NULL,
    result text NOT NULL
        CHECK (result IN ('supported', 'contradicted', 'unknown', 'not_applicable')),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    missing_facts text[] NOT NULL DEFAULT '{}'::text[],
    work_owner text NOT NULL DEFAULT '',
    finding_id uuid,
    assessed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, target_kind, target_id, rule_key, dimension),
    FOREIGN KEY (tenant_id, finding_id) REFERENCES operations.findings (tenant_id, id)
);

-- Tenant RLS on every new table; runtime roles read, protected paths write.
DO $rls$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['source_record_tenant_state', 'source_record_subjects',
                             'source_record_lookup_keys', 'source_record_assessment_queue',
                             'source_record_assessment_current'] LOOP
        EXECUTE format('ALTER TABLE operations.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE operations.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON operations.%I
               USING (tenant_id = nullif(current_setting(''operations.tenant_id'', true), '''')::bigint)
               WITH CHECK (tenant_id = nullif(current_setting(''operations.tenant_id'', true), '''')::bigint)',
            t);
        EXECUTE format('REVOKE ALL ON operations.%I FROM PUBLIC', t);
        EXECUTE format(
            'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.%I
               FROM operations_app, ninja_ingest, operations_readonly', t);
        EXECUTE format(
            'GRANT SELECT ON operations.%I TO operations_app, operations_readonly, ninja_ingest', t);
    END LOOP;
END
$rls$;
-- The assessment worker claims and completes queue rows.
GRANT UPDATE (status, processed_revision, attempts, last_error, processed_at)
    ON operations.source_record_assessment_queue TO ninja_ingest;

-- Writes to derived assessments need the exclusive guard and current findings
-- contract, exactly like findings and condition assessments (0365).
CREATE TRIGGER assert_findings_writer BEFORE INSERT OR UPDATE OR DELETE
    ON operations.source_record_assessment_current FOR EACH STATEMENT
    EXECUTE FUNCTION operations.assert_findings_writer();
CREATE TRIGGER assert_findings_row_tenant BEFORE INSERT OR UPDATE OR DELETE
    ON operations.source_record_assessment_current FOR EACH ROW
    EXECUTE FUNCTION operations.assert_findings_row_tenant();

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES
    ('source_record_tenant_state', 'exempt', 'transactional input generation counter',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_record_subjects', 'exempt',
     'admission anchor maintained from observations; observation history is ADR-0045 authority',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_record_lookup_keys', 'exempt', 'derived from current observations; rebuildable',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_record_assessment_queue', 'exempt', 'work queue; leased and coalesced',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_record_assessment_current', 'exempt',
     'derived current rule results; findings carry the history',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL)
ON CONFLICT (table_name) DO NOTHING;

-- Record role from the source entity type. Unknown types fall back to
-- 'unclassified' explicitly; role-dependent rules report that as unknown.
CREATE FUNCTION operations.source_record_role(p_entity_type text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $fn$
    SELECT CASE
        WHEN p_entity_type LIKE 'agent.%' THEN 'endpoint_agent'
        WHEN p_entity_type = 'vm.guest' THEN 'virtual_machine'
        WHEN p_entity_type = 'vm.host' THEN 'virtual_host'
        WHEN p_entity_type = 'network.device' THEN 'network_device'
        WHEN p_entity_type = 'monitor.target' THEN 'monitor_target'
        WHEN p_entity_type = 'cmdb.asset' THEN 'documentation'
        WHEN p_entity_type = 'org' THEN 'source_group'
        ELSE 'unclassified'
    END
$fn$;

-- Roles whose records describe a Computer and take part in identity comparison.
-- Documentation names and typed-in serials are not endpoint identity evidence.
CREATE FUNCTION operations.source_record_role_compares_identity(p_role text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $fn$
    SELECT p_role IN ('endpoint_agent', 'virtual_machine', 'virtual_host')
$fn$;

-- Normalized lookup keys of one record (normalization version 1). Mirrors
-- ingest.normalize: short lowercase hostname without trailing parentheses and
-- quote/space characters; serials of four or more characters that are not one
-- repeated character and not an enabled rejection; non-zero VM UUIDs; MACs as
-- normalized by the connectors. Roaming records contribute no hardware keys.
CREATE FUNCTION operations.source_record_keys(
    p_tenant bigint, p_source_instance uuid, p_external_id text,
    p_role text, p_data jsonb
) RETURNS TABLE (key_family text, normalized_value text)
LANGUAGE sql STABLE
SET search_path = pg_catalog, operations
AS $fn$
    WITH roaming AS (
        SELECT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = p_tenant
                          AND rr.source_instance_id = p_source_instance
                          AND rr.external_id = p_external_id) AS is_roaming
    ), base AS (
        SELECT p_data ->> 'hostname' AS host,
               lower(btrim(p_data ->> 'serial_number')) AS serial,
               lower(btrim(p_data ->> 'vm_uuid')) AS vm_uuid
    )
    SELECT 'name', n.v
      FROM base, LATERAL (SELECT regexp_replace(
                 lower(btrim(split_part(regexp_replace(base.host, '\s*\(.*?\)\s*$', ''), '.', 1))),
                 '[\s''`‘’]', '', 'g') AS v) n
     WHERE operations.source_record_role_compares_identity(p_role) AND n.v > ''
    UNION
    SELECT 'serial', base.serial
      FROM base, roaming
     WHERE operations.source_record_role_compares_identity(p_role) AND NOT roaming.is_roaming
       AND length(base.serial) >= 4
       AND base.serial !~ '^(.)\1*$'
       AND NOT EXISTS (SELECT 1 FROM operations.identity_value_rejections r
                        WHERE r.value_kind = 'serial' AND r.enabled
                          AND r.normalized_value = base.serial)
    UNION
    SELECT 'vm_uuid', base.vm_uuid
      FROM base, roaming
     WHERE operations.source_record_role_compares_identity(p_role) AND NOT roaming.is_roaming
       AND base.vm_uuid > '' AND base.vm_uuid !~ '^[0-]+$'
    UNION
    SELECT 'mac', lower(m.v)
      FROM jsonb_array_elements_text(
               CASE WHEN jsonb_typeof(p_data -> 'macs') = 'array'
                    THEN p_data -> 'macs' ELSE '[]'::jsonb END) m(v)
     WHERE operations.source_record_role_compares_identity(p_role)
       AND lower(m.v) ~ '^[0-9a-f]{2}(:[0-9a-f]{2}){5}$'
       AND lower(m.v) NOT IN ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff', '02:00:4c:4f:4f:50')
$fn$;

-- Coalesced enqueue: a pending row gains a newer dirty revision; completion
-- only acknowledges the revision it read.
CREATE FUNCTION operations.source_record_enqueue(
    p_tenant bigint, p_kind text, p_target uuid, p_key jsonb DEFAULT '{}'::jsonb
) RETURNS void
LANGUAGE sql
SET search_path = pg_catalog, operations
AS $fn$
    INSERT INTO operations.source_record_assessment_queue AS q
        (tenant_id, target_kind, target_id, target_key)
    VALUES (p_tenant, p_kind, p_target, coalesce(p_key, '{}'::jsonb))
    ON CONFLICT (tenant_id, target_kind, target_id) DO UPDATE
       SET dirty_revision = q.dirty_revision + 1,
           status = 'pending',
           queued_at = CASE WHEN q.status = 'pending' THEN q.queued_at ELSE now() END
$fn$;

-- Deterministic id of one duplicate-review key scope (Stage C cases).
CREATE FUNCTION operations.source_record_case_key_id(
    p_tenant bigint, p_source_instance uuid, p_family text, p_value text
) RETURNS uuid
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $fn$
    SELECT md5('source_record_case_key:1:' || p_tenant || ':' || p_source_instance || ':'
               || p_family || ':' || p_value)::uuid
$fn$;

-- Enqueue the subjects and case keys that share any of the given keys. Large
-- buckets enqueue only their case key: one subject joining a common MAC or name
-- does not change any other subject's candidate Computers.
CREATE FUNCTION operations.source_record_enqueue_neighbors(
    p_tenant bigint, p_subject uuid, p_source_instance uuid,
    p_families text[], p_values text[]
) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    k record;
BEGIN
    FOR k IN SELECT DISTINCT f, v FROM unnest(p_families, p_values) AS u(f, v) LOOP
        IF k.f <> 'name' THEN
            PERFORM operations.source_record_enqueue(
                p_tenant, 'case_key',
                operations.source_record_case_key_id(p_tenant, p_source_instance, k.f, k.v),
                jsonb_build_object('source_instance_id', p_source_instance,
                                   'key_family', k.f, 'normalized_value', k.v));
        END IF;
        IF (SELECT count(*) FROM (SELECT 1 FROM operations.source_record_lookup_keys lk
                                   WHERE lk.tenant_id = p_tenant AND lk.key_family = k.f
                                     AND lk.normalized_value = k.v LIMIT 201) b) <= 200 THEN
            PERFORM operations.source_record_enqueue(p_tenant, 'source_record', lk.subject_id)
               FROM operations.source_record_lookup_keys lk
              WHERE lk.tenant_id = p_tenant AND lk.key_family = k.f
                AND lk.normalized_value = k.v AND lk.subject_id <> p_subject;
        END IF;
    END LOOP;
END
$fn$;

-- Admission inside the observation-write transaction (amendment R4-1). Runs for
-- every new observation and every decision-relevant change; a failure rolls the
-- observation write back.
CREATE FUNCTION operations.source_record_admit_observation() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_role text := operations.source_record_role(NEW.entity_type);
    v_subject uuid;
    v_old_f text[];
    v_old_v text[];
    v_new_f text[];
    v_new_v text[];
BEGIN
    INSERT INTO operations.source_record_subjects AS s (
        tenant_id, source_instance_id, external_namespace, parent_external_namespace,
        parent_external_id, external_id, observation_id, platform, entity_type,
        record_role, presence)
    VALUES (NEW.tenant_id, NEW.source_instance_id, NEW.external_namespace,
            NEW.parent_external_namespace, NEW.parent_external_id, NEW.external_id,
            NEW.observation_id, NEW.platform, NEW.entity_type, v_role,
            CASE WHEN NEW.active THEN 'present' ELSE 'withdrawn' END)
    ON CONFLICT (tenant_id, source_instance_id, external_namespace,
                 parent_external_namespace, parent_external_id, external_id)
        WHERE subject_kind = 'record'
    DO UPDATE SET observation_id = EXCLUDED.observation_id,
                  platform = EXCLUDED.platform,
                  entity_type = EXCLUDED.entity_type,
                  record_role = EXCLUDED.record_role,
                  presence = EXCLUDED.presence,
                  input_version = s.input_version + 1,
                  updated_at = now()
    RETURNING id INTO v_subject;

    SELECT coalesce(array_agg(key_family), '{}'), coalesce(array_agg(normalized_value), '{}')
      INTO v_old_f, v_old_v
      FROM operations.source_record_lookup_keys
     WHERE tenant_id = NEW.tenant_id AND subject_id = v_subject;
    DELETE FROM operations.source_record_lookup_keys
     WHERE tenant_id = NEW.tenant_id AND subject_id = v_subject;
    INSERT INTO operations.source_record_lookup_keys (
        tenant_id, subject_id, source_instance_id, record_role, key_family, normalized_value)
    SELECT NEW.tenant_id, v_subject, NEW.source_instance_id, v_role, k.key_family, k.normalized_value
      FROM operations.source_record_keys(NEW.tenant_id, NEW.source_instance_id,
                                         NEW.external_id, v_role, NEW.canonical_data) k;
    SELECT coalesce(array_agg(key_family), '{}'), coalesce(array_agg(normalized_value), '{}')
      INTO v_new_f, v_new_v
      FROM operations.source_record_lookup_keys
     WHERE tenant_id = NEW.tenant_id AND subject_id = v_subject;

    PERFORM operations.source_record_enqueue(NEW.tenant_id, 'source_record', v_subject);
    PERFORM operations.source_record_enqueue_neighbors(
        NEW.tenant_id, v_subject, NEW.source_instance_id,
        v_old_f || v_new_f, v_old_v || v_new_v);
    RETURN NULL;
END
$fn$;

CREATE TRIGGER source_record_admit_insert
    AFTER INSERT ON operations.entity_observation_current
    FOR EACH ROW EXECUTE FUNCTION operations.source_record_admit_observation();
CREATE TRIGGER source_record_admit_update
    AFTER UPDATE ON operations.entity_observation_current
    FOR EACH ROW
    WHEN (OLD.material_hash IS DISTINCT FROM NEW.material_hash
          OR OLD.active IS DISTINCT FROM NEW.active
          OR OLD.device_id IS DISTINCT FROM NEW.device_id
          OR OLD.client_id IS DISTINCT FROM NEW.client_id
          OR OLD.entity_type IS DISTINCT FROM NEW.entity_type
          OR OLD.observation_id IS DISTINCT FROM NEW.observation_id)
    EXECUTE FUNCTION operations.source_record_admit_observation();

-- One generation step per tenant per transaction, at commit (amendment R4-1).
CREATE FUNCTION operations.source_record_advance_generation() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_flag text := 'operations.source_record_generation_' || NEW.tenant_id;
BEGIN
    IF current_setting(v_flag, true) = txid_current()::text THEN
        RETURN NULL;
    END IF;
    INSERT INTO operations.source_record_tenant_state AS t (tenant_id, input_generation)
    VALUES (NEW.tenant_id, 1)
    ON CONFLICT (tenant_id) DO UPDATE
       SET input_generation = t.input_generation + 1, updated_at = now();
    PERFORM set_config(v_flag, txid_current()::text, true);
    RETURN NULL;
END
$fn$;

CREATE CONSTRAINT TRIGGER source_record_advance_generation
    AFTER INSERT OR UPDATE ON operations.source_record_subjects
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION operations.source_record_advance_generation();

REVOKE ALL ON FUNCTION operations.source_record_role(text),
                       operations.source_record_role_compares_identity(text),
                       operations.source_record_keys(bigint, uuid, text, text, jsonb),
                       operations.source_record_enqueue(bigint, text, uuid, jsonb),
                       operations.source_record_case_key_id(bigint, uuid, text, text),
                       operations.source_record_enqueue_neighbors(bigint, uuid, uuid, text[], text[]),
                       operations.source_record_admit_observation(),
                       operations.source_record_advance_generation()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.source_record_role(text),
                          operations.source_record_role_compares_identity(text),
                          operations.source_record_case_key_id(bigint, uuid, text, text)
    TO operations_app, operations_readonly, ninja_ingest;

-- Backfill: every current observation is admitted now, with its keys, and the
-- whole set is queued for its first assessment.
INSERT INTO operations.source_record_subjects (
    tenant_id, source_instance_id, external_namespace, parent_external_namespace,
    parent_external_id, external_id, observation_id, platform, entity_type,
    record_role, presence)
SELECT o.tenant_id, o.source_instance_id, o.external_namespace, o.parent_external_namespace,
       o.parent_external_id, o.external_id, o.observation_id, o.platform, o.entity_type,
       operations.source_record_role(o.entity_type),
       CASE WHEN o.active THEN 'present' ELSE 'withdrawn' END
  FROM operations.entity_observation_current o
ON CONFLICT DO NOTHING;

INSERT INTO operations.source_record_lookup_keys (
    tenant_id, subject_id, source_instance_id, record_role, key_family, normalized_value)
SELECT s.tenant_id, s.id, s.source_instance_id, s.record_role, k.key_family, k.normalized_value
  FROM operations.source_record_subjects s
  JOIN operations.entity_observation_current o
    ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
 CROSS JOIN LATERAL operations.source_record_keys(
       s.tenant_id, s.source_instance_id, s.external_id, s.record_role, o.canonical_data) k
ON CONFLICT DO NOTHING;

INSERT INTO operations.source_record_tenant_state (tenant_id, input_generation)
SELECT id, 1 FROM operations.tenants
ON CONFLICT DO NOTHING;

INSERT INTO operations.source_record_assessment_queue (tenant_id, target_kind, target_id)
SELECT tenant_id, 'source_record', id FROM operations.source_record_subjects
ON CONFLICT DO NOTHING;

INSERT INTO operations.source_record_assessment_queue (tenant_id, target_kind, target_id, target_key)
SELECT k.tenant_id, 'case_key',
       operations.source_record_case_key_id(k.tenant_id, k.source_instance_id, k.key_family, k.normalized_value),
       jsonb_build_object('source_instance_id', k.source_instance_id,
                          'key_family', k.key_family, 'normalized_value', k.normalized_value)
  FROM operations.source_record_lookup_keys k
 WHERE k.key_family <> 'name'
 GROUP BY k.tenant_id, k.source_instance_id, k.key_family, k.normalized_value
HAVING count(*) > 1
ON CONFLICT DO NOTHING;

INSERT INTO operations.queue_registry (
    queue_key, queue_type, table_name, owner, enabled, max_pending_age_m,
    max_failure_count, max_depth, description)
VALUES ('source_record.assessment', 'processing', 'operations.source_record_assessment_queue',
        'source_record.assessment', true, 120, 10, 0,
        'Managed source-record assessment (PLAN-004); dirty records and duplicate-review keys')
ON CONFLICT (queue_key) DO NOTHING;

-- Native source-record finding types: UI-only, native subjects only (§4, §9.1).
INSERT INTO operations.finding_types (
    name, default_severity, finding_class, source_module, subject_scope,
    creates_device_exposure, auto_resolvable, suppressed_by_approval,
    concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
    description, display_name, issue_category, issue_group, sort_order,
    alertable, covered_by, cover_note, allowed_subject_kinds
) VALUES
    ('source_record_identity_review', 'critical', 'entity', 'source_record.assessment',
     'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
     'A source record is not attached to a Computer and its identifiers point to more than '
     'one Computer. Decide which Computer it belongs to.',
     'Source record matches several Computers', 'Inventory', 'Computer identity', 75,
     FALSE, '[]'::jsonb, '', ARRAY['source_record']),
    ('source_record_identifier_invalid', 'high', 'entity', 'source_record.assessment',
     'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
     'An unattached source record reports a placeholder or invalid identifier. Correct it '
     'at the source; the identifier is not used for matching meanwhile.',
     'Source record has an invalid identifier', 'Inventory', 'Source data', 76,
     FALSE, '[]'::jsonb, '', ARRAY['source_record']),
    ('source_record_duplicate_review', 'high', 'entity', 'source_record.assessment',
     'source_record_case', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
     'Several records of one source report the same hardware identifier and are not all '
     'attached to one Computer. Review whether they are duplicate entries.',
     'Possible duplicate source records', 'Inventory', 'Duplicate computers', 77,
     FALSE, '[]'::jsonb, '', ARRAY['source_record_case']),
    ('source_record_policy_incomplete', 'medium', 'entity', 'source_record.assessment',
     'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
     'Records of a source type have no record role, so role-dependent rules cannot run.',
     'Source record type has no role', 'Data collection', 'Collection and processing', 78,
     FALSE, '[]'::jsonb, '', ARRAY['source_record'])
ON CONFLICT (name) DO NOTHING;

INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (1, 'source-record-assess', 'replay_safe',
          'Source-record assessment reads local observations and keys and convergently '
          'updates local assessments and findings in short guarded transactions; queue rows '
          'acknowledge only the revision processed. A later replay has no external mutation.')
ON CONFLICT (tenant_id, definition_key) DO NOTHING;
"""

REVERSE_SQL = r"""
DELETE FROM operations.job_recovery_policy_authorities WHERE definition_key = 'source-record-assess';
DELETE FROM operations.queue_registry WHERE queue_key = 'source_record.assessment';
DROP TRIGGER IF EXISTS source_record_admit_update ON operations.entity_observation_current;
DROP TRIGGER IF EXISTS source_record_admit_insert ON operations.entity_observation_current;
DROP TABLE IF EXISTS operations.source_record_assessment_current;
DROP TABLE IF EXISTS operations.source_record_assessment_queue;
DROP TABLE IF EXISTS operations.source_record_lookup_keys;
DROP TABLE IF EXISTS operations.source_record_subjects;
DROP TABLE IF EXISTS operations.source_record_tenant_state;
DROP FUNCTION IF EXISTS operations.source_record_admit_observation();
DROP FUNCTION IF EXISTS operations.source_record_advance_generation();
DROP FUNCTION IF EXISTS operations.source_record_enqueue_neighbors(bigint, uuid, uuid, text[], text[]);
DROP FUNCTION IF EXISTS operations.source_record_case_key_id(bigint, uuid, text, text);
DROP FUNCTION IF EXISTS operations.source_record_enqueue(bigint, text, uuid, jsonb);
DROP FUNCTION IF EXISTS operations.source_record_keys(bigint, uuid, text, text, jsonb);
DROP FUNCTION IF EXISTS operations.source_record_role_compares_identity(text);
DROP FUNCTION IF EXISTS operations.source_record_role(text);
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('source_record_tenant_state', 'source_record_subjects',
                      'source_record_lookup_keys', 'source_record_assessment_queue',
                      'source_record_assessment_current');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0369_finding_namespace_model_state"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
