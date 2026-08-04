from typing import ClassVar

from django.db import migrations

TENANT_CONSTRAINTS_SQL = r"""
ALTER TABLE operations.relationship_authority_policies
    ADD CONSTRAINT fk_rel_policy_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_relationship_evidence_current
    ADD CONSTRAINT fk_rel_evidence_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_evidence_tenant_source_endpoint
    FOREIGN KEY (tenant_id, source_endpoint_source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_evidence_tenant_target_endpoint
    FOREIGN KEY (tenant_id, target_endpoint_source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_evidence_tenant_source_entity
    FOREIGN KEY (tenant_id, source_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_evidence_tenant_target_entity
    FOREIGN KEY (tenant_id, target_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_relationship_dirty
    ADD CONSTRAINT fk_rel_dirty_tenant_source_entity
    FOREIGN KEY (tenant_id, source_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_dirty_tenant_target_entity
    FOREIGN KEY (tenant_id, target_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_relationship_decision_current
    ADD CONSTRAINT fk_rel_decision_tenant_source_entity
    FOREIGN KEY (tenant_id, source_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_decision_tenant_target_entity
    FOREIGN KEY (tenant_id, target_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_decision_tenant_user
    FOREIGN KEY (tenant_id, decided_by_id)
    REFERENCES operations.users (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_relationships
    ADD CONSTRAINT fk_relationship_tenant_source_entity
    FOREIGN KEY (tenant_id, source_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_relationship_tenant_target_entity
    FOREIGN KEY (tenant_id, target_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_relationship_evidence_support
    ADD CONSTRAINT fk_rel_support_tenant_relationship
    FOREIGN KEY (tenant_id, relationship_id)
    REFERENCES operations.entity_relationships (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_support_tenant_evidence
    FOREIGN KEY (tenant_id, evidence_id)
    REFERENCES operations.entity_relationship_evidence_current (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.source_events
    ADD CONSTRAINT fk_source_event_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_source_event_tenant_binding
    FOREIGN KEY (tenant_id, source_binding_id)
    REFERENCES operations.source_bindings (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_observation_history
    ADD CONSTRAINT fk_obs_history_tenant_source_event
    FOREIGN KEY (tenant_id, closed_by_source_event_id)
    REFERENCES operations.source_events (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;
"""


RLS_SQL = r"""
ALTER TABLE operations.relationship_authority_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.relationship_authority_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_evidence_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_evidence_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_dirty ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_dirty FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_decision_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_decision_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationships FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_evidence_support ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_evidence_support FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.source_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_events FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON operations.relationship_authority_policies
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.entity_relationship_evidence_current
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.entity_relationship_dirty
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.entity_relationship_decision_current
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.entity_relationships
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.entity_relationship_evidence_support
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
CREATE POLICY tenant_isolation ON operations.source_events
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());
"""


SEED_SQL = r"""
INSERT INTO operations.relationship_types (
    key, display_name, description, source_entity_class_id,
    target_entity_class_id, source_cardinality, target_cardinality,
    directed, enabled
) VALUES (
    'peripheral_attached_to_device', 'Peripheral attached to device',
    'A client-owned peripheral is attached to one canonical device.',
    'peripheral', 'device', 'one', 'many', TRUE, TRUE
)
ON CONFLICT (key) DO NOTHING;
"""


TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION operations.validate_relationship_tuple()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    contract relationship_types%ROWTYPE;
    source_row entities%ROWTYPE;
    target_row entities%ROWTYPE;
