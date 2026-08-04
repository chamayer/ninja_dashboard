"""Secure, audited, dirty-key effective attribute projection."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations

CLAIM_PROJECTOR_SQL = import_module(f"{__package__}.0103_attribute_claim_projection").PROJECTOR_SQL


SETUP_SQL = r"""
ALTER TABLE operations.users
    ADD CONSTRAINT uq_users_tenant_id UNIQUE (tenant_id, id);
ALTER TABLE operations.attribute_definitions
    ADD CONSTRAINT uq_attr_defs_id_class UNIQUE (id, entity_class_id);

ALTER TABLE operations.entity_attribute_decision_current
    ADD CONSTRAINT fk_attr_decision_tenant_entity_class
        FOREIGN KEY (tenant_id, entity_id, entity_class_id)
        REFERENCES operations.entities (tenant_id, id, entity_class_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_decision_typed_definition
        FOREIGN KEY (attribute_definition_id, value_type, cardinality)
        REFERENCES operations.attribute_definitions (id, value_type, cardinality)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_decision_definition_class
        FOREIGN KEY (attribute_definition_id, entity_class_id)
        REFERENCES operations.attribute_definitions (id, entity_class_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_decision_tenant_actor
        FOREIGN KEY (tenant_id, decided_by_id)
        REFERENCES operations.users (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_decision_tenant_value_entity
        FOREIGN KEY (tenant_id, value_entity_id)
        REFERENCES operations.entities (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_decision_member_current
    ADD CONSTRAINT fk_attr_decision_member_tenant_decision
        FOREIGN KEY (tenant_id, decision_id)
        REFERENCES operations.entity_attribute_decision_current (tenant_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_decision_member_tenant_value_entity
        FOREIGN KEY (tenant_id, value_entity_id)
        REFERENCES operations.entities (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_effective_dirty
    ADD CONSTRAINT fk_attr_effective_dirty_tenant_entity_class
        FOREIGN KEY (tenant_id, entity_id, entity_class_id)
        REFERENCES operations.entities (tenant_id, id, entity_class_id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_dirty_definition_class
        FOREIGN KEY (attribute_definition_id, entity_class_id)
        REFERENCES operations.attribute_definitions (id, entity_class_id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_effective_current
    ADD CONSTRAINT fk_attr_effective_tenant_entity_class
        FOREIGN KEY (tenant_id, entity_id, entity_class_id)
        REFERENCES operations.entities (tenant_id, id, entity_class_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_typed_definition
        FOREIGN KEY (attribute_definition_id, value_type, cardinality)
        REFERENCES operations.attribute_definitions (id, value_type, cardinality)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_definition_class
        FOREIGN KEY (attribute_definition_id, entity_class_id)
        REFERENCES operations.attribute_definitions (id, entity_class_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_tenant_value_entity
        FOREIGN KEY (tenant_id, value_entity_id)
        REFERENCES operations.entities (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_effective_member_current
    ADD CONSTRAINT fk_attr_effective_member_tenant_effective
        FOREIGN KEY (tenant_id, effective_id)
        REFERENCES operations.entity_attribute_effective_current (tenant_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_member_tenant_value_entity
        FOREIGN KEY (tenant_id, value_entity_id)
        REFERENCES operations.entities (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_effective_claim_support
    ADD CONSTRAINT fk_attr_effective_support_tenant_effective
        FOREIGN KEY (tenant_id, effective_id)
        REFERENCES operations.entity_attribute_effective_current (tenant_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_support_tenant_member
        FOREIGN KEY (tenant_id, effective_member_id)
        REFERENCES operations.entity_attribute_effective_member_current (tenant_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_effective_support_tenant_claim
        FOREIGN KEY (tenant_id, claim_id)
        REFERENCES operations.entity_attribute_claim_current (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_conflict_current
    ADD CONSTRAINT fk_attr_conflict_tenant_entity_class
        FOREIGN KEY (tenant_id, entity_id, entity_class_id)
        REFERENCES operations.entities (tenant_id, id, entity_class_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_conflict_definition_class
        FOREIGN KEY (attribute_definition_id, entity_class_id)
        REFERENCES operations.attribute_definitions (id, entity_class_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_conflict_claim_support
    ADD CONSTRAINT fk_attr_conflict_support_tenant_conflict
        FOREIGN KEY (tenant_id, conflict_id)
        REFERENCES operations.entity_attribute_conflict_current (tenant_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_conflict_support_tenant_claim
        FOREIGN KEY (tenant_id, claim_id)
        REFERENCES operations.entity_attribute_claim_current (tenant_id, id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_decision_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_decision_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_decision_member_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_decision_member_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_dirty ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_dirty FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_member_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_member_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_claim_support ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_effective_claim_support FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_conflict_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_conflict_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_conflict_claim_support ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_conflict_claim_support FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON operations.entity_attribute_decision_current
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_decision_member_current
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_effective_dirty
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_effective_current
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_effective_member_current
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_effective_claim_support
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_conflict_current
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_conflict_claim_support
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);

CREATE OR REPLACE FUNCTION operations.validate_attribute_decision_member()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    parent entity_attribute_decision_current%ROWTYPE;
BEGIN
    SELECT * INTO parent
    FROM entity_attribute_decision_current
    WHERE id = NEW.decision_id AND tenant_id = NEW.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'decision member tenant/parent mismatch';
    END IF;
    IF parent.cardinality <> 'set' OR parent.value_type <> NEW.value_type THEN
        RAISE EXCEPTION 'decision member does not match set definition';
    END IF;
    IF parent.operation = 'replace' AND NEW.action <> 'add' THEN
        RAISE EXCEPTION 'replace-set decisions accept only add members';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.audit_and_queue_attribute_decision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    before_safe jsonb;
    after_safe jsonb;
    row_now entity_attribute_decision_current%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        row_now := OLD;
    ELSE
        row_now := NEW;
    END IF;
    before_safe := CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE jsonb_build_object(
        'operation', OLD.operation, 'active', OLD.active,
        'attribute_definition_id', OLD.attribute_definition_id,
        'value_fingerprint', CASE WHEN OLD.value_fingerprint IS NULL THEN NULL
            ELSE encode(OLD.value_fingerprint, 'hex') END,
        'version', OLD.version, 'reason', OLD.reason
    ) END;
    after_safe := CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE jsonb_build_object(
        'operation', NEW.operation, 'active', NEW.active,
        'attribute_definition_id', NEW.attribute_definition_id,
        'value_fingerprint', CASE WHEN NEW.value_fingerprint IS NULL THEN NULL
            ELSE encode(NEW.value_fingerprint, 'hex') END,
        'version', NEW.version, 'reason', NEW.reason
    ) END;
    INSERT INTO audit_log (
        audit_id, tenant_id, actor_id, actor_kind, source, action,
        entity_type, entity_id, before_state, after_state, ip_address,
        user_agent, occurred_at
    ) VALUES (
        gen_random_uuid(), row_now.tenant_id, row_now.decided_by_id, 'user',
        'api', 'attribute_decision.' || lower(TG_OP),
        'entity_attribute_decision', row_now.entity_id,
        before_safe, after_safe, NULL, '', clock_timestamp()
    );
    INSERT INTO entity_attribute_effective_dirty (
        id, tenant_id, version, entity_id, entity_class_id,
        attribute_definition_id, queued_at, reason
    ) VALUES (
        gen_random_uuid(), row_now.tenant_id, 1, row_now.entity_id,
        row_now.entity_class_id, row_now.attribute_definition_id,
        clock_timestamp(), 'operator_decision'
    )
    ON CONFLICT (tenant_id, entity_id, attribute_definition_id) DO UPDATE SET
        entity_class_id = EXCLUDED.entity_class_id,
        queued_at = EXCLUDED.queued_at,
        reason = EXCLUDED.reason,
        version = entity_attribute_effective_dirty.version + 1;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.audit_and_queue_attribute_decision_member()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    parent entity_attribute_decision_current%ROWTYPE;
    member_now entity_attribute_decision_member_current%ROWTYPE;
    before_safe jsonb;
    after_safe jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN member_now := OLD; ELSE member_now := NEW; END IF;
    SELECT * INTO parent
    FROM entity_attribute_decision_current
    WHERE id = member_now.decision_id AND tenant_id = member_now.tenant_id;
    IF NOT FOUND THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;
    before_safe := CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE jsonb_build_object(
        'action', OLD.action, 'attribute_definition_id', parent.attribute_definition_id,
        'value_fingerprint', encode(OLD.value_fingerprint, 'hex')
    ) END;
    after_safe := CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE jsonb_build_object(
        'action', NEW.action, 'attribute_definition_id', parent.attribute_definition_id,
        'value_fingerprint', encode(NEW.value_fingerprint, 'hex')
    ) END;
    INSERT INTO audit_log (
        audit_id, tenant_id, actor_id, actor_kind, source, action,
        entity_type, entity_id, before_state, after_state, ip_address,
        user_agent, occurred_at
    ) VALUES (
        gen_random_uuid(), parent.tenant_id, parent.decided_by_id, 'user',
        'api', 'attribute_decision_member.' || lower(TG_OP),
        'entity_attribute_decision', parent.entity_id,
        before_safe, after_safe, NULL, '', clock_timestamp()
    );
    INSERT INTO entity_attribute_effective_dirty (
        id, tenant_id, version, entity_id, entity_class_id,
        attribute_definition_id, queued_at, reason
    ) VALUES (
        gen_random_uuid(), parent.tenant_id, 1, parent.entity_id,
        parent.entity_class_id, parent.attribute_definition_id,
        clock_timestamp(), 'operator_decision'
    )
    ON CONFLICT (tenant_id, entity_id, attribute_definition_id) DO UPDATE SET
        queued_at = EXCLUDED.queued_at,
        reason = EXCLUDED.reason,
        version = entity_attribute_effective_dirty.version + 1;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$function$;

CREATE TRIGGER validate_attribute_decision_member
BEFORE INSERT OR UPDATE ON operations.entity_attribute_decision_member_current
FOR EACH ROW EXECUTE FUNCTION operations.validate_attribute_decision_member();
CREATE TRIGGER audit_and_queue_attribute_decision
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_attribute_decision_current
FOR EACH ROW EXECUTE FUNCTION operations.audit_and_queue_attribute_decision();
CREATE TRIGGER audit_and_queue_attribute_decision_member
AFTER INSERT OR UPDATE OR DELETE ON operations.entity_attribute_decision_member_current
FOR EACH ROW EXECUTE FUNCTION operations.audit_and_queue_attribute_decision_member();

INSERT INTO operations.entity_attribute_effective_dirty (
    id, tenant_id, version, entity_id, entity_class_id,
    attribute_definition_id, queued_at, reason
)
SELECT gen_random_uuid(), claim.tenant_id, 1, claim.entity_id,
       claim.entity_class_id, claim.attribute_definition_id,
       clock_timestamp(), 'initial_backfill'
FROM operations.entity_attribute_claim_current claim
GROUP BY claim.tenant_id, claim.entity_id, claim.entity_class_id,
         claim.attribute_definition_id
ON CONFLICT (tenant_id, entity_id, attribute_definition_id) DO NOTHING;
"""


PROJECTOR_SQL = r"""
CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_effective(batch_size integer DEFAULT 500)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    projected_at timestamptz := clock_timestamp();
    batch_rows integer := 0;
    effective_writes integer := 0;
    member_writes integer := 0;
    support_writes integer := 0;
    conflict_rows integer := 0;
    conflict_support_writes integer := 0;
BEGIN
    IF batch_size < 1 OR batch_size > 5000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 5000';
    END IF;
    IF NOT pg_try_advisory_xact_lock(
        hashtextextended('operations.attribute_effective_projection', 0)
    ) THEN
        RETURN jsonb_build_object('status', 'busy', 'processed', 0);
    END IF;

    DROP TABLE IF EXISTS pg_temp.effective_projection_batch;
    CREATE TEMP TABLE effective_projection_batch ON COMMIT DROP AS
    SELECT dirty.id AS dirty_id, dirty.tenant_id, dirty.entity_id,
           entity.entity_class_id, dirty.attribute_definition_id,
           definition.value_type, definition.cardinality,
           definition.single_value_conflict_policy,
           definition.set_merge_policy, definition.enabled,
           previous.id AS previous_id, previous.status AS previous_status,
           previous.selection_reason AS previous_selection_reason,
           previous.value_text AS previous_value_text,
           previous.value_number AS previous_value_number,
           previous.value_boolean AS previous_value_boolean,
           previous.value_timestamp AS previous_value_timestamp,
           previous.value_entity_id AS previous_value_entity_id,
           previous.value_json AS previous_value_json,
           previous.value_fingerprint AS previous_value_fingerprint,
           previous.selected_authority_tier AS previous_authority_tier,
           previous.selected_authority_priority AS previous_authority_priority,
           pg_catalog.sha256(convert_to(
               'definition:' || definition.definition_version::text
               || ':' || definition.enabled::text
               || ':' || definition.single_value_conflict_policy
               || ':' || definition.set_merge_policy
               || ':' || COALESCE(signatures.signature_text, 'empty'),
               'UTF8'
           )) AS input_hash
    FROM entity_attribute_effective_dirty dirty
    JOIN entities entity
      ON entity.tenant_id = dirty.tenant_id AND entity.id = dirty.entity_id
    JOIN attribute_definitions definition
      ON definition.id = dirty.attribute_definition_id
    LEFT JOIN entity_attribute_effective_current previous
      ON previous.tenant_id = dirty.tenant_id
     AND previous.entity_id = dirty.entity_id
     AND previous.attribute_definition_id = dirty.attribute_definition_id
    LEFT JOIN LATERAL (
        SELECT string_agg(signature, '|' ORDER BY signature) AS signature_text
        FROM (
            SELECT 'claim:' || claim.id::text || ':'
                   || encode(claim.value_fingerprint, 'hex') || ':'
                   || claim.authority_eligible::text || ':'
                   || claim.authority_tier::text || ':'
                   || claim.authority_priority::text AS signature
            FROM entity_attribute_claim_current claim
            WHERE claim.tenant_id = dirty.tenant_id
              AND claim.entity_id = dirty.entity_id
              AND claim.attribute_definition_id = dirty.attribute_definition_id
              AND claim.active
            UNION ALL
            SELECT 'decision:' || decision.id::text || ':'
                   || decision.version::text || ':' || decision.active::text
                   || ':' || decision.operation || ':'
                   || COALESCE(encode(decision.value_fingerprint, 'hex'), '')
            FROM entity_attribute_decision_current decision
            WHERE decision.tenant_id = dirty.tenant_id
              AND decision.entity_id = dirty.entity_id
              AND decision.attribute_definition_id = dirty.attribute_definition_id
            UNION ALL
            SELECT 'member:' || member.id::text || ':' || member.version::text
                   || ':' || member.action || ':'
                   || encode(member.value_fingerprint, 'hex')
            FROM entity_attribute_decision_member_current member
            JOIN entity_attribute_decision_current decision
              ON decision.tenant_id = member.tenant_id
             AND decision.id = member.decision_id
            WHERE decision.tenant_id = dirty.tenant_id
              AND decision.entity_id = dirty.entity_id
              AND decision.attribute_definition_id = dirty.attribute_definition_id
        ) signature_rows
    ) signatures ON TRUE
    ORDER BY dirty.queued_at, dirty.id
    LIMIT batch_size
    FOR UPDATE OF dirty SKIP LOCKED;
    GET DIAGNOSTICS batch_rows = ROW_COUNT;

    IF batch_rows = 0 THEN
        RETURN jsonb_build_object(
            'status', 'complete', 'processed', 0, 'effective_writes', 0,
            'member_writes', 0, 'support_writes', 0, 'conflicts', 0,
            'conflict_support_writes', 0
        );
    END IF;

    DROP TABLE IF EXISTS pg_temp.effective_top_claims;
    CREATE TEMP TABLE effective_top_claims ON COMMIT DROP AS
    SELECT ranked.*
    FROM (
        SELECT claim.*,
               dense_rank() OVER (
                   PARTITION BY claim.tenant_id, claim.entity_id,
                                claim.attribute_definition_id
                   ORDER BY claim.authority_tier DESC,
                            claim.authority_priority DESC
               ) AS authority_rank
        FROM entity_attribute_claim_current claim
        JOIN effective_projection_batch batch
          ON batch.tenant_id = claim.tenant_id
         AND batch.entity_id = claim.entity_id
         AND batch.attribute_definition_id = claim.attribute_definition_id
        WHERE claim.active AND claim.authority_eligible AND batch.enabled
    ) ranked
    WHERE ranked.authority_rank = 1;

    DROP TABLE IF EXISTS pg_temp.effective_conflicts;
    CREATE TEMP TABLE effective_conflicts ON COMMIT DROP AS
    SELECT claim.tenant_id, claim.entity_id, claim.entity_class_id,
           claim.attribute_definition_id, MAX(claim.authority_tier) AS authority_tier,
           MAX(claim.authority_priority) AS authority_priority,
           COUNT(DISTINCT claim.value_fingerprint)::integer AS conflicting_value_count
    FROM effective_top_claims claim
    JOIN effective_projection_batch batch
      ON batch.tenant_id = claim.tenant_id
     AND batch.entity_id = claim.entity_id
     AND batch.attribute_definition_id = claim.attribute_definition_id
    WHERE batch.cardinality = 'single'
    GROUP BY claim.tenant_id, claim.entity_id, claim.entity_class_id,
             claim.attribute_definition_id
    HAVING COUNT(DISTINCT claim.value_fingerprint) > 1;

    DELETE FROM entity_attribute_conflict_claim_support support
    USING entity_attribute_conflict_current conflict,
          effective_projection_batch batch
    WHERE support.tenant_id = conflict.tenant_id
      AND support.conflict_id = conflict.id
      AND conflict.tenant_id = batch.tenant_id
      AND conflict.entity_id = batch.entity_id
      AND conflict.attribute_definition_id = batch.attribute_definition_id;

    DELETE FROM entity_attribute_conflict_current conflict
    USING effective_projection_batch batch
    WHERE conflict.tenant_id = batch.tenant_id
      AND conflict.entity_id = batch.entity_id
      AND conflict.attribute_definition_id = batch.attribute_definition_id
      AND NOT EXISTS (
          SELECT 1 FROM effective_conflicts current_conflict
          WHERE current_conflict.tenant_id = conflict.tenant_id
            AND current_conflict.entity_id = conflict.entity_id
            AND current_conflict.attribute_definition_id = conflict.attribute_definition_id
      );

    INSERT INTO entity_attribute_conflict_current (
        id, tenant_id, version, entity_id, entity_class_id,
        attribute_definition_id, conflict_kind, authority_tier,
        authority_priority, conflicting_value_count,
        first_detected_at, last_detected_at
    )
    SELECT gen_random_uuid(), conflict.tenant_id, 1, conflict.entity_id,
           conflict.entity_class_id, conflict.attribute_definition_id,
           'equal_authority', conflict.authority_tier,
           conflict.authority_priority, conflict.conflicting_value_count,
           projected_at, projected_at
    FROM effective_conflicts conflict
    ON CONFLICT (tenant_id, entity_id, attribute_definition_id) DO UPDATE SET
        entity_class_id = EXCLUDED.entity_class_id,
        authority_tier = EXCLUDED.authority_tier,
        authority_priority = EXCLUDED.authority_priority,
        conflicting_value_count = EXCLUDED.conflicting_value_count,
        last_detected_at = EXCLUDED.last_detected_at,
        version = entity_attribute_conflict_current.version + 1;

    INSERT INTO entity_attribute_conflict_claim_support (
        id, tenant_id, conflict_id, claim_id
    )
    SELECT gen_random_uuid(), claim.tenant_id, conflict.id, claim.id
    FROM effective_top_claims claim
    JOIN entity_attribute_conflict_current conflict
      ON conflict.tenant_id = claim.tenant_id
     AND conflict.entity_id = claim.entity_id
     AND conflict.attribute_definition_id = claim.attribute_definition_id
    JOIN effective_projection_batch batch
      ON batch.tenant_id = claim.tenant_id
     AND batch.entity_id = claim.entity_id
     AND batch.attribute_definition_id = claim.attribute_definition_id
    WHERE batch.cardinality = 'single';
    GET DIAGNOSTICS conflict_support_writes = ROW_COUNT;

    DROP TABLE IF EXISTS pg_temp.effective_source_set_claims;
    CREATE TEMP TABLE effective_source_set_claims ON COMMIT DROP AS
    WITH ranked AS (
        SELECT claim.*,
               dense_rank() OVER (
                   PARTITION BY claim.tenant_id, claim.entity_id,
                                claim.attribute_definition_id
                   ORDER BY claim.authority_tier DESC,
                            claim.authority_priority DESC
               ) AS authority_rank
        FROM entity_attribute_claim_current claim
        JOIN effective_projection_batch batch
          ON batch.tenant_id = claim.tenant_id
         AND batch.entity_id = claim.entity_id
         AND batch.attribute_definition_id = claim.attribute_definition_id
        WHERE claim.active AND claim.authority_eligible
          AND batch.enabled AND batch.cardinality = 'set'
    )
    SELECT ranked.*
    FROM ranked
    JOIN effective_projection_batch batch
      ON batch.tenant_id = ranked.tenant_id
     AND batch.entity_id = ranked.entity_id
     AND batch.attribute_definition_id = ranked.attribute_definition_id
    WHERE batch.set_merge_policy = 'all_eligible_union'
       OR ranked.authority_rank = 1;

    DROP TABLE IF EXISTS pg_temp.desired_effective_set_members;
    CREATE TEMP TABLE desired_effective_set_members ON COMMIT DROP AS
    WITH active_decisions AS (
        SELECT decision.*
        FROM entity_attribute_decision_current decision
        JOIN effective_projection_batch batch
          ON batch.tenant_id = decision.tenant_id
         AND batch.entity_id = decision.entity_id
         AND batch.attribute_definition_id = decision.attribute_definition_id
        WHERE decision.active AND decision.cardinality = 'set' AND batch.enabled
    ), combined AS (
        SELECT source.tenant_id, source.entity_id,
               source.attribute_definition_id, source.value_type,
               source.value_text, source.value_number, source.value_boolean,
               source.value_timestamp, source.value_entity_id,
               source.value_json, source.value_fingerprint,
               source.member_key, 'source_union'::text AS selection_reason,
               2 AS precedence
        FROM effective_source_set_claims source
        LEFT JOIN active_decisions decision
          ON decision.tenant_id = source.tenant_id
         AND decision.entity_id = source.entity_id
         AND decision.attribute_definition_id = source.attribute_definition_id
        WHERE decision.id IS NULL
           OR (
               decision.operation = 'modify'
               AND NOT EXISTS (
                   SELECT 1
                   FROM entity_attribute_decision_member_current removed
                   WHERE removed.tenant_id = decision.tenant_id
                     AND removed.decision_id = decision.id
                     AND removed.member_key = source.member_key
                     AND removed.action = 'remove'
               )
           )
        UNION ALL
        SELECT decision.tenant_id, decision.entity_id,
               decision.attribute_definition_id, member.value_type,
               member.value_text, member.value_number, member.value_boolean,
               member.value_timestamp, member.value_entity_id,
               member.value_json, member.value_fingerprint,
               member.member_key,
               CASE WHEN decision.operation = 'replace'
                    THEN 'operator_replace' ELSE 'operator_add' END,
               1
        FROM active_decisions decision
        JOIN entity_attribute_decision_member_current member
          ON member.tenant_id = decision.tenant_id
         AND member.decision_id = decision.id
        WHERE member.action = 'add'
    )
    SELECT DISTINCT ON (tenant_id, entity_id, attribute_definition_id, member_key)
           tenant_id, entity_id, attribute_definition_id, value_type,
           value_text, value_number, value_boolean, value_timestamp,
           value_entity_id, value_json, value_fingerprint, member_key,
           selection_reason
    FROM combined
    ORDER BY tenant_id, entity_id, attribute_definition_id, member_key,
             precedence;

    DROP TABLE IF EXISTS pg_temp.desired_effective_headers;
    CREATE TEMP TABLE desired_effective_headers ON COMMIT DROP AS
    WITH single_choice AS (
        SELECT DISTINCT ON (claim.tenant_id, claim.entity_id,
                            claim.attribute_definition_id)
               claim.*
        FROM effective_top_claims claim
        ORDER BY claim.tenant_id, claim.entity_id,
                 claim.attribute_definition_id, claim.id
    ), active_decisions AS (
        SELECT decision.*
        FROM entity_attribute_decision_current decision
        JOIN effective_projection_batch batch
          ON batch.tenant_id = decision.tenant_id
         AND batch.entity_id = decision.entity_id
         AND batch.attribute_definition_id = decision.attribute_definition_id
        WHERE decision.active AND batch.enabled
    ), set_counts AS (
        SELECT member.tenant_id, member.entity_id,
               member.attribute_definition_id, COUNT(*)::integer AS member_count
        FROM desired_effective_set_members member
        GROUP BY member.tenant_id, member.entity_id,
                 member.attribute_definition_id
    ), source_set_counts AS (
        SELECT claim.tenant_id, claim.entity_id,
               claim.attribute_definition_id, COUNT(*)::integer AS claim_count
        FROM effective_source_set_claims claim
        GROUP BY claim.tenant_id, claim.entity_id,
                 claim.attribute_definition_id
    )
    SELECT batch.tenant_id, batch.entity_id, batch.entity_class_id,
           batch.attribute_definition_id, batch.value_type, batch.cardinality,
           CASE
             WHEN decision.operation = 'replace' THEN 'selected'
             WHEN decision.operation = 'clear' THEN 'cleared'
             WHEN conflict.entity_id IS NOT NULL
              AND batch.single_value_conflict_policy = 'retain_last_uncontested'
              AND batch.previous_status = 'selected'
              AND batch.previous_selection_reason IN (
                  'source_authority', 'retained_last_uncontested'
              ) THEN 'selected'
             WHEN conflict.entity_id IS NOT NULL THEN 'unknown'
             WHEN choice.id IS NOT NULL THEN 'selected'
             ELSE 'no_evidence'
           END AS status,
           CASE
             WHEN decision.operation = 'replace' THEN 'operator_replace'
             WHEN decision.operation = 'clear' THEN 'operator_clear'
             WHEN conflict.entity_id IS NOT NULL
              AND batch.single_value_conflict_policy = 'retain_last_uncontested'
              AND batch.previous_status = 'selected'
              AND batch.previous_selection_reason IN (
                  'source_authority', 'retained_last_uncontested'
              ) THEN 'retained_last_uncontested'
             WHEN conflict.entity_id IS NOT NULL THEN 'conflict_unknown'
             WHEN choice.id IS NOT NULL THEN 'source_authority'
             ELSE 'no_eligible_evidence'
           END AS selection_reason,
           CASE WHEN decision.operation = 'replace' THEN decision.value_text
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_text
                WHEN conflict.entity_id IS NULL THEN choice.value_text END AS value_text,
           CASE WHEN decision.operation = 'replace' THEN decision.value_number
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_number
                WHEN conflict.entity_id IS NULL THEN choice.value_number END AS value_number,
           CASE WHEN decision.operation = 'replace' THEN decision.value_boolean
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_boolean
                WHEN conflict.entity_id IS NULL THEN choice.value_boolean END AS value_boolean,
           CASE WHEN decision.operation = 'replace' THEN decision.value_timestamp
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_timestamp
                WHEN conflict.entity_id IS NULL THEN choice.value_timestamp END AS value_timestamp,
           CASE WHEN decision.operation = 'replace' THEN decision.value_entity_id
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_entity_id
                WHEN conflict.entity_id IS NULL THEN choice.value_entity_id END AS value_entity_id,
           CASE WHEN decision.operation = 'replace' THEN decision.value_json
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_json
                WHEN conflict.entity_id IS NULL THEN choice.value_json END AS value_json,
           CASE WHEN decision.operation = 'replace' THEN decision.value_fingerprint
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 AND batch.previous_status = 'selected'
                 AND batch.previous_selection_reason IN (
                     'source_authority', 'retained_last_uncontested'
                 ) THEN batch.previous_value_fingerprint
                WHEN conflict.entity_id IS NULL THEN choice.value_fingerprint END AS value_fingerprint,
           CASE WHEN decision.id IS NOT NULL THEN NULL
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 THEN batch.previous_authority_tier
                ELSE choice.authority_tier END AS selected_authority_tier,
           CASE WHEN decision.id IS NOT NULL THEN NULL
                WHEN conflict.entity_id IS NOT NULL
                 AND batch.single_value_conflict_policy = 'retain_last_uncontested'
                 THEN batch.previous_authority_priority
                ELSE choice.authority_priority END AS selected_authority_priority,
           (conflict.entity_id IS NOT NULL) AS conflict,
           batch.input_hash, batch.previous_id
    FROM effective_projection_batch batch
    LEFT JOIN active_decisions decision
      ON decision.tenant_id = batch.tenant_id
     AND decision.entity_id = batch.entity_id
     AND decision.attribute_definition_id = batch.attribute_definition_id
    LEFT JOIN single_choice choice
      ON choice.tenant_id = batch.tenant_id
     AND choice.entity_id = batch.entity_id
     AND choice.attribute_definition_id = batch.attribute_definition_id
    LEFT JOIN effective_conflicts conflict
      ON conflict.tenant_id = batch.tenant_id
     AND conflict.entity_id = batch.entity_id
     AND conflict.attribute_definition_id = batch.attribute_definition_id
    WHERE batch.cardinality = 'single'
    UNION ALL
    SELECT batch.tenant_id, batch.entity_id, batch.entity_class_id,
           batch.attribute_definition_id, batch.value_type, batch.cardinality,
           CASE WHEN COALESCE(counts.member_count, 0) > 0 THEN 'selected'
                WHEN decision.id IS NOT NULL THEN 'empty'
                ELSE 'no_evidence' END,
           CASE WHEN decision.operation = 'replace' THEN 'operator_replace'
                WHEN decision.operation = 'modify' THEN 'operator_modify'
                WHEN COALESCE(source_counts.claim_count, 0) > 0 THEN 'source_union'
                ELSE 'no_eligible_evidence' END,
           NULL::text, NULL::numeric, NULL::boolean, NULL::timestamptz,
           NULL::uuid, NULL::jsonb, NULL::bytea,
           NULL::smallint, NULL::smallint, FALSE,
           batch.input_hash, batch.previous_id
    FROM effective_projection_batch batch
    LEFT JOIN active_decisions decision
      ON decision.tenant_id = batch.tenant_id
     AND decision.entity_id = batch.entity_id
     AND decision.attribute_definition_id = batch.attribute_definition_id
    LEFT JOIN set_counts counts
      ON counts.tenant_id = batch.tenant_id
     AND counts.entity_id = batch.entity_id
     AND counts.attribute_definition_id = batch.attribute_definition_id
    LEFT JOIN source_set_counts source_counts
      ON source_counts.tenant_id = batch.tenant_id
     AND source_counts.entity_id = batch.entity_id
     AND source_counts.attribute_definition_id = batch.attribute_definition_id
    WHERE batch.cardinality = 'set';

    DELETE FROM entity_attribute_effective_claim_support support
    USING entity_attribute_effective_current effective,
          effective_projection_batch batch
    WHERE support.tenant_id = effective.tenant_id
      AND support.effective_id = effective.id
      AND effective.tenant_id = batch.tenant_id
      AND effective.entity_id = batch.entity_id
      AND effective.attribute_definition_id = batch.attribute_definition_id;

    DELETE FROM entity_attribute_effective_member_current member
    USING entity_attribute_effective_current effective,
          effective_projection_batch batch
    WHERE member.tenant_id = effective.tenant_id
      AND member.effective_id = effective.id
      AND effective.tenant_id = batch.tenant_id
      AND effective.entity_id = batch.entity_id
      AND effective.attribute_definition_id = batch.attribute_definition_id;

    INSERT INTO entity_attribute_effective_current (
        id, tenant_id, version, entity_id, entity_class_id,
        attribute_definition_id, value_type, cardinality, status,
        selection_reason, value_text, value_number, value_boolean,
        value_timestamp, value_entity_id, value_json, value_fingerprint,
        selected_authority_tier, selected_authority_priority, conflict,
        input_hash, projected_at
    )
    SELECT COALESCE(desired.previous_id, gen_random_uuid()), desired.tenant_id,
           1, desired.entity_id, desired.entity_class_id,
           desired.attribute_definition_id, desired.value_type,
           desired.cardinality, desired.status, desired.selection_reason,
           desired.value_text, desired.value_number, desired.value_boolean,
           desired.value_timestamp, desired.value_entity_id,
           desired.value_json, desired.value_fingerprint,
           desired.selected_authority_tier,
           desired.selected_authority_priority, desired.conflict,
           desired.input_hash, projected_at
    FROM desired_effective_headers desired
    ON CONFLICT (tenant_id, entity_id, attribute_definition_id) DO UPDATE SET
        entity_class_id = EXCLUDED.entity_class_id,
        value_type = EXCLUDED.value_type,
        cardinality = EXCLUDED.cardinality,
        status = EXCLUDED.status,
        selection_reason = EXCLUDED.selection_reason,
        value_text = EXCLUDED.value_text,
        value_number = EXCLUDED.value_number,
        value_boolean = EXCLUDED.value_boolean,
        value_timestamp = EXCLUDED.value_timestamp,
        value_entity_id = EXCLUDED.value_entity_id,
        value_json = EXCLUDED.value_json,
        value_fingerprint = EXCLUDED.value_fingerprint,
        selected_authority_tier = EXCLUDED.selected_authority_tier,
        selected_authority_priority = EXCLUDED.selected_authority_priority,
        conflict = EXCLUDED.conflict,
        input_hash = EXCLUDED.input_hash,
        projected_at = EXCLUDED.projected_at,
        version = entity_attribute_effective_current.version + 1;
    GET DIAGNOSTICS effective_writes = ROW_COUNT;

    INSERT INTO entity_attribute_effective_member_current (
        id, tenant_id, version, effective_id, value_type, value_text,
        value_number, value_boolean, value_timestamp, value_entity_id,
        value_json, value_fingerprint, member_key, selection_reason
    )
    SELECT gen_random_uuid(), desired.tenant_id, 1, effective.id,
           desired.value_type, desired.value_text, desired.value_number,
           desired.value_boolean, desired.value_timestamp,
           desired.value_entity_id, desired.value_json,
           desired.value_fingerprint, desired.member_key,
           desired.selection_reason
    FROM desired_effective_set_members desired
    JOIN entity_attribute_effective_current effective
      ON effective.tenant_id = desired.tenant_id
     AND effective.entity_id = desired.entity_id
     AND effective.attribute_definition_id = desired.attribute_definition_id;
    GET DIAGNOSTICS member_writes = ROW_COUNT;

    INSERT INTO entity_attribute_effective_claim_support (
        id, tenant_id, effective_id, effective_member_id, claim_id
    )
    SELECT gen_random_uuid(), effective.tenant_id, effective.id, NULL, claim.id
    FROM entity_attribute_effective_current effective
    JOIN effective_projection_batch batch
      ON batch.tenant_id = effective.tenant_id
     AND batch.entity_id = effective.entity_id
     AND batch.attribute_definition_id = effective.attribute_definition_id
    JOIN effective_top_claims claim
      ON claim.tenant_id = effective.tenant_id
     AND claim.entity_id = effective.entity_id
     AND claim.attribute_definition_id = effective.attribute_definition_id
     AND claim.value_fingerprint = effective.value_fingerprint
    WHERE effective.selection_reason = 'source_authority'
    UNION ALL
    SELECT gen_random_uuid(), effective.tenant_id, effective.id,
           member.id, claim.id
    FROM entity_attribute_effective_current effective
    JOIN entity_attribute_effective_member_current member
      ON member.tenant_id = effective.tenant_id
     AND member.effective_id = effective.id
     AND member.selection_reason = 'source_union'
    JOIN effective_source_set_claims claim
      ON claim.tenant_id = effective.tenant_id
     AND claim.entity_id = effective.entity_id
     AND claim.attribute_definition_id = effective.attribute_definition_id
     AND claim.member_key = member.member_key
    JOIN effective_projection_batch batch
      ON batch.tenant_id = effective.tenant_id
     AND batch.entity_id = effective.entity_id
     AND batch.attribute_definition_id = effective.attribute_definition_id;
    GET DIAGNOSTICS support_writes = ROW_COUNT;

    SELECT COUNT(*) INTO conflict_rows FROM effective_conflicts;

    DELETE FROM entity_attribute_effective_dirty dirty
    USING effective_projection_batch batch
    WHERE dirty.id = batch.dirty_id;

    RETURN jsonb_build_object(
        'status', 'projected', 'processed', batch_rows,
        'effective_writes', effective_writes,
        'member_writes', member_writes,
        'support_writes', support_writes,
        'conflicts', conflict_rows,
        'conflict_support_writes', conflict_support_writes
    );
END;
$function$;
"""


VIEW_SQL = r"""
CREATE OR REPLACE VIEW operations.v_entity_attribute_effective_current
WITH (security_barrier = true) AS
SELECT effective.id, effective.tenant_id, effective.entity_id,
       effective.entity_class_id AS entity_class,
       definition.key AS attribute_key,
       definition.display_name AS attribute_display_name,
       definition.sensitivity, effective.cardinality, effective.status,
       effective.selection_reason,
       CASE
         WHEN definition.sensitivity IN ('sensitive', 'restricted')
           THEN '[redacted]'
         WHEN effective.status <> 'selected'
           THEN '[' || effective.status || ']'
         WHEN effective.cardinality = 'set'
           THEN '[' || (
               SELECT COUNT(*)::text
               FROM operations.entity_attribute_effective_member_current member
               WHERE member.tenant_id = effective.tenant_id
                 AND member.effective_id = effective.id
           ) || ' members]'
         WHEN effective.value_type = 'text' THEN effective.value_text
         WHEN effective.value_type = 'number' THEN effective.value_number::text
         WHEN effective.value_type = 'boolean' THEN effective.value_boolean::text
         WHEN effective.value_type = 'timestamp' THEN effective.value_timestamp::text
         WHEN effective.value_type = 'entity_reference'
           THEN effective.value_entity_id::text
         WHEN effective.value_type = 'structured' THEN '[structured]'
         ELSE '[unknown]'
       END AS value_display,
       effective.conflict, effective.projected_at
FROM operations.entity_attribute_effective_current effective
JOIN operations.attribute_definitions definition
  ON definition.id = effective.attribute_definition_id
WHERE effective.tenant_id = operations.current_tenant_id();

REVOKE ALL ON operations.v_entity_attribute_effective_current FROM PUBLIC;
GRANT SELECT ON operations.v_entity_attribute_effective_current TO operations_app;
"""


SECURITY_SQL = r"""
REVOKE ALL ON
    operations.entity_attribute_decision_current,
    operations.entity_attribute_decision_member_current,
    operations.entity_attribute_effective_dirty,
    operations.entity_attribute_effective_current,
    operations.entity_attribute_effective_member_current,
    operations.entity_attribute_effective_claim_support,
    operations.entity_attribute_conflict_current,
    operations.entity_attribute_conflict_claim_support
FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE ON operations.entity_attribute_decision_current
    TO operations_app;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON operations.entity_attribute_decision_member_current TO operations_app;
GRANT SELECT ON
    operations.entity_attribute_effective_current,
    operations.entity_attribute_effective_member_current,
    operations.entity_attribute_effective_claim_support,
    operations.entity_attribute_conflict_current,
    operations.entity_attribute_conflict_claim_support
TO operations_app;

REVOKE ALL ON FUNCTION operations.sync_entity_attribute_effective(integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.validate_attribute_decision_member()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.audit_and_queue_attribute_decision()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.audit_and_queue_attribute_decision_member()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.sync_entity_attribute_effective(integer)
    TO ninja_ingest, operations_app;

ALTER FUNCTION operations.validate_attribute_decision_member() OWNER TO operations_migrate;
ALTER FUNCTION operations.audit_and_queue_attribute_decision() OWNER TO operations_migrate;
ALTER FUNCTION operations.audit_and_queue_attribute_decision_member() OWNER TO operations_migrate;
ALTER FUNCTION operations.sync_entity_attribute_effective(integer) OWNER TO operations_migrate;

ALTER TABLE operations.entity_attribute_decision_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_decision_member_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_effective_dirty OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_effective_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_effective_member_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_effective_claim_support OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_conflict_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_conflict_claim_support OWNER TO operations_migrate;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS audit_and_queue_attribute_decision_member
    ON operations.entity_attribute_decision_member_current;
DROP TRIGGER IF EXISTS audit_and_queue_attribute_decision
    ON operations.entity_attribute_decision_current;
DROP TRIGGER IF EXISTS validate_attribute_decision_member
    ON operations.entity_attribute_decision_member_current;
DROP FUNCTION IF EXISTS operations.audit_and_queue_attribute_decision_member();
DROP FUNCTION IF EXISTS operations.audit_and_queue_attribute_decision();
DROP FUNCTION IF EXISTS operations.validate_attribute_decision_member();
DROP FUNCTION IF EXISTS operations.sync_entity_attribute_effective(integer);
ALTER TABLE operations.users
    DROP CONSTRAINT IF EXISTS uq_users_tenant_id CASCADE;
ALTER TABLE operations.attribute_definitions
    DROP CONSTRAINT IF EXISTS uq_attr_defs_id_class CASCADE;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0107_entityattributeconflictcurrent_and_more"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(SETUP_SQL, REVERSE_SQL),
        migrations.RunSQL(CLAIM_PROJECTOR_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(PROJECTOR_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(
            VIEW_SQL,
            "DROP VIEW IF EXISTS operations.v_entity_attribute_effective_current",
        ),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
    ]
