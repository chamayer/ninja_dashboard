"""One merge and split operation for Computers, recorded and reversible (ADR-0032).

* ``operations.computer_merges``: one row per merge: survivor, absorbed
  Computer, the change action, reason, evidence, the observations and findings
  the merge moved, and the split that reversed it, if any. Covered by the
  change history.
* ``operations.merge_computers(...)``: the merge the operator pages and the
  automatic merge pass both use. It moves observations, device findings
  (recording the merge on each), condition participants and assessments, and
  software installations to the survivor, tombstones the absorbed Computer
  with reason ``merged`` and records the relation. Same logic as the former
  ``views._merge_devices``, now in one place.
* ``operations.split_computer_merge(...)``: undoes a merge's memberships, not
  everything since: it reopens the absorbed Computer, returns the observations
  the merge moved that are still on the survivor, and moves back only the
  findings whose recorded merge provenance names the absorbed Computer. Later
  history stays where it was written; derived state is recomputed by the next
  cycle.
* A deferred constraint trigger requires a merge relation for every Computer
  tombstoned with reason ``merged``, so no other path can claim a merge.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.computer_merges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL,
    client_id uuid NOT NULL,
    survivor_id uuid NOT NULL REFERENCES operations.devices(id),
    absorbed_id uuid NOT NULL REFERENCES operations.devices(id),
    action_id uuid NOT NULL REFERENCES operations.change_actions(id),
    reason text NOT NULL CHECK (reason <> ''),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    moved_observation_ids uuid[] NOT NULL DEFAULT '{}',
    moved_finding_ids uuid[] NOT NULL DEFAULT '{}',
    merged_at timestamptz NOT NULL DEFAULT now(),
    split_action_id uuid NULL REFERENCES operations.change_actions(id),
    split_at timestamptz NULL,
    CHECK (survivor_id <> absorbed_id),
    CHECK ((split_action_id IS NULL) = (split_at IS NULL))
);
CREATE INDEX computer_merges_survivor ON operations.computer_merges (survivor_id);
CREATE UNIQUE INDEX computer_merges_one_open_per_absorbed
    ON operations.computer_merges (absorbed_id) WHERE split_at IS NULL;
ALTER TABLE operations.computer_merges ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.computer_merges FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.computer_merges FROM PUBLIC;
GRANT SELECT ON operations.computer_merges TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'computer_merges', 'covered', 'platform or operator decision or state',
    ARRAY['id','tenant_id','client_id','survivor_id','absorbed_id','action_id','reason',
          'evidence','moved_observation_ids','moved_finding_ids','merged_at',
          'split_action_id','split_at']::text[],
    '{}'::text[], ARRAY['id']::text[], 'survivor_id', NULL, NULL, 'client_id', FALSE, 'trigger'
);
SELECT operations.enable_change_history('computer_merges');

CREATE FUNCTION operations.merge_computers(
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

    INSERT INTO operations.computer_merges
        (tenant_id, client_id, survivor_id, absorbed_id, action_id, reason, evidence,
         moved_observation_ids, moved_finding_ids)
    VALUES (s.tenant_id, s.client_id, s.id, a.id, v_action, p_reason,
            coalesce(p_evidence, '{}'::jsonb), v_observations, v_findings)
    RETURNING id INTO v_merge;

    UPDATE operations.devices
       SET deleted_at = now(), deleted_reason = 'merged'
     WHERE id = a.id;
    RETURN v_merge;
END
$fn$;

CREATE FUNCTION operations.split_computer_merge(
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

CREATE FUNCTION operations.require_merge_relation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF NEW.deleted_reason = 'merged' AND NEW.deleted_at IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM operations.computer_merges
                        WHERE absorbed_id = NEW.id AND split_at IS NULL) THEN
        RAISE EXCEPTION 'Computer % is marked merged without a merge relation', NEW.id;
    END IF;
    RETURN NULL;
END
$fn$;
CREATE CONSTRAINT TRIGGER require_merge_relation
    AFTER INSERT OR UPDATE OF deleted_reason, deleted_at ON operations.devices
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION operations.require_merge_relation();

REVOKE ALL ON FUNCTION operations.merge_computers(uuid, uuid, text, jsonb, text, bigint, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.merge_computers(uuid, uuid, text, jsonb, text, bigint, text)
    TO operations_app, ninja_ingest;
REVOKE ALL ON FUNCTION operations.split_computer_merge(uuid, text, text, bigint, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.split_computer_merge(uuid, text, text, bigint, text)
    TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0307_identity_match_hard_conflicts"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
