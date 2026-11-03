"""Install the transactional invalidation foundation for PLAN-045.

This is one part of an unfinished transition. A missing or dirty row is not an
effective owner. In particular, this migration alone does not protect existing
readers and must be shipped together with the projector and reader transition.
It does not backfill existing Computers.
"""

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE TABLE operations.computer_client_ownership (
    tenant_id bigint NOT NULL,
    device_id uuid NOT NULL,
    state text NOT NULL DEFAULT 'dirty'
        CHECK (state IN ('dirty', 'resolved', 'unknown', 'conflict', 'review', 'decision_protected')),
    effective_client_id uuid,
    evidence_revision bigint NOT NULL DEFAULT 1 CHECK (evidence_revision > 0),
    projected_revision bigint NOT NULL DEFAULT 0 CHECK (projected_revision >= 0),
    contradiction boolean NOT NULL DEFAULT false,
    reason text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id),
    FOREIGN KEY (tenant_id, device_id) REFERENCES operations.devices (tenant_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, effective_client_id) REFERENCES operations.clients (tenant_id, id),
    CHECK ((state IN ('resolved', 'decision_protected')) = (effective_client_id IS NOT NULL)),
    CHECK ((state = 'dirty' AND projected_revision < evidence_revision)
        OR (state <> 'dirty' AND projected_revision = evidence_revision)),
    CHECK (NOT contradiction OR state = 'decision_protected')
);

ALTER TABLE operations.computer_client_ownership ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.computer_client_ownership FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.computer_client_ownership
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.computer_client_ownership FROM PUBLIC, operations_app,
    operations_readonly, ninja_ingest;
GRANT SELECT ON operations.computer_client_ownership TO operations_app,
    operations_readonly, ninja_ingest;
CREATE INDEX computer_client_ownership_dirty_idx
    ON operations.computer_client_ownership (tenant_id, device_id)
    WHERE state = 'dirty';