BEGIN
    SELECT * INTO contract FROM relationship_types WHERE key = NEW.relationship_type_id;
    IF NOT FOUND OR NOT contract.enabled THEN
        RAISE EXCEPTION 'relationship type is missing or disabled';
    END IF;
    SELECT * INTO source_row FROM entities
     WHERE id = NEW.source_entity_id AND tenant_id = NEW.tenant_id;
    SELECT * INTO target_row FROM entities
     WHERE id = NEW.target_entity_id AND tenant_id = NEW.tenant_id;
    IF source_row.id IS NULL OR target_row.id IS NULL THEN
        RAISE EXCEPTION 'relationship endpoints must belong to the decision tenant';
    END IF;
    IF source_row.entity_class_id <> contract.source_entity_class_id
       OR target_row.entity_class_id <> contract.target_entity_class_id THEN
        RAISE EXCEPTION 'relationship endpoint classes do not match the type contract';
    END IF;
    IF NEW.source_entity_id = NEW.target_entity_id THEN
        RAISE EXCEPTION 'relationship endpoints must be distinct';
    END IF;
    IF TG_TABLE_NAME = 'entity_relationships' AND NEW.status = 'active' THEN
        IF contract.source_cardinality = 'one' AND EXISTS (
            SELECT 1 FROM entity_relationships edge
             WHERE edge.tenant_id = NEW.tenant_id
               AND edge.relationship_type_id = NEW.relationship_type_id
               AND edge.source_entity_id = NEW.source_entity_id
               AND edge.target_entity_id <> NEW.target_entity_id
               AND edge.status = 'active'
        ) THEN
            RAISE EXCEPTION 'relationship source cardinality would be exceeded';
        END IF;
        IF contract.target_cardinality = 'one' AND EXISTS (
            SELECT 1 FROM entity_relationships edge
             WHERE edge.tenant_id = NEW.tenant_id
               AND edge.relationship_type_id = NEW.relationship_type_id
               AND edge.target_entity_id = NEW.target_entity_id
               AND edge.source_entity_id <> NEW.source_entity_id
               AND edge.status = 'active'
        ) THEN
            RAISE EXCEPTION 'relationship target cardinality would be exceeded';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.validate_relationship_evidence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    contract relationship_types%ROWTYPE;
    source_class text;
    target_class text;
    policy relationship_authority_policies%ROWTYPE;
