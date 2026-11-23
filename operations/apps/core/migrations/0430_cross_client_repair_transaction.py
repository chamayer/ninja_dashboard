"""Record cross-client membership repairs and their pending inventory rebuild."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.computer_repair_inventory_pending (
    tenant_id bigint NOT NULL,
    device_id uuid NOT NULL,
    action_id uuid NOT NULL REFERENCES operations.change_actions(id),
    affected_titles text[] NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, device_id),
    FOREIGN KEY (tenant_id, device_id) REFERENCES operations.devices(tenant_id, id)
);
ALTER TABLE operations.computer_repair_inventory_pending OWNER TO operations_migrate;
ALTER TABLE operations.computer_repair_inventory_pending ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.computer_repair_inventory_pending FORCE ROW LEVEL SECURITY;
CREATE POLICY computer_repair_pending_tenant ON operations.computer_repair_inventory_pending
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.computer_repair_inventory_pending
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.computer_repair_inventory_pending TO ninja_ingest;

CREATE TABLE operations.source_record_software_listing_state (
    tenant_id bigint NOT NULL,
    source_record_id uuid NOT NULL,
    received_at timestamptz NOT NULL,
    complete boolean NOT NULL,
    PRIMARY KEY (tenant_id, source_record_id),
    FOREIGN KEY (tenant_id, source_record_id)
        REFERENCES operations.source_record_subjects(tenant_id, id) ON DELETE CASCADE
);
ALTER TABLE operations.source_record_software_listing_state OWNER TO operations_migrate;
ALTER TABLE operations.source_record_software_listing_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_record_software_listing_state FORCE ROW LEVEL SECURITY;
CREATE POLICY repair_listing_state_tenant ON operations.source_record_software_listing_state
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.source_record_software_listing_state
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT, INSERT, UPDATE ON operations.source_record_software_listing_state TO ninja_ingest;

INSERT INTO operations.change_history_registry
    (table_name, classification, reason, recorded_columns, secret_columns, key_columns,
     computer_column, computer_condition_column, computer_condition_value, client_column,
     is_global, capture)
VALUES
    ('computer_repair_inventory_pending', 'exempt',
     'Pending projection derived from audited Computer repair actions',
     '{}', '{}', ARRAY['tenant_id', 'device_id'], 'device_id', NULL, NULL, NULL,
     false, NULL),
    ('source_record_software_listing_state', 'exempt',
     'Latest completeness decision for source-record installation projection',
     '{}', '{}', ARRAY['tenant_id', 'source_record_id'], NULL, NULL, NULL, NULL,
     false, NULL);

CREATE FUNCTION operations.cross_client_repair_snapshot(
    p_tenant bigint, p_survivor uuid, p_absorbed uuid, p_lock boolean
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_snapshot jsonb;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_survivor IS NULL OR p_absorbed IS NULL OR p_survivor = p_absorbed THEN
        RAISE EXCEPTION 'Invalid repair snapshot scope';
    END IF;
    IF p_lock THEN
        PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');
        PERFORM d.id FROM operations.devices d
         WHERE d.tenant_id = p_tenant AND d.id IN (p_survivor, p_absorbed)
         ORDER BY d.id FOR UPDATE OF d;
        PERFORM owner.device_id FROM operations.computer_client_ownership owner
         WHERE owner.tenant_id = p_tenant AND owner.device_id IN (p_survivor, p_absorbed)
         ORDER BY owner.device_id FOR UPDATE OF owner;
        PERFORM s.id
          FROM operations.source_record_subjects s
          JOIN operations.entity_observation_current eo
            ON eo.tenant_id = s.tenant_id AND eo.observation_id = s.observation_id
         WHERE s.tenant_id = p_tenant AND s.subject_kind = 'record'
           AND eo.device_id IN (p_survivor, p_absorbed)
         ORDER BY s.id FOR UPDATE OF s;
    END IF;
    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'subject_id', s.id, 'device_id', eo.device_id,
        'input_version', s.input_version, 'association_version', s.association_version
    ) ORDER BY s.id), '[]'::jsonb) INTO v_snapshot
      FROM operations.source_record_subjects s
      JOIN operations.entity_observation_current eo
        ON eo.tenant_id = s.tenant_id AND eo.observation_id = s.observation_id
     WHERE s.tenant_id = p_tenant AND s.subject_kind = 'record'
       AND eo.device_id IN (p_survivor, p_absorbed);
    RETURN v_snapshot;
END
$fn$;
ALTER FUNCTION operations.cross_client_repair_snapshot(bigint, uuid, uuid, boolean)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.cross_client_repair_snapshot(bigint, uuid, uuid, boolean)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.cross_client_repair_snapshot(bigint, uuid, uuid, boolean)
    TO operations_app;

CREATE FUNCTION operations.record_cross_client_repair(
    p_tenant bigint, p_survivor uuid, p_absorbed uuid, p_action uuid,
    p_reviewed_membership jsonb
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_action operations.change_actions%ROWTYPE;
    v_merge operations.computer_merges%ROWTYPE;
    v_survivor operations.devices%ROWTYPE;
    v_absorbed operations.devices%ROWTYPE;
    v_result record;
    v_link_ids uuid[];
    v_observation_ids uuid[];
    v_titles text[];
    v_reverse boolean;
    v_move_membership jsonb;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_survivor IS NULL OR p_absorbed IS NULL OR p_survivor = p_absorbed
       OR p_action IS NULL
       OR p_action IS DISTINCT FROM nullif(current_setting('operations.change_action_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Invalid cross-client repair context';
    END IF;
    IF to_regclass('operations.v_current_source_installations') IS NULL THEN
        RAISE EXCEPTION 'Cross-client repair requires the source installation projection';
    END IF;
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');
    SELECT * INTO STRICT v_action
      FROM operations.change_actions
     WHERE id = p_action AND tenant_id = p_tenant AND explicit
       AND (
           (actor_kind = 'operator' AND actor_id IS NOT NULL
               AND pg_has_role(session_user, 'operations_app', 'MEMBER'))
           OR (actor_kind IN ('process', 'system') AND process <> ''
               AND pg_has_role(session_user, 'ninja_ingest', 'MEMBER'))
       )
       AND action IN ('computer.merge.cross_client', 'computer.split.cross_client')
       AND btrim(reason) <> ''
       AND evidence ->> 'survivor_id' = p_survivor::text
       AND evidence ->> 'absorbed_id' = p_absorbed::text;
    v_reverse := v_action.action = 'computer.split.cross_client';

    PERFORM d.id FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.id IN (p_survivor, p_absorbed)
     ORDER BY d.id FOR UPDATE OF d;
    SELECT * INTO STRICT v_survivor FROM operations.devices
     WHERE tenant_id = p_tenant AND id = p_survivor AND deleted_at IS NULL;
    SELECT * INTO STRICT v_absorbed FROM operations.devices
     WHERE tenant_id = p_tenant AND id = p_absorbed;
    PERFORM owner.device_id FROM operations.computer_client_ownership owner
     WHERE owner.tenant_id = p_tenant AND owner.device_id IN (p_survivor, p_absorbed)
     ORDER BY owner.device_id FOR UPDATE OF owner;

    IF v_reverse THEN
        SELECT * INTO STRICT v_merge FROM operations.computer_merges
         WHERE tenant_id = p_tenant AND id = (v_action.evidence ->> 'merge_id')::uuid
           AND survivor_id = p_survivor AND absorbed_id = p_absorbed AND split_at IS NULL
         FOR UPDATE;
        IF v_absorbed.deleted_at IS NULL OR v_absorbed.deleted_reason IS DISTINCT FROM 'merged'
           OR EXISTS (
               SELECT 1 FROM operations.entity_source_links link
                WHERE link.tenant_id = p_tenant AND link.entity_id = v_absorbed.entity_id
           ) THEN
            RAISE EXCEPTION 'The absorbed Computer changed; review reversal again';
        END IF;
    ELSE
        IF v_absorbed.deleted_at IS NOT NULL
           OR v_survivor.client_id IS NULL OR v_absorbed.client_id IS NULL
           OR v_survivor.client_id = v_absorbed.client_id
           OR v_action.evidence ->> 'survivor_client_id' IS DISTINCT FROM v_survivor.client_id::text
           OR v_action.evidence ->> 'absorbed_client_id' IS DISTINCT FROM v_absorbed.client_id::text
           OR (SELECT count(*)
               FROM operations.computer_client_ownership owner
               JOIN operations.devices d
                 ON d.tenant_id = owner.tenant_id AND d.id = owner.device_id
              WHERE owner.tenant_id = p_tenant AND owner.device_id IN (p_survivor, p_absorbed)
                AND owner.state IN ('resolved', 'decision_protected')
                AND owner.effective_client_id = d.client_id) <> 2 THEN
            RAISE EXCEPTION 'Computer ownership changed; review the cross-client merge again';
        END IF;
    END IF;
    IF EXISTS (
        SELECT 1 FROM operations.computer_repair_inventory_pending pending
         WHERE pending.tenant_id = p_tenant AND pending.device_id IN (p_survivor, p_absorbed)
           AND (NOT v_reverse OR pending.action_id IS DISTINCT FROM v_merge.action_id)
    ) THEN
        RAISE EXCEPTION 'A previous Computer repair still has pending inventory';
    END IF;

    IF v_reverse THEN
        UPDATE operations.devices SET deleted_at = NULL, deleted_reason = ''
         WHERE tenant_id = p_tenant AND id = p_absorbed;
    ELSE
        IF p_reviewed_membership IS DISTINCT FROM operations.cross_client_repair_snapshot(
            p_tenant, p_survivor, p_absorbed, true
        ) THEN
            RAISE EXCEPTION 'Computer source membership changed; review the merge again';
        END IF;
        SELECT jsonb_agg(member.value ORDER BY member.ordinality) INTO v_move_membership
          FROM jsonb_array_elements(p_reviewed_membership) WITH ORDINALITY AS member(value, ordinality)
         WHERE member.value ->> 'device_id' = p_absorbed::text;
    END IF;
    SELECT * INTO STRICT v_result FROM operations.apply_repair_membership(
        p_tenant, p_survivor, p_absorbed, p_action, v_move_membership
    );

    IF v_reverse THEN
        UPDATE operations.computer_merges
           SET split_action_id = p_action, split_at = v_action.occurred_at
         WHERE tenant_id = p_tenant AND id = v_merge.id;
    ELSE
        SELECT coalesce(array_agg(link.id ORDER BY link.id), '{}'),
               coalesce(array_agg(s.observation_id ORDER BY s.observation_id), '{}')
          INTO v_link_ids, v_observation_ids
          FROM jsonb_to_recordset(v_result.moved_membership) moved(subject_id uuid)
          JOIN operations.source_record_subjects s ON s.tenant_id = p_tenant AND s.id = moved.subject_id
          JOIN operations.entity_source_links link
            ON link.tenant_id = s.tenant_id AND link.source_subject_id = s.id;
        INSERT INTO operations.computer_merges
            (tenant_id, client_id, survivor_id, absorbed_id, action_id, reason, evidence,
             moved_observation_ids, moved_link_ids)
        VALUES
            (p_tenant, v_survivor.client_id, p_survivor, p_absorbed, p_action, v_action.reason,
             v_action.evidence || jsonb_build_object('moved_membership', v_result.moved_membership,
                                                     'inventory_projection', 'source_record'),
             v_observation_ids, v_link_ids)
        RETURNING * INTO v_merge;
        UPDATE operations.devices SET deleted_at = v_action.occurred_at, deleted_reason = 'merged'
         WHERE tenant_id = p_tenant AND id = p_absorbed;
    END IF;

    SELECT coalesce(array_agg(title ORDER BY title), '{}') INTO v_titles
      FROM (
          SELECT unnest(v_result.affected_titles) AS title
          UNION
          SELECT unnest(pending.affected_titles)
            FROM operations.computer_repair_inventory_pending pending
           WHERE pending.tenant_id = p_tenant AND pending.device_id IN (p_survivor, p_absorbed)
      ) affected;
    INSERT INTO operations.computer_repair_inventory_pending
        (tenant_id, device_id, action_id, affected_titles)
    SELECT p_tenant, affected_device.device_id, p_action, v_titles
      FROM unnest(ARRAY[p_survivor, p_absorbed]) AS affected_device(device_id)
    ON CONFLICT (tenant_id, device_id) DO UPDATE
        SET action_id = EXCLUDED.action_id, affected_titles = EXCLUDED.affected_titles,
            queued_at = EXCLUDED.queued_at;
    PERFORM operations.retire_entity_relationships(p_tenant, v_survivor.entity_id, 'computer_repair');
    PERFORM operations.retire_entity_relationships(p_tenant, v_absorbed.entity_id, 'computer_repair');
    PERFORM operations.invalidate_computer_client_ownership(p_tenant, p_survivor);
    PERFORM operations.invalidate_computer_client_ownership(p_tenant, p_absorbed);
    RETURN v_merge.id;
END
$fn$;
ALTER FUNCTION operations.record_cross_client_repair(bigint, uuid, uuid, uuid, jsonb)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.record_cross_client_repair(bigint, uuid, uuid, uuid, jsonb)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.record_cross_client_repair(bigint, uuid, uuid, uuid, jsonb)
    TO operations_app, ninja_ingest;

CREATE FUNCTION operations.publish_repair_inventory(p_tenant bigint, p_device uuid, p_binding uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_pending operations.computer_repair_inventory_pending%ROWTYPE;
    v_device operations.devices%ROWTYPE;
    v_titles text[];
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Invalid repair inventory tenant';
    END IF;
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');
    PERFORM binding.source_instance_id
      FROM operations.source_bindings binding
      JOIN operations.source_instances instance
        ON instance.tenant_id = binding.tenant_id AND instance.id = binding.source_instance_id
      JOIN operations.sources source ON source.id = instance.source_id AND source.name = 'Ninja'
     WHERE binding.tenant_id = p_tenant AND binding.id = p_binding;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invalid Ninja software source binding';
    END IF;
    SELECT * INTO v_device FROM operations.devices
     WHERE tenant_id = p_tenant AND id = p_device FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    SELECT * INTO v_pending FROM operations.computer_repair_inventory_pending
     WHERE tenant_id = p_tenant AND device_id = p_device FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    v_titles := v_pending.affected_titles;

    IF to_regclass('operations.v_current_source_installations') IS NULL THEN
        RETURN false;
    END IF;
    IF v_device.deleted_at IS NULL THEN
        PERFORM 1 FROM operations.computer_client_ownership
         WHERE tenant_id = p_tenant AND device_id = p_device
           AND state IN ('resolved', 'decision_protected') AND effective_client_id = v_device.client_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RETURN false;
        END IF;
        SELECT coalesce(array_agg(title ORDER BY title), '{}') INTO v_titles
          FROM (
              SELECT unnest(v_titles) AS title
              UNION
              SELECT canonical_name FROM operations.v_current_source_installations
               WHERE tenant_id = p_tenant AND device_id = p_device AND stale_since IS NULL
          ) touched;
    END IF;

    -- Current inventory is projected from the active source association.
    -- The queue acknowledges the repair and requests a fresh evaluation.
    INSERT INTO operations.software_reclassification_targets (tenant_id, target_key, canonical_name, source)
    SELECT p_tenant, left('name:' || lower(title), 300), min(title), 'inventory'
      FROM unnest(v_titles) AS touched(title)
     WHERE title <> ''
     GROUP BY left('name:' || lower(title), 300)
    ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL
    DO UPDATE SET generation = software_reclassification_targets.generation + 1;
    DELETE FROM operations.computer_repair_inventory_pending
     WHERE tenant_id = p_tenant AND device_id = p_device AND action_id = v_pending.action_id;
    RETURN true;
END
$fn$;
ALTER FUNCTION operations.publish_repair_inventory(bigint, uuid, uuid) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.publish_repair_inventory(bigint, uuid, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.publish_repair_inventory(bigint, uuid, uuid) TO ninja_ingest;
"""

REVERSE_SQL = """
LOCK TABLE operations.computer_repair_inventory_pending IN ACCESS EXCLUSIVE MODE;
ALTER TABLE operations.computer_repair_inventory_pending NO FORCE ROW LEVEL SECURITY;
SET LOCAL row_security = off;
DO $fn$
BEGIN
    IF EXISTS (SELECT 1 FROM operations.computer_repair_inventory_pending) THEN
        RAISE EXCEPTION 'Complete the pending repair inventory before rolling back';
    END IF;
END
$fn$;
DROP FUNCTION operations.record_cross_client_repair(bigint, uuid, uuid, uuid, jsonb);
DROP FUNCTION operations.cross_client_repair_snapshot(bigint, uuid, uuid, boolean);
DROP FUNCTION operations.publish_repair_inventory(bigint, uuid, uuid);
DROP TABLE operations.computer_repair_inventory_pending;
DROP TABLE operations.source_record_software_listing_state;
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('computer_repair_inventory_pending', 'source_record_software_listing_state');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0429_versioned_repair_membership"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