-- Client-scoped mutations hold this row lock until their transaction ends.
-- Runtime roles cannot update the projection and so cannot take the lock
-- directly; the definer only accepts the current tenant and selected client.
CREATE FUNCTION operations.lock_computer_client_scope(
    p_tenant bigint, p_device uuid, p_client uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'lock_computer_client_scope: tenant context mismatch';
    END IF;
    PERFORM 1 FROM operations.computer_client_ownership
     WHERE tenant_id = p_tenant AND device_id = p_device
       AND effective_client_id = p_client AND state IN ('resolved', 'decision_protected')
     FOR SHARE;
    RETURN FOUND;
END
$fn$;
REVOKE ALL ON FUNCTION operations.lock_computer_client_scope(bigint, uuid, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.lock_computer_client_scope(bigint, uuid, uuid)
    TO operations_app, ninja_ingest;

CREATE FUNCTION operations.lock_computer_client_scopes(
    p_tenant bigint, p_devices uuid[], p_clients uuid[]
) RETURNS TABLE(device_id uuid, client_id uuid)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR coalesce(cardinality(p_devices), 0) <> coalesce(cardinality(p_clients), 0) THEN
        RAISE EXCEPTION 'lock_computer_client_scopes: tenant context or input mismatch';
    END IF;
    -- All callers take locks in the same order, even when their inputs overlap.
    FOR target IN SELECT DISTINCT item.device_id, item.client_id
                    FROM unnest(p_devices, p_clients) AS item(device_id, client_id)
                   WHERE item.device_id IS NOT NULL AND item.client_id IS NOT NULL
                   ORDER BY item.device_id, item.client_id
    LOOP
        IF operations.lock_computer_client_scope(p_tenant, target.device_id, target.client_id) THEN
            device_id := target.device_id; client_id := target.client_id;
            RETURN NEXT;
        END IF;
    END LOOP;
END
$fn$;
REVOKE ALL ON FUNCTION operations.lock_computer_client_scopes(bigint, uuid[], uuid[])
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.lock_computer_client_scopes(bigint, uuid[], uuid[])
    TO ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'computer_client_ownership', 'exempt',
    'Rebuildable derived ownership projection and invalidation state',
    '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, false, NULL
);

CREATE FUNCTION operations.queue_source_client_reassessment(p_tenant bigint, p_subject uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_instance uuid;
BEGIN
    UPDATE operations.source_record_subjects
       SET input_version = input_version + 1, updated_at = now()
     WHERE tenant_id = p_tenant AND id = p_subject AND subject_kind = 'record'
     RETURNING source_instance_id INTO v_instance;
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM operations.source_record_enqueue(p_tenant, 'source_record', p_subject);
    PERFORM operations.source_record_enqueue_neighbors(
        p_tenant, p_subject, v_instance,
        coalesce((SELECT array_agg(key_family::text ORDER BY key_family, normalized_value)
                    FROM operations.source_record_lookup_keys WHERE tenant_id = p_tenant AND subject_id = p_subject), '{}'::text[]),
        coalesce((SELECT array_agg(normalized_value::text ORDER BY key_family, normalized_value)
                    FROM operations.source_record_lookup_keys WHERE tenant_id = p_tenant AND subject_id = p_subject), '{}'::text[]));
END
$fn$;

CREATE FUNCTION operations.queue_computer_client_reassessment(p_tenant bigint, p_device uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT s.id FROM operations.source_record_subjects s
        JOIN operations.entity_observation_current observation
          ON observation.tenant_id = s.tenant_id AND observation.observation_id = s.observation_id
        WHERE s.tenant_id = p_tenant AND observation.device_id = p_device
          AND s.subject_kind = 'record'
        ORDER BY s.id
    LOOP
        PERFORM operations.queue_source_client_reassessment(p_tenant, target.id);
    END LOOP;
END
$fn$;

CREATE FUNCTION operations.invalidate_computer_client_ownership(p_tenant bigint, p_device uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS NULL OR p_device IS NULL THEN
        RETURN;
    END IF;
    -- A device may already be gone when a cascading delete reaches an input.
    INSERT INTO operations.computer_client_ownership AS ownership
        (tenant_id, device_id)
    SELECT d.tenant_id, d.id FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.id = p_device
    ON CONFLICT (tenant_id, device_id) DO UPDATE
       SET state = 'dirty', effective_client_id = NULL,
           evidence_revision = ownership.evidence_revision + 1,
           contradiction = false, reason = '', updated_at = now();
    PERFORM operations.queue_computer_client_reassessment(p_tenant, p_device);
END
$fn$;

CREATE FUNCTION operations.invalidate_computer_client_observation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.tenant_id, OLD.device_id, OLD.active, OLD.platform,
            OLD.canonical_data->'source_client_attribution',
            OLD.canonical_data->>'platform_group_id', OLD.parent_external_namespace, OLD.parent_external_id,
            OLD.entity_type, OLD.entity_key, OLD.external_namespace, OLD.external_id,
            OLD.source_instance_id)
           IS NOT DISTINCT FROM
           (NEW.tenant_id, NEW.device_id, NEW.active, NEW.platform,
            NEW.canonical_data->'source_client_attribution',
            NEW.canonical_data->>'platform_group_id', NEW.parent_external_namespace, NEW.parent_external_id,
            NEW.entity_type, NEW.entity_key, NEW.external_namespace, NEW.external_id,
            NEW.source_instance_id) THEN
        RETURN NULL;
    END IF;
    -- A reattachment invalidates both owners. Stable ordering prevents the
    -- common two-device reattachment from locking the two rows in reverse.
    FOR target IN
        SELECT DISTINCT tenant_id, device_id FROM (
            SELECT OLD.tenant_id, OLD.device_id WHERE TG_OP <> 'INSERT'
            UNION ALL
            SELECT NEW.tenant_id, NEW.device_id WHERE TG_OP <> 'DELETE'
        ) affected WHERE device_id IS NOT NULL ORDER BY tenant_id, device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    -- Some source-group changes are not part of a stream's material hash.
    -- The ordinary admission trigger can therefore miss an unattached record.
    FOR target IN
        SELECT DISTINCT subject.tenant_id, subject.id
          FROM operations.source_record_subjects subject
          JOIN (
              SELECT OLD.tenant_id, OLD.observation_id
               WHERE TG_OP <> 'INSERT' AND OLD.device_id IS NULL
              UNION
              SELECT NEW.tenant_id, NEW.observation_id
               WHERE TG_OP <> 'DELETE' AND NEW.device_id IS NULL
          ) affected ON affected.tenant_id = subject.tenant_id
                    AND affected.observation_id = subject.observation_id
         WHERE subject.subject_kind = 'record'
         ORDER BY subject.tenant_id, subject.id
    LOOP
        PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.id);
    END LOOP;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_observation_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_observation_current
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_observation();

CREATE FUNCTION operations.invalidate_computer_client_device() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' OR
       (OLD.client_id, OLD.deleted_at) IS DISTINCT FROM (NEW.client_id, NEW.deleted_at) THEN
        PERFORM operations.invalidate_computer_client_ownership(NEW.tenant_id, NEW.id);
    END IF;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_device_dirty
AFTER INSERT OR UPDATE OF client_id, deleted_at ON operations.devices
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_device();

CREATE FUNCTION operations.invalidate_computer_client_decision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.tenant_id, OLD.device_id, OLD.dimension, OLD.value, OLD.version)
           IS NOT DISTINCT FROM
           (NEW.tenant_id, NEW.device_id, NEW.dimension, NEW.value, NEW.version) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT tenant_id, device_id FROM (
            SELECT OLD.tenant_id, OLD.device_id
             WHERE TG_OP <> 'INSERT'
               AND OLD.dimension IN ('client_conflict_accepted', 'client_ownership_choice')
            UNION ALL
            SELECT NEW.tenant_id, NEW.device_id
             WHERE TG_OP <> 'DELETE'
               AND NEW.dimension IN ('client_conflict_accepted', 'client_ownership_choice')
        ) affected WHERE device_id IS NOT NULL ORDER BY tenant_id, device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_decision_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.device_operator_decisions
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_decision();

CREATE FUNCTION operations.invalidate_computer_client_roaming() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id
          FROM operations.entity_observation_current observation
          JOIN (
              SELECT OLD.tenant_id, OLD.source_instance_id, OLD.external_id
               WHERE TG_OP <> 'INSERT'
              UNION
              SELECT NEW.tenant_id, NEW.source_instance_id, NEW.external_id
               WHERE TG_OP <> 'DELETE'
          ) roaming ON roaming.tenant_id = observation.tenant_id
                   AND roaming.source_instance_id = observation.source_instance_id
                   AND roaming.external_id = observation.external_id
         WHERE observation.device_id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;

CREATE TRIGGER computer_client_roaming_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.identity_roaming_records
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_roaming();

CREATE FUNCTION operations.invalidate_computer_client_availability() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF OLD.deleted_at IS NOT DISTINCT FROM NEW.deleted_at THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT d.tenant_id, d.id AS device_id FROM operations.devices d
         WHERE d.tenant_id = NEW.tenant_id AND (
             d.client_id = NEW.id OR EXISTS (
                 SELECT 1 FROM operations.entity_observation_current observation
                  WHERE observation.tenant_id = d.tenant_id AND observation.device_id = d.id
                    AND (observation.client_id = NEW.id OR EXISTS (
                        SELECT 1 FROM operations.source_instances instance
                         WHERE instance.tenant_id = observation.tenant_id
                           AND instance.id = observation.source_instance_id
                           AND instance.client_id = NEW.id
                    ) OR EXISTS (
                        SELECT 1 FROM operations.entity_source_links link
                         WHERE link.tenant_id = observation.tenant_id
                           AND link.source_instance_id = observation.source_instance_id
                           AND link.entity_class_id = 'client'
                           AND link.entity_id = NEW.id AND link.missing_since IS NULL
                           AND (link.external_id = observation.canonical_data->>'platform_group_id'
                                OR EXISTS (SELECT 1 FROM operations.entity_observation_current org
                                    WHERE org.tenant_id = link.tenant_id
                                      AND org.source_instance_id = link.source_instance_id
                                      AND org.entity_type = 'org' AND org.external_id = link.external_id
                                      AND org.entity_key = observation.canonical_data->>'platform_group_id'))
                    ))) OR EXISTS (
                 SELECT 1 FROM operations.device_operator_decisions decision
                  WHERE decision.tenant_id = d.tenant_id AND decision.device_id = d.id
                    AND decision.dimension = 'client_ownership_choice'
                    AND decision.value ->> 'client_id' = NEW.id::text))
         ORDER BY d.tenant_id, d.id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    FOR target IN
        SELECT DISTINCT subject.id
          FROM operations.source_record_subjects subject
          JOIN operations.entity_observation_current observation
            ON observation.tenant_id = subject.tenant_id
           AND observation.observation_id = subject.observation_id
         WHERE subject.tenant_id = NEW.tenant_id AND subject.subject_kind = 'record'
           AND observation.device_id IS NULL AND (
               observation.client_id = NEW.id OR EXISTS (
                   SELECT 1 FROM operations.source_instances instance
                    WHERE instance.tenant_id = observation.tenant_id
                      AND instance.id = observation.source_instance_id AND instance.client_id = NEW.id)
               OR EXISTS (
                   SELECT 1 FROM operations.entity_source_links link
                    WHERE link.tenant_id = observation.tenant_id
                      AND link.source_instance_id = observation.source_instance_id
                      AND link.entity_class_id = 'client' AND link.entity_id = NEW.id
                      AND link.missing_since IS NULL
                      AND (link.external_id = observation.canonical_data->>'platform_group_id'
                           OR (observation.entity_type = 'org' AND link.external_id = observation.external_id)
                           OR EXISTS (SELECT 1 FROM operations.entity_observation_current org
                               WHERE org.tenant_id = link.tenant_id
                                 AND org.source_instance_id = link.source_instance_id
                                 AND org.entity_type = 'org' AND org.external_id = link.external_id
                                 AND org.entity_key = observation.canonical_data->>'platform_group_id'))))
         ORDER BY subject.id
    LOOP
        PERFORM operations.queue_source_client_reassessment(NEW.tenant_id, target.id);
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_availability_dirty
AFTER UPDATE OF deleted_at ON operations.clients
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_availability();

CREATE FUNCTION operations.invalidate_computer_client_relationship() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.tenant_id, OLD.relationship_type_id, OLD.source_entity_id, OLD.target_entity_id, OLD.status)
       IS NOT DISTINCT FROM
       (NEW.tenant_id, NEW.relationship_type_id, NEW.source_entity_id, NEW.target_entity_id, NEW.status) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT d.tenant_id, d.id AS device_id
          FROM operations.devices d JOIN (
              SELECT OLD.tenant_id, OLD.source_entity_id, OLD.target_entity_id
               WHERE TG_OP <> 'INSERT' AND OLD.relationship_type_id = 'os_installation_runs_on_computer'
              UNION
              SELECT NEW.tenant_id, NEW.source_entity_id, NEW.target_entity_id
               WHERE TG_OP <> 'DELETE' AND NEW.relationship_type_id = 'os_installation_runs_on_computer'
          ) affected ON affected.tenant_id = d.tenant_id
         WHERE d.entity_id = affected.target_entity_id OR EXISTS (
             SELECT 1 FROM operations.entity_relationships relationship
              WHERE relationship.tenant_id = affected.tenant_id
                AND relationship.relationship_type_id = 'os_installation_runs_on_computer'
                AND relationship.source_entity_id = affected.source_entity_id
                AND relationship.target_entity_id = d.entity_id
                AND relationship.status = 'active')
         ORDER BY d.tenant_id, d.id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_relationship_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_relationships
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_relationship();