BEGIN
    SELECT * INTO contract FROM relationship_types WHERE key = NEW.relationship_type_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'relationship type is missing'; END IF;
    IF NEW.source_entity_id IS NOT NULL THEN
        SELECT entity_class_id INTO source_class FROM entities
         WHERE tenant_id = NEW.tenant_id AND id = NEW.source_entity_id;
        IF source_class IS NULL OR source_class <> contract.source_entity_class_id THEN
            RAISE EXCEPTION 'resolved source endpoint violates relationship type';
        END IF;
    END IF;
    IF NEW.target_entity_id IS NOT NULL THEN
        SELECT entity_class_id INTO target_class FROM entities
         WHERE tenant_id = NEW.tenant_id AND id = NEW.target_entity_id;
        IF target_class IS NULL OR target_class <> contract.target_entity_class_id THEN
            RAISE EXCEPTION 'resolved target endpoint violates relationship type';
        END IF;
    END IF;
    SELECT * INTO policy
      FROM relationship_authority_policies
     WHERE tenant_id = NEW.tenant_id
       AND source_instance_id = NEW.source_instance_id
       AND native_record_type = NEW.native_record_type
       AND relationship_type_id = NEW.relationship_type_id
       AND enabled;
    IF FOUND THEN
        NEW.authority_eligible := policy.eligible;
        NEW.authority_tier := policy.authority_tier;
        NEW.authority_priority := policy.priority;
    ELSE
        NEW.authority_eligible := FALSE;
        NEW.authority_tier := 0;
        NEW.authority_priority := 0;
    END IF;
    IF NEW.source_entity_id IS NOT NULL AND NEW.target_entity_id IS NOT NULL THEN
        NEW.resolution_status := 'resolved';
    ELSIF NEW.source_entity_id IS NOT NULL OR NEW.target_entity_id IS NOT NULL THEN
        NEW.resolution_status := 'partial';
    ELSIF NEW.resolution_status <> 'invalid' THEN
        NEW.resolution_status := 'unresolved';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.queue_relationship_tuple(
    row_tenant bigint, row_type varchar, row_source uuid, row_target uuid,
    queue_reason varchar
) RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
    INSERT INTO entity_relationship_dirty (
        id, tenant_id, version, relationship_type_id, source_entity_id,
        target_entity_id, queued_at, reason
    ) VALUES (
        gen_random_uuid(), row_tenant, 1, row_type, row_source, row_target,
        clock_timestamp(), queue_reason
    )
    ON CONFLICT (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
    DO UPDATE SET queued_at = EXCLUDED.queued_at,
                  reason = EXCLUDED.reason,
                  version = entity_relationship_dirty.version + 1;
$function$;

CREATE OR REPLACE FUNCTION operations.queue_relationship_evidence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' AND ROW(
        OLD.relationship_type_id, OLD.source_entity_id, OLD.target_entity_id,
        OLD.authority_eligible, OLD.authority_tier, OLD.authority_priority,
        OLD.material_hash, OLD.active, OLD.withdrawn_at
    ) IS NOT DISTINCT FROM ROW(
        NEW.relationship_type_id, NEW.source_entity_id, NEW.target_entity_id,
        NEW.authority_eligible, NEW.authority_tier, NEW.authority_priority,
        NEW.material_hash, NEW.active, NEW.withdrawn_at
    ) THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'INSERT' AND OLD.source_entity_id IS NOT NULL
       AND OLD.target_entity_id IS NOT NULL THEN
        PERFORM queue_relationship_tuple(
            OLD.tenant_id, OLD.relationship_type_id, OLD.source_entity_id,
            OLD.target_entity_id, 'evidence_change'
        );
    END IF;
    IF TG_OP <> 'DELETE' AND NEW.source_entity_id IS NOT NULL
       AND NEW.target_entity_id IS NOT NULL THEN
        PERFORM queue_relationship_tuple(
            NEW.tenant_id, NEW.relationship_type_id, NEW.source_entity_id,
            NEW.target_entity_id, 'evidence_change'
        );
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.audit_and_queue_relationship_decision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    row_now entity_relationship_decision_current%ROWTYPE;
    before_safe jsonb;
    after_safe jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN row_now := OLD; ELSE row_now := NEW; END IF;
    before_safe := CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE jsonb_build_object(
        'relationship_type', OLD.relationship_type_id,
        'source_entity_id', OLD.source_entity_id,
        'target_entity_id', OLD.target_entity_id,
        'operation', OLD.operation, 'active', OLD.active, 'reason', OLD.reason
    ) END;
    after_safe := CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE jsonb_build_object(
        'relationship_type', NEW.relationship_type_id,
        'source_entity_id', NEW.source_entity_id,
        'target_entity_id', NEW.target_entity_id,
        'operation', NEW.operation, 'active', NEW.active, 'reason', NEW.reason
    ) END;
    INSERT INTO audit_log (
        audit_id, tenant_id, actor_id, actor_kind, source, action,
        entity_type, entity_id, before_state, after_state, ip_address,
        user_agent, occurred_at
    ) VALUES (
        gen_random_uuid(), row_now.tenant_id, row_now.decided_by_id, 'user',
        'api', 'relationship_decision.' || lower(TG_OP),
        'entity_relationship', row_now.source_entity_id,
        before_safe, after_safe, NULL, '', clock_timestamp()
    );
    PERFORM queue_relationship_tuple(
        row_now.tenant_id, row_now.relationship_type_id,
        row_now.source_entity_id, row_now.target_entity_id,
        'operator_decision'
    );
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.protect_source_event_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
BEGIN
    IF ROW(
        OLD.tenant_id, OLD.version, OLD.source_instance_id, OLD.source_binding_id,
        OLD.external_event_id, OLD.event_type, OLD.event_at, OLD.received_at,
        OLD.subject_external_namespace, OLD.subject_parent_external_namespace,
        OLD.subject_parent_external_id, OLD.subject_external_id,
        OLD.source_actor_id, OLD.source_actor_display, OLD.outcome,
        OLD.raw_event, OLD.raw_hash
    ) IS DISTINCT FROM ROW(
        NEW.tenant_id, NEW.version, NEW.source_instance_id, NEW.source_binding_id,
        NEW.external_event_id, NEW.event_type, NEW.event_at, NEW.received_at,
        NEW.subject_external_namespace, NEW.subject_parent_external_namespace,
        NEW.subject_parent_external_id, NEW.subject_external_id,
        NEW.source_actor_id, NEW.source_actor_display, NEW.outcome,
        NEW.raw_event, NEW.raw_hash
    ) THEN
        RAISE EXCEPTION 'source event evidence is immutable';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE TRIGGER validate_relationship_evidence
