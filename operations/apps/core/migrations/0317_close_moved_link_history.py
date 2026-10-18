"""Close the link history of source links a merge moved (incident 2026-10-17).

Migration 0315 re-pointed 18 source links of merged-away Computers to the
survivors but left each link's open ``entity_source_link_history`` row naming
the old Computer. ``sync_entity_source_links_from_observations`` closes a
link's open history only when it moves the link itself, so it then tried to
open a second history row next to the stale one and failed on
``uq_entity_source_link_history_open``. That failed every source refresh
from the 0315 deploy on, and with it every resolver and evaluator run.

* The stale open history rows (link and history naming different entities)
  are closed now, as one recorded action; the next sync opens the row for the
  link's current Computer.
* ``operations.move_computer_links`` and ``split_computer_merge`` close the
  moved links' open history, so merges and splits keep it consistent.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'entity_source_link.repair_history',
    'Migration 0315 moved source links without closing their open link history, '
        || 'so every source refresh failed on uq_entity_source_link_history_open.',
    '{"migration": "0317_close_moved_link_history"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0317', NULL, true);

CREATE FUNCTION operations.close_stale_link_history(p_tenant bigint) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    UPDATE operations.entity_source_link_history h
       SET effective_to = GREATEST(now(), h.effective_from + interval '1 microsecond')
      FROM operations.entity_source_links l
     WHERE l.tenant_id = p_tenant AND h.tenant_id = l.tenant_id
       AND h.source_instance_id = l.source_instance_id
       AND h.external_namespace = l.external_namespace
       AND h.parent_external_namespace = l.parent_external_namespace
       AND h.parent_external_id = l.parent_external_id
       AND h.external_id = l.external_id
       AND h.effective_to IS NULL
       AND (h.entity_id, h.entity_class_id) IS DISTINCT FROM (l.entity_id, l.entity_class_id);
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;
REVOKE ALL ON FUNCTION operations.close_stale_link_history(bigint) FROM PUBLIC;

SELECT operations.close_stale_link_history(t.id) FROM operations.tenants t;

CREATE OR REPLACE FUNCTION operations.move_computer_links(
    p_tenant bigint, p_from_entity uuid, p_to_entity uuid, p_reason text
) RETURNS uuid[]
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_links uuid[];
BEGIN
    WITH moved AS (
        UPDATE operations.entity_source_links
           SET entity_id = p_to_entity, reason = left(p_reason, 120)
         WHERE tenant_id = p_tenant AND entity_id = p_from_entity
        RETURNING id
    )
    SELECT coalesce(array_agg(id), '{}') INTO v_links FROM moved;
    -- The link sync opens the history row for the new Computer; the old one
    -- must be closed first or the sync cannot (one open row per link).
    PERFORM operations.close_stale_link_history(p_tenant);
    PERFORM operations.retire_entity_relationships(p_tenant, p_from_entity, 'computer_merged');
    RETURN v_links;
END
$fn$;

CREATE OR REPLACE FUNCTION operations.split_computer_merge(
    p_merge uuid,
    p_reason text,
    p_actor_kind text DEFAULT 'operator',
    p_actor_id bigint DEFAULT NULL,
    p_process text DEFAULT ''
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    m operations.computer_merges%ROWTYPE;
    v_action uuid;
BEGIN
    SELECT * INTO m FROM operations.computer_merges WHERE id = p_merge FOR UPDATE;
    IF m.id IS NULL THEN
        RAISE EXCEPTION 'split_computer_merge: unknown merge';
    END IF;
    IF m.split_at IS NOT NULL THEN
        RAISE EXCEPTION 'split_computer_merge: this merge was already split';
    END IF;
    IF p_reason IS NULL OR p_reason = '' THEN
        RAISE EXCEPTION 'split_computer_merge: a reason is required';
    END IF;
    PERFORM set_config('operations.tenant_id', m.tenant_id::text, true);
    v_action := operations.begin_change(
        'computer.split', p_reason,
        jsonb_build_object('merge_id', m.id, 'survivor_id', m.survivor_id,
                           'absorbed_id', m.absorbed_id),
        p_actor_kind, p_actor_id, coalesce(p_process, ''), '', m.tenant_id, true);

    UPDATE operations.computer_merges
       SET split_action_id = v_action, split_at = now()
     WHERE id = m.id;
    UPDATE operations.devices
       SET deleted_at = NULL, deleted_reason = ''
     WHERE id = m.absorbed_id;
    -- Only the memberships this merge moved, and only if they are still on
    -- the survivor; anything that moved since stays where it is.
    UPDATE operations.entity_observation_current
       SET device_id = m.absorbed_id
     WHERE tenant_id = m.tenant_id AND device_id = m.survivor_id
       AND observation_id = ANY(m.moved_observation_ids);
    -- The links the merge moved go back; the survivor's relationship edges
    -- are re-derived from the evidence that now follows them (migration 0315).
    UPDATE operations.entity_source_links link
       SET entity_id = absorbed.entity_id,
           reason = left('split from ' || m.survivor_id::text, 120)
      FROM operations.devices absorbed, operations.devices survivor
     WHERE absorbed.id = m.absorbed_id AND survivor.id = m.survivor_id
       AND link.tenant_id = m.tenant_id AND link.id = ANY(m.moved_link_ids)
       AND link.entity_id = survivor.entity_id;
    PERFORM operations.close_stale_link_history(m.tenant_id);
    PERFORM operations.retire_entity_relationships(
        m.tenant_id, (SELECT entity_id FROM operations.devices WHERE id = m.survivor_id),
        'computer_split');
    UPDATE operations.findings
       SET subject_id = m.absorbed_id,
           finding_details = (finding_details - 'merge')
               || jsonb_build_object('split', jsonb_build_object(
                      'merge_id', m.id::text, 'back_to_device_id', m.absorbed_id::text))
     WHERE tenant_id = m.tenant_id AND subject_type = 'device'
       AND subject_id = m.survivor_id
       AND id = ANY(m.moved_finding_ids)
       AND finding_details -> 'merge' ->> 'from_device_id' = m.absorbed_id::text;
END
$fn$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0316_retire_source_record_withdrawn"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