CREATE FUNCTION operations.invalidate_computer_client_companion_stream() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.source_id, OLD.external_namespace, OLD.enabled) IS NOT DISTINCT FROM
       (NEW.source_id, NEW.external_namespace, NEW.enabled) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id
          FROM operations.entity_observation_current observation
          JOIN operations.source_instances instance
            ON instance.tenant_id = observation.tenant_id AND instance.id = observation.source_instance_id
          JOIN (
              SELECT OLD.source_id, OLD.external_namespace WHERE TG_OP <> 'INSERT'
              UNION
              SELECT NEW.source_id, NEW.external_namespace WHERE TG_OP <> 'DELETE'
          ) affected ON affected.source_id = instance.source_id
                    AND affected.external_namespace = observation.external_namespace
         WHERE observation.device_id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id
    LOOP
        PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_companion_stream_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.source_record_companion_streams
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_companion_stream();

CREATE FUNCTION operations.invalidate_computer_client_source_instance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    target record; v_last_device uuid;
BEGIN
    IF (OLD.source_id, OLD.client_id) IS NOT DISTINCT FROM (NEW.source_id, NEW.client_id) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id, subject.id AS subject_id
          FROM operations.entity_observation_current observation
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = observation.tenant_id
           AND subject.observation_id = observation.observation_id
           AND subject.subject_kind = 'record'
         WHERE observation.tenant_id = NEW.tenant_id AND observation.source_instance_id = NEW.id
           AND (observation.device_id IS NOT NULL OR subject.id IS NOT NULL)
         ORDER BY observation.tenant_id, observation.device_id, subject.id
    LOOP
        IF target.device_id IS NOT NULL AND target.device_id IS DISTINCT FROM v_last_device THEN
            PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
            v_last_device := target.device_id;
        ELSIF target.device_id IS NULL AND target.subject_id IS NOT NULL THEN
            PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.subject_id);
        END IF;
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_source_instance_dirty
AFTER UPDATE OF source_id, client_id ON operations.source_instances
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_source_instance();