BEFORE INSERT OR UPDATE ON operations.entity_relationship_evidence_current
FOR EACH ROW EXECUTE FUNCTION operations.validate_relationship_evidence();
CREATE TRIGGER queue_relationship_evidence
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_relationship_evidence_current
FOR EACH ROW EXECUTE FUNCTION operations.queue_relationship_evidence();
CREATE TRIGGER validate_relationship_decision
BEFORE INSERT OR UPDATE ON operations.entity_relationship_decision_current
FOR EACH ROW EXECUTE FUNCTION operations.validate_relationship_tuple();
CREATE TRIGGER audit_and_queue_relationship_decision
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_relationship_decision_current
FOR EACH ROW EXECUTE FUNCTION operations.audit_and_queue_relationship_decision();
CREATE TRIGGER validate_relationship_dirty
BEFORE INSERT OR UPDATE ON operations.entity_relationship_dirty
FOR EACH ROW EXECUTE FUNCTION operations.validate_relationship_tuple();
CREATE TRIGGER validate_relationship_current
BEFORE INSERT OR UPDATE ON operations.entity_relationships
FOR EACH ROW EXECUTE FUNCTION operations.validate_relationship_tuple();
CREATE TRIGGER protect_source_event_immutable
BEFORE UPDATE ON operations.source_events
FOR EACH ROW EXECUTE FUNCTION operations.protect_source_event_immutable();
"""


PROJECTOR_SQL = r"""
CREATE OR REPLACE FUNCTION operations.sync_entity_relationships(batch_size integer DEFAULT 500)
RETURNS TABLE(processed integer, relationship_writes integer, support_writes integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    projected_at timestamptz := clock_timestamp();
BEGIN
    IF batch_size < 1 OR batch_size > 10000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 10000';
    END IF;
    CREATE TEMP TABLE relationship_projection_batch ON COMMIT DROP AS
    SELECT dirty.*
      FROM entity_relationship_dirty dirty
     ORDER BY dirty.queued_at, dirty.id
     LIMIT batch_size
     FOR UPDATE SKIP LOCKED;
    GET DIAGNOSTICS processed = ROW_COUNT;
    IF processed = 0 THEN
        relationship_writes := 0;
        support_writes := 0;
        RETURN NEXT;
        RETURN;
    END IF;

    CREATE TEMP TABLE desired_relationships ON COMMIT DROP AS
    WITH inputs AS (
        SELECT batch.tenant_id, batch.relationship_type_id,
               batch.source_entity_id, batch.target_entity_id,
               decision.id AS decision_id, decision.operation,
               evidence.authority_tier, evidence.authority_priority,
               evidence.evidence_ids
          FROM relationship_projection_batch batch
          LEFT JOIN entity_relationship_decision_current decision
            ON decision.tenant_id = batch.tenant_id
           AND decision.relationship_type_id = batch.relationship_type_id
           AND decision.source_entity_id = batch.source_entity_id
           AND decision.target_entity_id = batch.target_entity_id
           AND decision.active
          LEFT JOIN LATERAL (
              WITH ranked AS (
                  SELECT item.*,
                         dense_rank() OVER (
                             ORDER BY item.authority_tier DESC,
                                      item.authority_priority DESC
                         ) AS authority_rank
                    FROM entity_relationship_evidence_current item
                   WHERE item.tenant_id = batch.tenant_id
                     AND item.relationship_type_id = batch.relationship_type_id
                     AND item.source_entity_id = batch.source_entity_id
                     AND item.target_entity_id = batch.target_entity_id
                     AND item.active AND item.authority_eligible
                     AND item.resolution_status = 'resolved'
              )
              SELECT MAX(authority_tier) AS authority_tier,
                     MAX(authority_priority) AS authority_priority,
                     string_agg(id::text, ',' ORDER BY id) AS evidence_ids
                FROM ranked WHERE authority_rank = 1
          ) evidence ON TRUE
    )
    SELECT inputs.*,
           CASE WHEN operation = 'include' THEN 'active'
                WHEN operation = 'exclude' THEN 'suppressed'
                WHEN evidence_ids IS NOT NULL THEN 'active'
                ELSE 'no_evidence' END AS status,
           CASE WHEN operation = 'include' THEN 'operator_include'
                WHEN operation = 'exclude' THEN 'operator_exclude'
                WHEN evidence_ids IS NOT NULL THEN 'source_authority'
                ELSE 'no_eligible_evidence' END AS selection_reason,
           pg_catalog.sha256(convert_to(concat_ws('|',
               COALESCE(decision_id::text, ''), COALESCE(operation, ''),
               COALESCE(authority_tier::text, ''),
               COALESCE(authority_priority::text, ''),
               COALESCE(evidence_ids, '')
           ), 'UTF8')) AS input_hash
      FROM inputs;

    INSERT INTO entity_relationships (
        id, tenant_id, version, relationship_type_id, source_entity_id,
        target_entity_id, status, selection_reason, selected_authority_tier,
        selected_authority_priority, input_hash, projected_at
    )
    SELECT gen_random_uuid(), desired.tenant_id, 1,
           desired.relationship_type_id, desired.source_entity_id,
           desired.target_entity_id, desired.status, desired.selection_reason,
           CASE WHEN desired.selection_reason = 'source_authority'
                THEN desired.authority_tier END,
           CASE WHEN desired.selection_reason = 'source_authority'
                THEN desired.authority_priority END,
           desired.input_hash, projected_at
      FROM desired_relationships desired
    ON CONFLICT (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
    DO UPDATE SET status = EXCLUDED.status,
                  selection_reason = EXCLUDED.selection_reason,
                  selected_authority_tier = EXCLUDED.selected_authority_tier,
                  selected_authority_priority = EXCLUDED.selected_authority_priority,
                  input_hash = EXCLUDED.input_hash,
                  projected_at = EXCLUDED.projected_at,
                  version = entity_relationships.version + 1
      WHERE entity_relationships.input_hash IS DISTINCT FROM EXCLUDED.input_hash;
    GET DIAGNOSTICS relationship_writes = ROW_COUNT;

    DELETE FROM entity_relationship_evidence_support support
    USING entity_relationships edge, relationship_projection_batch batch
    WHERE support.tenant_id = edge.tenant_id
      AND support.relationship_id = edge.id
      AND edge.tenant_id = batch.tenant_id
      AND edge.relationship_type_id = batch.relationship_type_id
      AND edge.source_entity_id = batch.source_entity_id
      AND edge.target_entity_id = batch.target_entity_id;

    INSERT INTO entity_relationship_evidence_support (
        id, tenant_id, relationship_id, evidence_id
    )
    SELECT gen_random_uuid(), edge.tenant_id, edge.id, evidence.id
      FROM desired_relationships desired
      JOIN entity_relationships edge
        ON edge.tenant_id = desired.tenant_id
       AND edge.relationship_type_id = desired.relationship_type_id
       AND edge.source_entity_id = desired.source_entity_id
       AND edge.target_entity_id = desired.target_entity_id
      JOIN entity_relationship_evidence_current evidence
        ON evidence.tenant_id = desired.tenant_id
       AND evidence.relationship_type_id = desired.relationship_type_id
       AND evidence.source_entity_id = desired.source_entity_id
       AND evidence.target_entity_id = desired.target_entity_id
       AND evidence.active AND evidence.authority_eligible
       AND evidence.resolution_status = 'resolved'
       AND evidence.authority_tier = desired.authority_tier
       AND evidence.authority_priority = desired.authority_priority
     WHERE desired.selection_reason = 'source_authority';
    GET DIAGNOSTICS support_writes = ROW_COUNT;

    DELETE FROM entity_relationship_dirty dirty
    USING relationship_projection_batch batch
    WHERE dirty.id = batch.id;
    RETURN NEXT;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.sync_entity_candidates(batch_size integer DEFAULT 500)
RETURNS TABLE(created integer, reopened integer, attached integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
BEGIN
    IF batch_size < 1 OR batch_size > 10000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 10000';
    END IF;
    created := 0; reopened := 0; attached := 0;

    WITH eligible AS (
        SELECT observation.*, entity_type.entity_class_id,
               CASE WHEN COALESCE(bool_or(
                    policy.enabled AND policy.may_establish_identity
               ), FALSE) THEN 'pending' ELSE 'observed_only' END AS desired_status
          FROM entity_observation_current observation
          JOIN entity_types entity_type ON entity_type.name = observation.entity_type
          LEFT JOIN identity_authority_policies policy
            ON policy.tenant_id = observation.tenant_id
           AND policy.source_instance_id = observation.source_instance_id
           AND policy.native_record_type = observation.entity_type
           AND policy.resulting_entity_type_id = entity_type.name
         WHERE observation.active
           AND NOT EXISTS (
               SELECT 1 FROM entity_source_links link
                WHERE link.tenant_id = observation.tenant_id
                  AND link.source_instance_id = observation.source_instance_id
                  AND link.external_namespace = observation.external_namespace
                  AND link.parent_external_namespace = observation.parent_external_namespace
                  AND link.parent_external_id = observation.parent_external_id
                  AND link.external_id = observation.external_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM entity_candidates candidate
                WHERE candidate.tenant_id = observation.tenant_id
                  AND candidate.source_instance_id = observation.source_instance_id
                  AND candidate.external_namespace = observation.external_namespace
                  AND candidate.parent_external_namespace =
                      observation.parent_external_namespace
                  AND candidate.parent_external_id = observation.parent_external_id
                  AND candidate.external_id = observation.external_id
                  AND candidate.proposed_entity_class_id = entity_type.entity_class_id
           )
         GROUP BY observation.observation_id, entity_type.entity_class_id
         ORDER BY observation.last_seen_at, observation.observation_id
         LIMIT batch_size
    ), inserted AS (
        INSERT INTO entity_candidates (
            id, tenant_id, version, source_instance_id, proposed_entity_class_id,
            client_id, external_namespace, parent_external_namespace,
            parent_external_id, external_id, status, material_hash,
            first_observed_at, last_observed_at
        )
        SELECT gen_random_uuid(), eligible.tenant_id, 1, eligible.source_instance_id,
               eligible.entity_class_id, eligible.client_id,
               eligible.external_namespace, eligible.parent_external_namespace,
               eligible.parent_external_id, eligible.external_id,
               eligible.desired_status, eligible.material_hash,
               eligible.observed_at, eligible.last_seen_at
          FROM eligible
        ON CONFLICT (tenant_id, source_instance_id, external_namespace,
                     parent_external_namespace, parent_external_id, external_id,
                     proposed_entity_class_id) DO NOTHING
        RETURNING *
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), inserted.tenant_id, 1, inserted.id,
               'create', 'system', 'generic_candidate_projector',
               'unattached source identity', NULL,
               jsonb_build_object('status', inserted.status), clock_timestamp()
          FROM inserted
        RETURNING 1
    ) SELECT count(*)::integer INTO created FROM events;

    WITH changed AS (
        SELECT candidate.id, candidate.tenant_id, candidate.status AS old_status,
               observation.material_hash, observation.last_seen_at,
               CASE WHEN COALESCE(bool_or(
                    policy.enabled AND policy.may_establish_identity
               ), FALSE) THEN 'pending' ELSE 'observed_only' END AS desired_status
          FROM entity_candidates candidate
          JOIN entity_observation_current observation
            ON observation.tenant_id = candidate.tenant_id
           AND observation.source_instance_id = candidate.source_instance_id
           AND observation.external_namespace = candidate.external_namespace
           AND observation.parent_external_namespace = candidate.parent_external_namespace
           AND observation.parent_external_id = candidate.parent_external_id
           AND observation.external_id = candidate.external_id
          JOIN entity_types entity_type
            ON entity_type.name = observation.entity_type
           AND entity_type.entity_class_id = candidate.proposed_entity_class_id
          LEFT JOIN identity_authority_policies policy
            ON policy.tenant_id = observation.tenant_id
           AND policy.source_instance_id = observation.source_instance_id
           AND policy.native_record_type = observation.entity_type
           AND policy.resulting_entity_type_id = entity_type.name
         WHERE observation.active
           AND candidate.status IN ('rejected', 'observed_only', 'pending')
           AND candidate.material_hash IS DISTINCT FROM observation.material_hash
         GROUP BY candidate.id, candidate.tenant_id, candidate.status,
                  observation.material_hash, observation.last_seen_at
         ORDER BY observation.last_seen_at, candidate.id
         LIMIT batch_size
    ), updated AS (
        UPDATE entity_candidates candidate
           SET status = changed.desired_status,
               material_hash = changed.material_hash,
               last_observed_at = changed.last_seen_at,
               latest_decision = '', latest_decision_reason = '',
               latest_decided_by_id = NULL, latest_decided_at = NULL,
               version = candidate.version + 1
          FROM changed WHERE candidate.id = changed.id
        RETURNING candidate.*, changed.old_status
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), updated.tenant_id, 1, updated.id,
               'reopen', 'system', 'generic_candidate_projector',
               'material source evidence changed',
               jsonb_build_object('status', updated.old_status),
               jsonb_build_object('status', updated.status), clock_timestamp()
          FROM updated RETURNING 1
    ) SELECT count(*)::integer INTO reopened FROM events;

    WITH linked AS (
        SELECT candidate.id, candidate.tenant_id, candidate.status AS old_status,
               link.entity_id
          FROM entity_candidates candidate
          JOIN entity_source_links link
            ON link.tenant_id = candidate.tenant_id
           AND link.source_instance_id = candidate.source_instance_id
           AND link.external_namespace = candidate.external_namespace
           AND link.parent_external_namespace = candidate.parent_external_namespace
           AND link.parent_external_id = candidate.parent_external_id
           AND link.external_id = candidate.external_id
         WHERE candidate.status <> 'attached'
         ORDER BY candidate.id LIMIT batch_size
    ), updated AS (
        UPDATE entity_candidates candidate
           SET status = 'attached', resolved_entity_id = linked.entity_id,
               latest_decision = 'attached',
               latest_decision_reason = 'authoritative source link exists',
               latest_decided_at = clock_timestamp(),
               version = candidate.version + 1
          FROM linked WHERE candidate.id = linked.id
        RETURNING candidate.*, linked.old_status
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), updated.tenant_id, 1, updated.id,
               'attach', 'system', 'generic_candidate_projector',
               'authoritative source link exists',
               jsonb_build_object('status', updated.old_status),
               jsonb_build_object('status', 'attached'), clock_timestamp()
          FROM updated RETURNING 1
    ) SELECT count(*)::integer INTO attached FROM events;
    RETURN NEXT;
