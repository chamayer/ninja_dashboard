"""A merge moves the absorbed Computer's source links (ADR-0032 "Merge and split").

Found in production 2026-10-16 after the first 32 automatic merges: the merge
moved observations but left the absorbed Computer's source links on its
entity, so attribute claims and relationship evidence still resolved to the
tombstone. The projector then had two active "OS installation runs on
Computer" edges for one OS installation and failed every batch
("relationship source cardinality would be exceeded"), leaving 18 links and
28 edges stale.

* ``operations.move_computer_links``: re-points one entity's source links to
  another and retires the first entity's active relationship edges
  (``no_evidence`` / ``computer_merged``, input hash cleared, tuples queued),
  so the projector re-derives them from the evidence that now follows the
  links.
* ``merge_computers`` calls it and records the moved links
  (``computer_merges.moved_link_ids``); ``split_computer_merge`` moves only
  those links back and retires the survivor's edges the same way.
* Remediation, as one recorded action: the open merges' links are moved and
  recorded, and the edges of every merged-away Computer are retired.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.computer_merges
    ADD COLUMN moved_link_ids uuid[] NOT NULL DEFAULT '{}';
UPDATE operations.change_history_registry
   SET recorded_columns = recorded_columns || ARRAY['moved_link_ids']::text[]
 WHERE table_name = 'computer_merges' AND NOT ('moved_link_ids' = ANY(recorded_columns));

CREATE FUNCTION operations.retire_entity_relationships(
    p_tenant bigint, p_entity uuid, p_reason text
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_count integer;
BEGIN
    WITH retired AS (
        UPDATE operations.entity_relationships
           SET status = 'no_evidence', selection_reason = left(p_reason, 40),
               selected_authority_tier = NULL, selected_authority_priority = NULL,
               input_hash = '\x'::bytea, projected_at = now(), version = version + 1
         WHERE tenant_id = p_tenant AND status = 'active'
           AND (source_entity_id = p_entity OR target_entity_id = p_entity)
        RETURNING tenant_id, relationship_type_id, source_entity_id, target_entity_id
    ), queued AS (
        INSERT INTO operations.entity_relationship_dirty
            (version, id, queued_at, reason, source_entity_id, target_entity_id, tenant_id,
             relationship_type_id)
        SELECT 1, gen_random_uuid(), now(), left(p_reason, 40), source_entity_id,
               target_entity_id, tenant_id, relationship_type_id
          FROM retired
        ON CONFLICT (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
        DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM retired;
    RETURN v_count;
END
$fn$;

CREATE FUNCTION operations.move_computer_links(
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
    PERFORM operations.retire_entity_relationships(p_tenant, p_from_entity, 'computer_merged');
    RETURN v_links;
END
$fn$;

CREATE OR REPLACE FUNCTION operations.merge_computers(
    p_survivor uuid,
    p_absorbed uuid,
    p_reason text,
    p_evidence jsonb DEFAULT '{}'::jsonb,
    p_actor_kind text DEFAULT 'process',
    p_actor_id bigint DEFAULT NULL,
    p_process text DEFAULT ''
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    s operations.devices%ROWTYPE;
    a operations.devices%ROWTYPE;
    v_action uuid;
    v_merge uuid;
    v_observations uuid[];
    v_findings uuid[];
    v_links uuid[];
BEGIN
    SELECT * INTO s FROM operations.devices WHERE id = p_survivor FOR UPDATE;
    SELECT * INTO a FROM operations.devices WHERE id = p_absorbed FOR UPDATE;
    IF s.id IS NULL OR a.id IS NULL THEN
        RAISE EXCEPTION 'merge_computers: unknown Computer';
    END IF;
    IF s.id = a.id THEN
        RAISE EXCEPTION 'merge_computers: a Computer cannot absorb itself';
    END IF;
    IF s.deleted_at IS NOT NULL OR a.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'merge_computers: both Computers must be current';
    END IF;
    IF s.tenant_id <> a.tenant_id OR s.client_id <> a.client_id THEN
        RAISE EXCEPTION 'merge_computers: Computers of different clients are never merged';
    END IF;
    PERFORM set_config('operations.tenant_id', s.tenant_id::text, true);

    v_action := operations.begin_change(
        CASE WHEN p_actor_kind = 'operator' THEN 'computer.merge' ELSE 'computer.merge.automatic' END,
        p_reason,
        coalesce(p_evidence, '{}'::jsonb)
            || jsonb_build_object('survivor_id', s.id, 'absorbed_id', a.id),
        p_actor_kind, p_actor_id, coalesce(p_process, ''), '', s.tenant_id, true);

    WITH moved AS (
        UPDATE operations.entity_observation_current
           SET device_id = s.id
         WHERE tenant_id = s.tenant_id AND device_id = a.id
        RETURNING observation_id
    )
    SELECT coalesce(array_agg(observation_id), '{}') INTO v_observations FROM moved;

    WITH moved AS (
        UPDATE operations.findings
           SET subject_id = s.id,
               finding_details = finding_details || jsonb_build_object(
                   'merge', jsonb_build_object(
                       'reason', 'merged_device',
                       'from_device_id', a.id::text,
                       'into_device_id', s.id::text))
         WHERE tenant_id = s.tenant_id AND subject_type = 'device' AND subject_id = a.id
        RETURNING id
    )
    SELECT coalesce(array_agg(id), '{}') INTO v_findings FROM moved;

    -- Condition scope and assessments follow the findings; where the survivor
    -- already has the same scope its current assessment is kept.
    INSERT INTO operations.condition_participants
        (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
    SELECT tenant_id, row_kind, finding_id, participant_kind, s.id, participant_role
      FROM operations.condition_participants
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id
    ON CONFLICT DO NOTHING;
    DELETE FROM operations.condition_participants
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id;
    INSERT INTO operations.condition_assessments
        (tenant_id, row_kind, finding_id, participant_kind, participant_id,
         participant_role, condition_identity, policy_version, policy_digest,
         coverage, response, reevaluation_key, currentness, assessed_at)
    SELECT tenant_id, row_kind, finding_id, participant_kind, s.id,
           participant_role, condition_identity, policy_version, policy_digest,
           coverage, response, reevaluation_key, currentness, assessed_at
      FROM operations.condition_assessments
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id
    ON CONFLICT DO NOTHING;
    DELETE FROM operations.condition_assessments
     WHERE tenant_id = s.tenant_id AND participant_kind = 'device' AND participant_id = a.id;

    -- Current software inventory has one row per Computer and product: fold a
    -- collision into the survivor's row, then move the rest.
    UPDATE operations.software_installations_current winner
       SET publisher = COALESCE(winner.publisher, losing.publisher),
           version = CASE WHEN losing.last_observed_at > winner.last_observed_at
                          THEN COALESCE(losing.version, winner.version)
                          ELSE winner.version END,
           install_location = COALESCE(winner.install_location, losing.install_location),
           install_date = COALESCE(winner.install_date, losing.install_date),
           first_observed_at = LEAST(winner.first_observed_at, losing.first_observed_at),
           last_observed_at = GREATEST(winner.last_observed_at, losing.last_observed_at),
           refreshed_at = GREATEST(winner.refreshed_at, losing.refreshed_at)
      FROM operations.software_installations_current losing
     WHERE winner.tenant_id = s.tenant_id AND losing.tenant_id = s.tenant_id
       AND winner.client_id = losing.client_id
       AND winner.device_id = s.id AND losing.device_id = a.id
       AND winner.canonical_name = losing.canonical_name;
    DELETE FROM operations.software_installations_current losing
     WHERE losing.tenant_id = s.tenant_id AND losing.device_id = a.id
       AND EXISTS (SELECT 1 FROM operations.software_installations_current winner
                    WHERE winner.tenant_id = losing.tenant_id
                      AND winner.client_id = losing.client_id
                      AND winner.device_id = s.id
                      AND winner.canonical_name = losing.canonical_name);
    UPDATE operations.software_installations_current
       SET device_id = s.id
     WHERE tenant_id = s.tenant_id AND device_id = a.id;

    -- The absorbed Computer's source links now name the survivor, so claims
    -- and relationship evidence re-derive onto it (migration 0315).
    v_links := operations.move_computer_links(s.tenant_id, a.entity_id, s.entity_id,
                                              'merged into ' || s.id::text);

    INSERT INTO operations.computer_merges
        (tenant_id, client_id, survivor_id, absorbed_id, action_id, reason, evidence,
         moved_observation_ids, moved_finding_ids, moved_link_ids)
    VALUES (s.tenant_id, s.client_id, s.id, a.id, v_action, p_reason,
            coalesce(p_evidence, '{}'::jsonb), v_observations, v_findings, v_links)
    RETURNING id INTO v_merge;

    UPDATE operations.devices
       SET deleted_at = now(), deleted_reason = 'merged'
     WHERE id = a.id;
    RETURN v_merge;
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

REVOKE ALL ON FUNCTION operations.retire_entity_relationships(bigint, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.move_computer_links(bigint, uuid, uuid, text) FROM PUBLIC;

-- Remediation of the merges made before this migration.
SELECT operations.begin_change(
    'computer.merge.repair_links',
    'Merges before migration 0315 left the absorbed Computer''s source links behind.',
    '{"migration": "0315_merge_moves_source_links"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0315', NULL, true);
UPDATE operations.computer_merges m
   SET moved_link_ids = operations.move_computer_links(
           m.tenant_id, absorbed.entity_id, survivor.entity_id,
           'merged into ' || m.survivor_id::text)
  FROM operations.devices absorbed, operations.devices survivor
 WHERE absorbed.id = m.absorbed_id AND survivor.id = m.survivor_id
   AND m.split_at IS NULL;
SELECT operations.retire_entity_relationships(d.tenant_id, d.entity_id, 'computer_merged')
  FROM operations.devices d
 WHERE d.deleted_at IS NOT NULL AND d.deleted_reason = 'merged'
   AND EXISTS (SELECT 1 FROM operations.entity_relationships r
                WHERE r.status = 'active'
                  AND (r.source_entity_id = d.entity_id OR r.target_entity_id = d.entity_id));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0314_computer_history"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