-- A group link or its decision can change independent source-client evidence
-- without updating the attached device observations themselves.
CREATE FUNCTION operations.invalidate_computer_client_group_link() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE target record; v_last_device uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.tenant_id, OLD.entity_class_id, OLD.entity_id, OLD.source_instance_id,
        OLD.external_id, OLD.external_namespace, OLD.parent_external_namespace,
        OLD.parent_external_id, OLD.missing_since) IS NOT DISTINCT FROM
       (NEW.tenant_id, NEW.entity_class_id, NEW.entity_id, NEW.source_instance_id,
        NEW.external_id, NEW.external_namespace, NEW.parent_external_namespace,
        NEW.parent_external_id, NEW.missing_since) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id, subject.id AS subject_id
          FROM operations.entity_observation_current observation
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = observation.tenant_id
           AND subject.observation_id = observation.observation_id
           AND subject.subject_kind = 'record'
          JOIN (
              SELECT OLD.tenant_id, OLD.source_instance_id, OLD.external_id
               WHERE TG_OP <> 'INSERT' AND OLD.entity_class_id = 'client'
              UNION
              SELECT NEW.tenant_id, NEW.source_instance_id, NEW.external_id
               WHERE TG_OP <> 'DELETE' AND NEW.entity_class_id = 'client'
          ) affected ON affected.tenant_id = observation.tenant_id
                    AND affected.source_instance_id = observation.source_instance_id
                    AND (affected.external_id = observation.canonical_data->>'platform_group_id'
                         OR affected.external_id = observation.parent_external_id
                         OR (observation.entity_type = 'org' AND affected.external_id = observation.external_id)
                         OR EXISTS (SELECT 1 FROM operations.entity_observation_current org
                             WHERE org.tenant_id = affected.tenant_id
                               AND org.source_instance_id = affected.source_instance_id
                               AND org.entity_type = 'org' AND org.external_id = affected.external_id
                               AND org.entity_key = observation.canonical_data->>'platform_group_id'))
         WHERE observation.device_id IS NOT NULL OR subject.id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id, subject.id
    LOOP
        IF target.device_id IS NOT NULL AND target.device_id IS DISTINCT FROM v_last_device THEN
            PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
            v_last_device := target.device_id;
        ELSIF target.device_id IS NULL AND target.subject_id IS NOT NULL THEN
            PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.subject_id);
        END IF;
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_group_link_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_source_links
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_group_link();