END;
$function$;
"""


SECURITY_SQL = r"""
REVOKE ALL ON operations.relationship_types,
    operations.relationship_authority_policies,
    operations.entity_relationship_evidence_current,
    operations.entity_relationship_dirty,
    operations.entity_relationship_decision_current,
    operations.entity_relationships,
    operations.entity_relationship_evidence_support,
    operations.source_events FROM PUBLIC;

GRANT SELECT ON operations.relationship_types
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.relationship_authority_policies
    TO operations_app, ninja_ingest, operations_readonly;
GRANT SELECT, INSERT, UPDATE ON operations.entity_relationship_evidence_current
    TO ninja_ingest;
GRANT SELECT, INSERT, UPDATE ON operations.entity_relationship_decision_current
    TO operations_app;
GRANT UPDATE ON operations.entity_candidates TO operations_app;
GRANT INSERT ON operations.entity_candidate_events TO operations_app;
GRANT INSERT, UPDATE ON operations.entity_source_links TO operations_app;
GRANT INSERT ON operations.entity_source_link_history TO operations_app;
GRANT SELECT ON operations.entity_relationships,
    operations.entity_relationship_evidence_support TO operations_app;
GRANT SELECT, INSERT, UPDATE ON operations.source_events TO ninja_ingest;

REVOKE ALL ON FUNCTION operations.validate_relationship_tuple() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.validate_relationship_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.queue_relationship_tuple(bigint, varchar, uuid, uuid, varchar)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.queue_relationship_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.audit_and_queue_relationship_decision() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.protect_source_event_immutable() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.sync_entity_relationships(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.sync_entity_candidates(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.sync_entity_relationships(integer)
    TO ninja_ingest, operations_app;
GRANT EXECUTE ON FUNCTION operations.sync_entity_candidates(integer)
    TO ninja_ingest, operations_app;

ALTER FUNCTION operations.validate_relationship_tuple() OWNER TO operations_migrate;
ALTER FUNCTION operations.validate_relationship_evidence() OWNER TO operations_migrate;
ALTER FUNCTION operations.queue_relationship_tuple(bigint, varchar, uuid, uuid, varchar)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.queue_relationship_evidence() OWNER TO operations_migrate;
ALTER FUNCTION operations.audit_and_queue_relationship_decision() OWNER TO operations_migrate;
ALTER FUNCTION operations.protect_source_event_immutable() OWNER TO operations_migrate;
ALTER FUNCTION operations.sync_entity_relationships(integer) OWNER TO operations_migrate;
ALTER FUNCTION operations.sync_entity_candidates(integer) OWNER TO operations_migrate;

ALTER TABLE operations.relationship_types OWNER TO operations_migrate;
ALTER TABLE operations.relationship_authority_policies OWNER TO operations_migrate;
ALTER TABLE operations.entity_relationship_evidence_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_relationship_dirty OWNER TO operations_migrate;
ALTER TABLE operations.entity_relationship_decision_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_relationships OWNER TO operations_migrate;
ALTER TABLE operations.entity_relationship_evidence_support OWNER TO operations_migrate;
ALTER TABLE operations.source_events OWNER TO operations_migrate;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS validate_relationship_current ON operations.entity_relationships;
DROP TRIGGER IF EXISTS protect_source_event_immutable ON operations.source_events;
DROP TRIGGER IF EXISTS validate_relationship_dirty ON operations.entity_relationship_dirty;
DROP TRIGGER IF EXISTS audit_and_queue_relationship_decision
    ON operations.entity_relationship_decision_current;
DROP TRIGGER IF EXISTS validate_relationship_decision
    ON operations.entity_relationship_decision_current;
DROP TRIGGER IF EXISTS queue_relationship_evidence
    ON operations.entity_relationship_evidence_current;
DROP TRIGGER IF EXISTS validate_relationship_evidence
    ON operations.entity_relationship_evidence_current;
DROP FUNCTION IF EXISTS operations.sync_entity_candidates(integer);
DROP FUNCTION IF EXISTS operations.sync_entity_relationships(integer);
DROP FUNCTION IF EXISTS operations.audit_and_queue_relationship_decision();
DROP FUNCTION IF EXISTS operations.protect_source_event_immutable();
DROP FUNCTION IF EXISTS operations.queue_relationship_evidence();
DROP FUNCTION IF EXISTS operations.queue_relationship_tuple(bigint, varchar, uuid, uuid, varchar);
DROP FUNCTION IF EXISTS operations.validate_relationship_evidence();
DROP FUNCTION IF EXISTS operations.validate_relationship_tuple();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0110_relationshiptype_entityrelationshipevidencecurrent_and_more"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(TENANT_CONSTRAINTS_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(RLS_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(SEED_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(TRIGGER_SQL, REVERSE_SQL),
        migrations.RunSQL(PROJECTOR_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
    ]
