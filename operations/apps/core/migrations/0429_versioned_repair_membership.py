"""Move pinned repair memberships while preserving source-owned inventory."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION operations.apply_repair_membership(
    p_tenant bigint, p_survivor uuid, p_absorbed uuid, p_action uuid,
    p_reviewed_membership jsonb
) RETURNS TABLE (moved_membership jsonb, affected_titles text[])
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_action operations.change_actions%ROWTYPE;
    v_snapshot jsonb;
    v_from uuid;
    v_to uuid;
    v_from_entity uuid;
    v_to_entity uuid;
    v_reverse boolean;
    v_version bigint;
    v_original_action uuid;
    v_closed jsonb;
    v_kept uuid;
    v_closed_id uuid;
    v_closed_entity uuid;
    r record;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_survivor IS NULL OR p_absorbed IS NULL OR p_survivor = p_absorbed
       OR p_action IS NULL
       OR p_action IS DISTINCT FROM nullif(current_setting('operations.change_action_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Invalid repair membership context';
    END IF;
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');

    SELECT * INTO STRICT v_action
      FROM operations.change_actions
     WHERE id = p_action AND tenant_id = p_tenant AND explicit
       AND action IN ('computer.merge.cross_client', 'computer.split.cross_client')
       AND btrim(reason) <> ''
       AND evidence ->> 'survivor_id' = p_survivor::text
       AND evidence ->> 'absorbed_id' = p_absorbed::text;
    v_reverse := v_action.action = 'computer.split.cross_client';

    IF v_reverse THEN
        -- A reversal uses the versions returned by the original move and
        -- recorded with the merge. A caller cannot supply fresher versions.
        SELECT saved_merge.evidence -> 'moved_membership', saved_merge.action_id
          INTO STRICT v_snapshot, v_original_action
          FROM operations.computer_merges saved_merge
          JOIN operations.change_actions original
            ON original.tenant_id = saved_merge.tenant_id AND original.id = saved_merge.action_id
           AND original.action = 'computer.merge.cross_client'
         WHERE saved_merge.tenant_id = p_tenant
           AND saved_merge.id = (v_action.evidence ->> 'merge_id')::uuid
           AND saved_merge.survivor_id = p_survivor AND saved_merge.absorbed_id = p_absorbed
           AND saved_merge.split_at IS NULL
         FOR UPDATE OF saved_merge;
        v_from := p_survivor;
        v_to := p_absorbed;
    ELSE
        v_snapshot := p_reviewed_membership;
        v_from := p_absorbed;
        v_to := p_survivor;
    END IF;

    IF jsonb_typeof(v_snapshot) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Repair requires a reviewed membership snapshot';
    END IF;
    IF jsonb_array_length(v_snapshot) = 0 OR EXISTS (
        SELECT 1
          FROM jsonb_to_recordset(v_snapshot) expected(
              subject_id uuid, association_version bigint, input_version bigint)
         GROUP BY expected.subject_id
        HAVING expected.subject_id IS NULL OR count(*) <> 1
            OR bool_or(expected.association_version IS NULL OR expected.association_version < 0)
            OR bool_or(NOT v_reverse AND (expected.input_version IS NULL OR expected.input_version < 0))
    ) THEN
        RAISE EXCEPTION 'Invalid repair membership snapshot';
    END IF;

    -- The parent transaction owns the tenant and ownership fences. Hold the
    -- Computer and source subject locks while checking and moving membership.
    PERFORM d.id FROM operations.devices d
     WHERE d.tenant_id = p_tenant AND d.id IN (v_from, v_to)
     ORDER BY d.id FOR UPDATE OF d;
    SELECT entity_id INTO STRICT v_from_entity
      FROM operations.devices WHERE tenant_id = p_tenant AND id = v_from AND deleted_at IS NULL;
    SELECT entity_id INTO STRICT v_to_entity
      FROM operations.devices WHERE tenant_id = p_tenant AND id = v_to AND deleted_at IS NULL;

    PERFORM s.id
      FROM operations.source_record_subjects s
      JOIN jsonb_to_recordset(v_snapshot) expected(subject_id uuid) ON expected.subject_id = s.id
     WHERE s.tenant_id = p_tenant
     ORDER BY s.id FOR UPDATE OF s;
    IF v_reverse THEN
        SELECT member INTO v_closed
          FROM jsonb_array_elements(v_snapshot) AS entry(member)
         WHERE member ? 'closed_from';
        IF v_closed IS NOT NULL THEN
            v_closed_id := (v_closed ->> 'subject_id')::uuid;
            v_kept := (v_closed ->> 'successor_id')::uuid;
            SELECT device.entity_id INTO STRICT v_closed_entity
              FROM operations.devices device
             WHERE device.tenant_id = p_tenant AND device.id IN (p_survivor, p_absorbed)
               AND device.id = (v_closed ->> 'closed_from')::uuid;
            PERFORM id FROM operations.source_record_subjects
             WHERE tenant_id = p_tenant AND id = v_kept FOR UPDATE;
            IF NOT EXISTS (
                SELECT 1
                  FROM operations.ninja_record_supersessions history
                  JOIN operations.source_record_subjects subject
                    ON subject.tenant_id = history.tenant_id AND subject.id = history.source_record_id
                  JOIN operations.entity_observation_current observation
                    ON observation.tenant_id = subject.tenant_id AND observation.observation_id = subject.observation_id
                  JOIN operations.entity_source_links kept
                    ON kept.tenant_id = history.tenant_id AND kept.source_subject_id = history.successor_record_id
                 WHERE history.tenant_id = p_tenant AND history.source_record_id = v_closed_id
                   AND history.successor_record_id = v_kept AND history.action_id = v_original_action
                   AND history.computer_id = p_survivor AND observation.device_id IS NULL
                   AND subject.association_version = (v_closed ->> 'association_version')::bigint
                   AND kept.entity_class_id = 'device' AND kept.entity_id = v_from_entity
                   AND kept.association_version = (v_closed ->> 'successor_association_version')::bigint
                   AND NOT EXISTS (
                       SELECT 1 FROM operations.entity_source_links link
                        WHERE link.tenant_id = subject.tenant_id AND link.source_subject_id = subject.id
                   )
            ) THEN
                RAISE EXCEPTION 'Ninja succession changed; review the reversal again'
                    USING ERRCODE = 'serialization_failure';
            END IF;
        END IF;
    END IF;
    IF EXISTS (
        SELECT 1
          FROM jsonb_to_recordset(v_snapshot) expected(
              subject_id uuid, association_version bigint, input_version bigint)
         WHERE expected.subject_id IS DISTINCT FROM v_closed_id AND NOT EXISTS (
            SELECT 1
              FROM operations.source_record_subjects s
              JOIN operations.entity_source_links link
                ON link.tenant_id = s.tenant_id AND link.source_subject_id = s.id
              JOIN operations.entity_observation_current eo
                ON eo.tenant_id = s.tenant_id AND eo.observation_id = s.observation_id
             WHERE s.tenant_id = p_tenant AND s.id = expected.subject_id
               AND s.subject_kind = 'record' AND link.entity_class_id = 'device'
               AND link.entity_id = v_from_entity AND eo.device_id = v_from
               AND link.association_version = expected.association_version
               AND s.association_version = expected.association_version
               AND (v_reverse OR s.input_version = expected.input_version)
         )
    ) OR (NOT v_reverse AND (
        EXISTS (
            SELECT 1 FROM operations.entity_source_links link
             WHERE link.tenant_id = p_tenant AND link.entity_id = v_from_entity
               AND NOT EXISTS (
                   SELECT 1 FROM jsonb_to_recordset(v_snapshot) expected(subject_id uuid)
                    WHERE expected.subject_id = link.source_subject_id)
        ) OR EXISTS (
            SELECT 1 FROM operations.entity_observation_current eo
             WHERE eo.tenant_id = p_tenant AND eo.device_id = v_from
               AND NOT EXISTS (
                   SELECT 1 FROM jsonb_to_recordset(v_snapshot) expected(subject_id uuid)
                   JOIN operations.source_record_subjects s
                     ON s.tenant_id = p_tenant AND s.id = expected.subject_id
                    WHERE s.observation_id = eo.observation_id)
        )
    )) THEN
        RAISE EXCEPTION 'Repair membership changed; review the complete action again'
            USING ERRCODE = 'serialization_failure';
    END IF;

    SELECT coalesce(array_agg(title ORDER BY title), '{}') INTO affected_titles
      FROM (
          SELECT unnest(operations.archive_repair_installation_subjects(
              p_tenant, p_survivor, p_absorbed, p_action)) AS title
          UNION
          SELECT inventory.canonical_name
            FROM (
                SELECT subject.id
                  FROM operations.entity_observation_current observation
                  JOIN operations.source_record_subjects subject
                    ON subject.tenant_id = observation.tenant_id AND subject.observation_id = observation.observation_id
                 WHERE observation.tenant_id = p_tenant AND observation.device_id IN (p_survivor, p_absorbed)
                UNION
                SELECT v_closed_id WHERE v_closed_id IS NOT NULL
            ) scoped_sources
            JOIN operations.source_record_software_current inventory
              ON inventory.tenant_id = p_tenant AND inventory.source_record_id = scoped_sources.id
             AND inventory.stale_since IS NULL
      ) touched;
    IF NOT v_reverse THEN
        v_closed := operations.close_cross_client_ninja_predecessor(p_tenant, p_survivor, p_absorbed, p_action);
        v_closed_id := (v_closed ->> 'subject_id')::uuid;
        v_kept := (v_closed ->> 'successor_id')::uuid;
    END IF;
    moved_membership := '[]'::jsonb;
    FOR r IN
        SELECT subject_id, association_version
          FROM jsonb_to_recordset(v_snapshot) expected(subject_id uuid, association_version bigint)
         WHERE subject_id IS DISTINCT FROM v_closed_id
         ORDER BY subject_id
    LOOP
        v_version := operations.set_source_association(
            r.subject_id, v_to_entity, 'device',
            CASE WHEN v_reverse THEN 'split' ELSE 'merge' END, 1,
            v_action.reason, r.association_version, 'system', v_action.actor_id,
            'operations.cross_client_repair',
            jsonb_build_object('repair_action_id', p_action));
        IF v_version IS DISTINCT FROM r.association_version + 1 THEN
            RAISE EXCEPTION 'Repair must advance every reviewed association version'
                USING ERRCODE = 'serialization_failure';
        END IF;
        moved_membership := moved_membership || jsonb_build_array(jsonb_build_object(
            'subject_id', r.subject_id, 'association_version', v_version));
    END LOOP;
    IF v_closed IS NOT NULL AND v_reverse THEN
        DELETE FROM operations.ninja_record_supersessions
         WHERE tenant_id = p_tenant AND source_record_id = v_closed_id AND action_id = v_original_action;
        v_version := operations.set_source_association(
            v_closed_id, v_closed_entity, 'device', 'split', 1, v_action.reason,
            (v_closed ->> 'association_version')::bigint, 'system', v_action.actor_id,
            'operations.cross_client_repair',
            jsonb_build_object('repair_action_id', p_action, 'reversed_succession_action_id', v_original_action));
        IF v_version IS DISTINCT FROM (v_closed ->> 'association_version')::bigint + 1 THEN
            RAISE EXCEPTION 'The historical Ninja association could not be restored'
                USING ERRCODE = 'serialization_failure';
        END IF;
    ELSIF v_closed IS NOT NULL THEN
        SELECT association_version INTO STRICT v_version FROM operations.source_record_subjects
         WHERE tenant_id = p_tenant AND id = v_kept;
        moved_membership := moved_membership || jsonb_build_array(
            v_closed || jsonb_build_object('successor_association_version', v_version));
    END IF;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION operations.apply_repair_membership(bigint, uuid, uuid, uuid, jsonb)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.apply_repair_membership(bigint, uuid, uuid, uuid, jsonb)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0428_cross_client_installation_history"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(
            FORWARD_SQL,
            "DROP FUNCTION operations.apply_repair_membership(bigint, uuid, uuid, uuid, jsonb)",
        ),
    ]