CREATE FUNCTION operations.invalidate_computer_client_group_history() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE target record; v_last_device uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.tenant_id, OLD.entity_class_id, OLD.entity_id, OLD.source_instance_id,
        OLD.external_id, OLD.external_namespace, OLD.parent_external_namespace,
        OLD.parent_external_id, OLD.effective_from, OLD.effective_to, OLD.actor_kind)
           IS NOT DISTINCT FROM
       (NEW.tenant_id, NEW.entity_class_id, NEW.entity_id, NEW.source_instance_id,
        NEW.external_id, NEW.external_namespace, NEW.parent_external_namespace,
        NEW.parent_external_id, NEW.effective_from, NEW.effective_to, NEW.actor_kind) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id, subject.id AS subject_id
          FROM operations.entity_observation_current observation
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = observation.tenant_id
           AND subject.observation_id = observation.observation_id
           AND subject.subject_kind = 'record'
          JOIN (
              SELECT OLD.tenant_id, OLD.source_instance_id, OLD.external_id
               WHERE TG_OP <> 'INSERT' AND OLD.entity_class_id = 'client'
              UNION
              SELECT NEW.tenant_id, NEW.source_instance_id, NEW.external_id
               WHERE TG_OP <> 'DELETE' AND NEW.entity_class_id = 'client'
          ) affected ON affected.tenant_id = observation.tenant_id
                    AND affected.source_instance_id = observation.source_instance_id
                    AND (affected.external_id = observation.canonical_data->>'platform_group_id'
                         OR affected.external_id = observation.parent_external_id
                         OR (observation.entity_type = 'org' AND affected.external_id = observation.external_id)
                         OR EXISTS (SELECT 1 FROM operations.entity_observation_current org
                             WHERE org.tenant_id = affected.tenant_id
                               AND org.source_instance_id = affected.source_instance_id
                               AND org.entity_type = 'org' AND org.external_id = affected.external_id
                               AND org.entity_key = observation.canonical_data->>'platform_group_id'))
         WHERE observation.device_id IS NOT NULL OR subject.id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id, subject.id
    LOOP
        IF target.device_id IS NOT NULL AND target.device_id IS DISTINCT FROM v_last_device THEN
            PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
            v_last_device := target.device_id;
        ELSIF target.device_id IS NULL AND target.subject_id IS NOT NULL THEN
            PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.subject_id);
        END IF;
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_group_history_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_source_link_history
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_group_history();

-- Independent name corroboration depends on the current source-group name.
CREATE FUNCTION operations.invalidate_computer_client_group_observation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE target record; v_last_device uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.tenant_id, OLD.source_instance_id, OLD.entity_type, OLD.entity_key,
        OLD.external_id, OLD.external_namespace, OLD.parent_external_namespace,
        OLD.parent_external_id, OLD.active, OLD.canonical_data->>'name',
        OLD.canonical_data->>'is_placeholder')
           IS NOT DISTINCT FROM
       (NEW.tenant_id, NEW.source_instance_id, NEW.entity_type, NEW.entity_key,
        NEW.external_id, NEW.external_namespace, NEW.parent_external_namespace,
        NEW.parent_external_id, NEW.active, NEW.canonical_data->>'name',
        NEW.canonical_data->>'is_placeholder') THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id, subject.id AS subject_id
          FROM operations.entity_observation_current observation
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = observation.tenant_id
           AND subject.observation_id = observation.observation_id
           AND subject.subject_kind = 'record'
          JOIN (
              SELECT OLD.tenant_id, OLD.source_instance_id, OLD.entity_key, OLD.external_id
               WHERE TG_OP <> 'INSERT' AND OLD.entity_type = 'org'
              UNION
              SELECT NEW.tenant_id, NEW.source_instance_id, NEW.entity_key, NEW.external_id
               WHERE TG_OP <> 'DELETE' AND NEW.entity_type = 'org'
          ) affected ON affected.tenant_id = observation.tenant_id
                    AND affected.source_instance_id = observation.source_instance_id
                    AND (observation.canonical_data->>'platform_group_id' IN
                         (affected.entity_key, affected.external_id)
                         OR observation.parent_external_id IN (affected.entity_key, affected.external_id)
                         OR (observation.entity_type = 'org' AND observation.external_id = affected.external_id))
         WHERE observation.device_id IS NOT NULL OR subject.id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id, subject.id
    LOOP
        IF target.device_id IS NOT NULL AND target.device_id IS DISTINCT FROM v_last_device THEN
            PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
            v_last_device := target.device_id;
        ELSIF target.device_id IS NULL AND target.subject_id IS NOT NULL THEN
            PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.subject_id);
        END IF;
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_group_observation_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_observation_current
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_group_observation();

-- Name ambiguity, aliases and exclusions can change without touching a group.
-- Restrict invalidation to groups reporting the affected normalized names.
CREATE FUNCTION operations.invalidate_computer_client_name_authority() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_old_tenant bigint; v_new_tenant bigint;
    v_old_name text; v_new_name text;
    target record; v_last_device uuid;
BEGIN
    IF TG_TABLE_NAME = 'clients' THEN
        IF TG_OP = 'UPDATE' AND (OLD.tenant_id, OLD.display_name, OLD.deleted_at)
           IS NOT DISTINCT FROM (NEW.tenant_id, NEW.display_name, NEW.deleted_at) THEN
            RETURN NULL;
        END IF;
        IF TG_OP <> 'INSERT' THEN v_old_tenant := OLD.tenant_id; v_old_name := OLD.display_name; END IF;
        IF TG_OP <> 'DELETE' THEN v_new_tenant := NEW.tenant_id; v_new_name := NEW.display_name; END IF;
    ELSIF TG_TABLE_NAME = 'client_name_aliases' THEN
        IF TG_OP = 'UPDATE' AND (OLD.tenant_id, OLD.client_id, OLD.normalized_name, OLD.tier, OLD.enabled, OLD.created_by)
           IS NOT DISTINCT FROM (NEW.tenant_id, NEW.client_id, NEW.normalized_name, NEW.tier, NEW.enabled, NEW.created_by) THEN
            RETURN NULL;
        END IF;
        IF TG_OP <> 'INSERT' THEN v_old_tenant := OLD.tenant_id; v_old_name := OLD.normalized_name; END IF;
        IF TG_OP <> 'DELETE' THEN v_new_tenant := NEW.tenant_id; v_new_name := NEW.normalized_name; END IF;
    ELSIF TG_TABLE_NAME = 'client_org_excludes' THEN
        IF TG_OP = 'UPDATE' AND (OLD.tenant_id, OLD.normalized_name, OLD.enabled)
           IS NOT DISTINCT FROM (NEW.tenant_id, NEW.normalized_name, NEW.enabled) THEN
            RETURN NULL;
        END IF;
        IF TG_OP <> 'INSERT' THEN v_old_tenant := OLD.tenant_id; v_old_name := OLD.normalized_name; END IF;
        IF TG_OP <> 'DELETE' THEN v_new_tenant := NEW.tenant_id; v_new_name := NEW.normalized_name; END IF;
    ELSE
        IF TG_OP = 'UPDATE' AND (OLD.tenant_id, OLD.normalized_name)
           IS NOT DISTINCT FROM (NEW.tenant_id, NEW.normalized_name) THEN
            RETURN NULL;
        END IF;
        IF TG_OP <> 'INSERT' THEN v_old_tenant := OLD.tenant_id; v_old_name := OLD.normalized_name; END IF;
        IF TG_OP <> 'DELETE' THEN v_new_tenant := NEW.tenant_id; v_new_name := NEW.normalized_name; END IF;
    END IF;
    v_old_name := regexp_replace(lower(coalesce(v_old_name, '')), '[\s\-_.]', '', 'g');
    v_new_name := regexp_replace(lower(coalesce(v_new_name, '')), '[\s\-_.]', '', 'g');
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id, subject.id AS subject_id
          FROM operations.entity_observation_current observation
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = observation.tenant_id
           AND subject.observation_id = observation.observation_id
           AND subject.subject_kind = 'record'
          JOIN operations.entity_observation_current org
            ON org.tenant_id = observation.tenant_id AND org.source_instance_id = observation.source_instance_id
           AND org.entity_type = 'org' AND org.active
           AND (observation.canonical_data->>'platform_group_id' IN (org.entity_key, org.external_id)
                OR (observation.entity_type = 'org' AND observation.observation_id = org.observation_id))
         WHERE (observation.device_id IS NOT NULL OR subject.id IS NOT NULL) AND (
             (org.tenant_id = v_old_tenant AND v_old_name <> '' AND
              regexp_replace(lower(coalesce(org.canonical_data->>'name', '')), '[\s\-_.]', '', 'g') = v_old_name)
             OR (org.tenant_id = v_new_tenant AND v_new_name <> '' AND
              regexp_replace(lower(coalesce(org.canonical_data->>'name', '')), '[\s\-_.]', '', 'g') = v_new_name))
         ORDER BY observation.tenant_id, observation.device_id, subject.id
    LOOP
        IF target.device_id IS NOT NULL AND target.device_id IS DISTINCT FROM v_last_device THEN
            PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
            v_last_device := target.device_id;
        ELSIF target.device_id IS NULL AND target.subject_id IS NOT NULL THEN
            PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.subject_id);
        END IF;
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_name_client_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.clients
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_name_authority();
CREATE TRIGGER computer_client_name_alias_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.client_name_aliases
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_name_authority();
CREATE TRIGGER computer_client_name_exclude_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.client_org_excludes
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_name_authority();
CREATE TRIGGER computer_client_name_placeholder_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.placeholder_org_names
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_name_authority();

CREATE FUNCTION operations.invalidate_computer_client_mapping_decision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE target record; v_last_device uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.tenant_id, OLD.source_link_id, OLD.state, OLD.provenance, OLD.decided_at, OLD.superseded_at)
           IS NOT DISTINCT FROM
       (NEW.tenant_id, NEW.source_link_id, NEW.state, NEW.provenance, NEW.decided_at, NEW.superseded_at) THEN
        RETURN NULL;
    END IF;
    FOR target IN
        SELECT DISTINCT observation.tenant_id, observation.device_id, subject.id AS subject_id
          FROM operations.entity_observation_current observation
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = observation.tenant_id
           AND subject.observation_id = observation.observation_id
           AND subject.subject_kind = 'record'
          JOIN operations.entity_source_links link
            ON link.tenant_id = observation.tenant_id
           AND link.source_instance_id = observation.source_instance_id
           AND link.entity_class_id = 'client'
           AND (link.external_id = observation.canonical_data->>'platform_group_id'
                OR link.external_id = observation.parent_external_id
                OR (observation.entity_type = 'org' AND link.external_id = observation.external_id)
                OR EXISTS (SELECT 1 FROM operations.entity_observation_current org
                    WHERE org.tenant_id = link.tenant_id AND org.source_instance_id = link.source_instance_id
                      AND org.entity_type = 'org' AND org.external_id = link.external_id
                      AND org.entity_key = observation.canonical_data->>'platform_group_id'))
          JOIN (
              SELECT OLD.tenant_id, OLD.source_link_id WHERE TG_OP <> 'INSERT'
              UNION
              SELECT NEW.tenant_id, NEW.source_link_id WHERE TG_OP <> 'DELETE'
          ) affected ON affected.tenant_id = link.tenant_id AND affected.source_link_id = link.id
         WHERE observation.device_id IS NOT NULL OR subject.id IS NOT NULL
         ORDER BY observation.tenant_id, observation.device_id, subject.id
    LOOP
        IF target.device_id IS NOT NULL AND target.device_id IS DISTINCT FROM v_last_device THEN
            PERFORM operations.invalidate_computer_client_ownership(target.tenant_id, target.device_id);
            v_last_device := target.device_id;
        ELSIF target.device_id IS NULL AND target.subject_id IS NOT NULL THEN
            PERFORM operations.queue_source_client_reassessment(target.tenant_id, target.subject_id);
        END IF;
    END LOOP;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER computer_client_mapping_decision_dirty
AFTER INSERT OR UPDATE OR DELETE ON operations.client_source_mapping_decisions
FOR EACH ROW EXECUTE FUNCTION operations.invalidate_computer_client_mapping_decision();

REVOKE ALL ON FUNCTION operations.queue_source_client_reassessment(bigint, uuid),
    operations.queue_computer_client_reassessment(bigint, uuid),
    operations.invalidate_computer_client_ownership(bigint, uuid),
    operations.invalidate_computer_client_observation(),
    operations.invalidate_computer_client_device(),
    operations.invalidate_computer_client_decision(),
    operations.invalidate_computer_client_roaming(),
    operations.invalidate_computer_client_availability(),
    operations.invalidate_computer_client_relationship(),
    operations.invalidate_computer_client_companion_stream(),
    operations.invalidate_computer_client_source_instance(),
    operations.invalidate_computer_client_group_link(),
    operations.invalidate_computer_client_group_history(),
    operations.invalidate_computer_client_group_observation(),
    operations.invalidate_computer_client_name_authority(),
    operations.invalidate_computer_client_mapping_decision() FROM PUBLIC, operations_app,
    operations_readonly, ninja_ingest;
"""

REVERSE_SQL = r"""
DROP TRIGGER computer_client_mapping_decision_dirty ON operations.client_source_mapping_decisions;
DROP TRIGGER computer_client_name_placeholder_dirty ON operations.placeholder_org_names;
DROP TRIGGER computer_client_name_exclude_dirty ON operations.client_org_excludes;
DROP TRIGGER computer_client_name_alias_dirty ON operations.client_name_aliases;
DROP TRIGGER computer_client_name_client_dirty ON operations.clients;
DROP TRIGGER computer_client_group_observation_dirty ON operations.entity_observation_current;
DROP TRIGGER computer_client_group_history_dirty ON operations.entity_source_link_history;
DROP TRIGGER computer_client_group_link_dirty ON operations.entity_source_links;
DROP TRIGGER computer_client_source_instance_dirty ON operations.source_instances;
DROP TRIGGER computer_client_companion_stream_dirty ON operations.source_record_companion_streams;
DROP TRIGGER computer_client_relationship_dirty ON operations.entity_relationships;
DROP TRIGGER computer_client_availability_dirty ON operations.clients;
DROP TRIGGER computer_client_roaming_dirty ON operations.identity_roaming_records;
DROP TRIGGER computer_client_decision_dirty ON operations.device_operator_decisions;
DROP TRIGGER computer_client_observation_dirty ON operations.entity_observation_current;
DROP TRIGGER computer_client_device_dirty ON operations.devices;
DROP FUNCTION operations.invalidate_computer_client_roaming();
DROP FUNCTION operations.invalidate_computer_client_source_instance();
DROP FUNCTION operations.invalidate_computer_client_group_link();
DROP FUNCTION operations.invalidate_computer_client_group_history();
DROP FUNCTION operations.invalidate_computer_client_group_observation();
DROP FUNCTION operations.invalidate_computer_client_name_authority();
DROP FUNCTION operations.invalidate_computer_client_mapping_decision();
DROP FUNCTION operations.invalidate_computer_client_companion_stream();
DROP FUNCTION operations.invalidate_computer_client_relationship();
DROP FUNCTION operations.invalidate_computer_client_availability();
DROP FUNCTION operations.invalidate_computer_client_decision();
DROP FUNCTION operations.invalidate_computer_client_observation();
DROP FUNCTION operations.invalidate_computer_client_device();
DROP FUNCTION operations.invalidate_computer_client_ownership(bigint, uuid);
DROP FUNCTION operations.queue_computer_client_reassessment(bigint, uuid);
DROP FUNCTION operations.queue_source_client_reassessment(bigint, uuid);
DROP FUNCTION operations.lock_computer_client_scopes(bigint, uuid[], uuid[]);
DROP FUNCTION operations.lock_computer_client_scope(bigint, uuid, uuid);
DROP TABLE operations.computer_client_ownership;
DELETE FROM operations.change_history_registry WHERE table_name = 'computer_client_ownership';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0400_association_refreshes_computer_values"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
